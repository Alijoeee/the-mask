"""The Word package: a .docx file held in memory, its parts, and a new file written from them.

A .docx is a zip of parts, most of them XML (the Open Packaging Conventions). ``DocxPackage.open``
reads every entry into memory and is done with the file, so the original is never touched again;
``save`` always writes a new one. A part's XML is parsed the first time it is asked for and kept,
and what ``raw`` and ``save`` give for it is that tree as it is now, changes included. A file that
is not a Word file, or that Word has encrypted with a password, is refused with a message the
owner can act on.
"""

from __future__ import annotations

import copy
import io
import lzma
import posixpath
import re
import struct
import zipfile
import zlib
from collections.abc import Callable
from functools import partial
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

from themask.errors import ProtectedFileError, UnsupportedFileError

NOT_A_DOCX_MESSAGE = (
    "This is not a Word .docx file. If it is an old .doc, open it in Word and save as .docx."
)
PROTECTED_MESSAGE = "This file is protected or encrypted. Please provide an unprotected copy."

# The prefixes the Word code uses in find() and xpath(), with their namespaces.
NS: dict[str, str] = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "v": "urn:schemas-microsoft-com:vml",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
# The namespaces of the package's own bookkeeping: [Content_Types].xml and the .rels parts.
TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

DOCUMENT = "word/document.xml"
CONTENT_TYPES = "[Content_Types].xml"

_REL_TYPES = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_OFFICE_DOCUMENT = f"{_REL_TYPES}/officeDocument"  # names the main document
# The kinds of text part after the main document, in reading order, each with its content type
# (compared without case, as content types are) and its relationship type. A part is of a kind
# when its content type says so (ruling R18) or when the main document relates to it with that
# kind's relationship, which is how Word finds it whatever its content type (ruling R20).
_WML = "application/vnd.openxmlformats-officedocument.wordprocessingml"
_TEXT_KINDS = tuple(
    (f"{_WML}.{kind}+xml".casefold(), f"{_REL_TYPES}/{kind}")
    for kind in ("header", "footer", "footnotes", "endnotes")
)
_ENDS_IN_A_NUMBER = re.compile(r"([0-9]+)\.[^.]*$")  # the digits before a file's extension

# Every OLE compound file starts with these bytes: an old binary .doc does, and so does a .docx
# that Word has encrypted with a password. Only the encrypted one has these two streams, whose
# names its directory stores in UTF-16.
_COMPOUND_FILE = bytes.fromhex("D0CF11E0A1B11AE1")
_ENCRYPTION_STREAMS = tuple(n.encode("utf-16-le") for n in ("EncryptionInfo", "EncryptedPackage"))

# What reading a zip can raise when the bytes are not a zip, or an entry cannot be read back:
# a broken directory, a failed checksum, damaged or cut-off compressed data, an unknown
# compression method, an entry encrypted with a zip password, a name that is not UTF-8.
_UNREADABLE_ZIP = (
    zipfile.BadZipFile,
    zlib.error,
    lzma.LZMAError,
    OSError,
    EOFError,
    struct.error,
    NotImplementedError,
    RuntimeError,
    ValueError,
)

_ZIP_TIME = (1980, 1, 1, 0, 0, 0)  # the date Word itself gives every entry of a .docx


class DocxPackage:
    """A Word file in memory: every part by its name in the zip, in the zip's order."""

    def __init__(self, parts: dict[str, bytes], source: Path | None = None) -> None:
        """A package of ``parts``; ``source`` is the file they came from, never written to."""
        self._raw = dict(parts)
        self._trees: dict[str, etree._Element] = {}
        self._source = source

    @classmethod
    def open(cls, path: Path) -> DocxPackage:
        """The Word file at ``path``, read into memory.

        Raises ProtectedFileError for a file Word has encrypted with a password, and
        UnsupportedFileError for anything else that is not a .docx: an old .doc, a damaged or
        non-zip file, a zip without word/document.xml or without [Content_Types].xml (which
        tells the text parts apart), or one whose main document is not a Word document: a
        "Strict Open XML" document, whose text this package cannot see, or one with a DOCTYPE.
        """
        data = path.read_bytes()
        if data.startswith(_COMPOUND_FILE):
            if any(stream in data for stream in _ENCRYPTION_STREAMS):
                raise ProtectedFileError(PROTECTED_MESSAGE)
            raise UnsupportedFileError(NOT_A_DOCX_MESSAGE)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                parts = {i.filename: archive.read(i) for i in archive.infolist() if not i.is_dir()}
        except _UNREADABLE_ZIP as error:
            raise UnsupportedFileError(NOT_A_DOCX_MESSAGE) from error
        if CONTENT_TYPES not in parts or DOCUMENT not in parts:
            raise UnsupportedFileError(NOT_A_DOCX_MESSAGE)
        package = cls(parts, path)
        main = package._main_part()
        if main is None or _root_tag(parts[main]) != f"{{{NS['w']}}}document":
            raise UnsupportedFileError(NOT_A_DOCX_MESSAGE)
        return package

    def copy(self) -> DocxPackage:
        """A package of its own with the same parts: changing one never changes the other."""
        twin = DocxPackage(self._raw, self._source)
        twin._trees = {name: copy.deepcopy(root) for name, root in self._trees.items()}
        return twin

    def names(self) -> list[str]:
        """The names of the parts, in the order of the zip; parts added later come last."""
        return list(self._raw)

    def xml(self, name: str) -> etree._Element:
        """The root element of part ``name``, parsed the first time and the same object after.

        Changes to the tree are kept: ``raw`` and ``save`` write the tree as it is then. XML
        comments and processing instructions are left out of it. Raises KeyError when there is no
        such part and UnsupportedFileError when it is not valid XML or has a DOCTYPE.
        """
        root = self._trees.get(name)
        if root is None:
            root = self._trees[name] = _parse(self._raw[name])
        return root

    def raw(self, name: str) -> bytes:
        """The bytes of part ``name``: its tree written out, if it has been parsed."""
        root = self._trees.get(name)
        return self._raw[name] if root is None else _serialize(root)

    def set_raw(self, name: str, data: bytes) -> None:
        """Gives part ``name`` these bytes, replacing its tree; a new name is added at the end."""
        self._raw[name] = data
        self._trees.pop(name, None)

    def rels_of(self, part_name: str) -> etree._Element:
        """The relationships of a part: ``word/_rels/document.xml.rels`` for the document.

        ``""`` is the package itself (``_rels/.rels``). Raises KeyError when the part has no
        relationships part.
        """
        return self.xml(_rels_name(part_name))

    def remove_part(self, name: str) -> None:
        """Takes part ``name`` out of the package, and everything that refers to it.

        That is: the zip entry, the part's own relationships part, every relationship in any
        .rels part whose target is this part, and its Override in [Content_Types].xml. Nothing
        happens for a part that is not there.
        """
        for gone in (name, _rels_name(name)):
            self._raw.pop(gone, None)
            self._trees.pop(gone, None)
        for rels in [n for n in self._raw if _is_rels(n)]:
            folder = posixpath.dirname(posixpath.dirname(rels))  # where its targets are read from
            self._drop_children(rels, partial(_relationships_to, folder, name))
        if CONTENT_TYPES in self._raw:
            self._drop_children(CONTENT_TYPES, partial(_overrides_of, name))

    def save(self, path: Path) -> None:
        """Writes the package as a new .docx at ``path``, [Content_Types].xml first.

        Raises ValueError when ``path`` is the file the package was opened from: the original is
        never written to.
        """
        if (
            self._source is not None
            and path.exists()
            and self._source.exists()
            and path.samefile(self._source)
        ):
            raise ValueError("A Word file is never saved over the file it was opened from.")
        names = self.names()
        if CONTENT_TYPES in names:  # Word looks for it first
            names.remove(CONTENT_TYPES)
            names.insert(0, CONTENT_TYPES)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                entry = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, self.raw(name))

    @property
    def TEXT_PARTS(self) -> list[str]:  # upper case: the name the plan gives it
        """The parts that hold the document's text, in reading order.

        First the main document: the part the package's officeDocument relationship names, else
        ``word/document.xml``. Then the headers, the footers, the footnotes and the endnotes:
        the parts whose content type says so, and those the main document relates to as such
        whatever their content type, since Word shows those too. Within each kind, the parts
        whose names end in a number come in numeric order (header2 before header10), then the
        others in the package's order; no part comes twice. Not among them: comments, removed
        before masking, and any other part typed as a main document, such as the whole .docx an
        altChunk embeds, which the cleaner removes.
        """
        main = self._main_part()
        if main is None:
            return []
        types = self._content_types()
        related = self._relationships(main)
        parts = [main]
        for content_type, relationship in _TEXT_KINDS:
            of_kind = {name for kind, name in related if kind == relationship}
            parts += _in_number_order(
                [
                    n
                    for n in self._raw
                    if n not in parts and (n in of_kind or types.get(n) == content_type)
                ]
            )
        return parts

    def _drop_children(
        self, name: str, doomed: Callable[[etree._Element], list[etree._Element]]
    ) -> None:
        """Removes from part ``name`` the children ``doomed`` picks from its root.

        A part that loses nothing is left as it was, unparsed if it was unparsed, so its bytes
        are written out unchanged.
        """
        parsed_before = name in self._trees
        root = self._tree(name)
        children = doomed(root)
        for child in children:
            root.remove(child)
        if children and not parsed_before:
            self._trees[name] = root

    def _main_part(self) -> str | None:
        """The part the package's officeDocument relationship names, else word/document.xml."""
        for kind, name in self._relationships(""):
            if kind == _OFFICE_DOCUMENT:
                return name
        return DOCUMENT if DOCUMENT in self._raw else None

    def _relationships(self, source: str) -> list[tuple[str, str]]:
        """(type, part) for each relationship of part ``source`` ("" for the package itself).

        In the order of its relationships part, and only those to a part the package has.
        """
        rels = _rels_name(source)
        if rels not in self._raw:
            return []
        folder = posixpath.dirname(source)
        by_name = {unquote(n).casefold(): n for n in self._raw}
        found: list[tuple[str, str]] = []
        for r in self._tree(rels).iterchildren(f"{{{RELS_NS}}}Relationship"):
            internal = r.get("TargetMode") != "External"
            target = _target_part(folder, r.get("Target", "")) if internal else None
            name = None if target is None else by_name.get(unquote(target).casefold())
            if name is not None:
                found.append((r.get("Type", ""), name))
        return found

    def _tree(self, name: str) -> etree._Element:
        """Part ``name`` parsed: its tree if it has one, else a new tree that is not kept."""
        root = self._trees.get(name)
        return _parse(self._raw[name]) if root is None else root

    def _content_types(self) -> dict[str, str]:
        """The content type of each part that has one, in lower case.

        A part's type is its Override in [Content_Types].xml, else the Default for its
        extension, as the Open Packaging Conventions define it.
        """
        if CONTENT_TYPES not in self._raw:
            return {}
        table = self._tree(CONTENT_TYPES)
        overrides = {
            unquote(o.get("PartName", "").lstrip("/")).casefold(): o.get("ContentType", "")
            for o in table.iterchildren(f"{{{TYPES_NS}}}Override")
        }
        defaults = {
            d.get("Extension", "").casefold(): d.get("ContentType", "")
            for d in table.iterchildren(f"{{{TYPES_NS}}}Default")
        }
        types: dict[str, str] = {}
        for name in self._raw:
            found = overrides.get(unquote(name).casefold())
            if found is None:
                file = posixpath.basename(name)
                found = defaults.get(file.rpartition(".")[2].casefold()) if "." in file else None
            if found is not None:
                types[name] = found.strip().casefold()
        return types


def _parse(data: bytes) -> etree._Element:
    # A parser of its own for each part: an lxml parser must not be used by two threads at once,
    # and the analysis runs in a worker thread. Nothing is fetched and no entity is expanded; a
    # part with a DOCTYPE is refused (Word never writes one, and the entities it declares could
    # hide text: ruling R20). XML comments and processing instructions are dropped, so the text
    # on either side of one inside a w:t is a single text.
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=True, remove_pis=True
    )
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as error:
        raise UnsupportedFileError(NOT_A_DOCX_MESSAGE) from error
    if root.getroottree().docinfo.doctype:
        raise UnsupportedFileError(NOT_A_DOCX_MESSAGE)
    return root


def _serialize(root: etree._Element) -> bytes:
    data: bytes = etree.tostring(
        root.getroottree(), xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return data


def _root_tag(data: bytes) -> str | None:
    """The tag of the root of ``data``; None when it is not XML or has a DOCTYPE. Reads no more."""
    events = etree.iterparse(
        io.BytesIO(data), events=("start",), resolve_entities=False, no_network=True
    )
    try:
        _event, root = next(events)
    except (etree.XMLSyntaxError, StopIteration):
        return None
    return None if root.getroottree().docinfo.doctype else str(root.tag)


def _rels_name(part_name: str) -> str:
    """``word/_rels/document.xml.rels`` for ``word/document.xml``, ``_rels/.rels`` for ``""``."""
    folder, file = posixpath.split(part_name)
    return posixpath.join(folder, "_rels", f"{file}.rels")


def _is_rels(name: str) -> bool:
    return name.endswith(".rels") and posixpath.basename(posixpath.dirname(name)) == "_rels"


def _target_part(folder: str, target: str) -> str | None:
    """The part a relationship target names, read from ``folder``; None when it names none."""
    if not target:
        return None
    path = target.lstrip("/") if target.startswith("/") else posixpath.join(folder, target)
    path = posixpath.normpath(path)
    return None if path in {".", ".."} or path.startswith("../") else path


def _relationships_to(folder: str, name: str, rels: etree._Element) -> list[etree._Element]:
    """The relationships in ``rels``, of a part in ``folder``, whose target is part ``name``."""
    return [
        r
        for r in rels.iterchildren(f"{{{RELS_NS}}}Relationship")
        if r.get("TargetMode") != "External"
        and _same_part(_target_part(folder, r.get("Target", "")), name)
    ]


def _overrides_of(name: str, types: etree._Element) -> list[etree._Element]:
    """The Override elements of [Content_Types].xml that give part ``name`` its type."""
    return [
        o
        for o in types.iterchildren(f"{{{TYPES_NS}}}Override")
        if _same_part(o.get("PartName", "").lstrip("/"), name)
    ]


def _same_part(target: str | None, name: str) -> bool:
    # Part names compare without case and with %-escapes decoded (a target may write a space as
    # %20 where the zip entry has the space itself).
    return target is not None and unquote(target).casefold() == unquote(name).casefold()


def _in_number_order(names: list[str]) -> list[str]:
    """``names`` whose file names end in a number, in numeric order, then the rest as they were."""

    def key(name: str) -> tuple[int, int]:
        number = _ENDS_IN_A_NUMBER.search(posixpath.basename(name))
        return (0, int(number.group(1))) if number else (1, 0)

    return sorted(names, key=key)  # a stable sort: equal keys keep the package's order
