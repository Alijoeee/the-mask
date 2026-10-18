"""Word files for the tests of the Word package.

``fixtures`` is the folder of files that only pretend to be Word files. ``make_docx`` writes a
small Word file from a few lines of WordprocessingML, for the cases the corpus does not have
(fields, tabs, nested tables, content controls, odd part names). ``paragraph`` makes a single
``w:p`` element. The namespaces are written out here rather than taken from the code under test.
"""

from __future__ import annotations

import itertools
import re
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from lxml import etree

NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "v": "urn:schemas-microsoft-com:vml",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}
XMLNS = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in NAMESPACES.items())

_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_PACKAGE_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WML = "application/vnd.openxmlformats-officedocument.wordprocessingml"
# For each kind of part make_docx can add: its root element, content type and relationship type.
_KINDS = {
    "header": ("w:hdr", f"{_WML}.header+xml", f"{_REL}/header"),
    "footer": ("w:ftr", f"{_WML}.footer+xml", f"{_REL}/footer"),
    "footnotes": ("w:footnotes", f"{_WML}.footnotes+xml", f"{_REL}/footnotes"),
    "endnotes": ("w:endnotes", f"{_WML}.endnotes+xml", f"{_REL}/endnotes"),
    "comments": ("w:comments", f"{_WML}.comments+xml", f"{_REL}/comments"),
}
_KIND = re.compile(r"word/(header|footer|footnotes|endnotes|comments)\d*\.xml")

MakeDocx = Callable[..., Path]


def paragraph(content: str) -> etree._Element:
    """A ``w:p`` holding ``content``: WordprocessingML that may use the prefixes in NAMESPACES."""
    return etree.fromstring(f"<w:p {XMLNS}>{content}</w:p>")


def _xml(text: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + text).encode()


def _entries(body: str, parts: Mapping[str, str]) -> dict[str, bytes]:
    types = [f'<Override PartName="/word/document.xml" ContentType="{_WML}.document.main+xml"/>']
    relationships = []
    added = {}
    for number, (name, content) in enumerate(parts.items(), start=1):
        kind = _KIND.fullmatch(name)
        if kind is None:
            raise ValueError(f"make_docx does not know what kind of part {name} is.")
        root, content_type, relationship_type = _KINDS[kind.group(1)]
        added[name] = _xml(f"<{root} {XMLNS}>{content}</{root}>")
        types.append(f'<Override PartName="/{name}" ContentType="{content_type}"/>')
        relationships.append(
            f'<Relationship Id="rId{number}" Type="{relationship_type}"'
            f' Target="{name.removeprefix("word/")}"/>'
        )
    return {
        "[Content_Types].xml": _xml(
            f'<Types xmlns="{_TYPES}">'
            '<Default Extension="rels"'
            ' ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{''.join(types)}</Types>"
        ),
        "_rels/.rels": _xml(
            f'<Relationships xmlns="{_PACKAGE_RELS}"><Relationship Id="rId1"'
            f' Type="{_REL}/officeDocument" Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": _xml(f"<w:document {XMLNS}><w:body>{body}</w:body></w:document>"),
        "word/_rels/document.xml.rels": _xml(
            f'<Relationships xmlns="{_PACKAGE_RELS}">{"".join(relationships)}</Relationships>'
        ),
        **added,
    }


@pytest.fixture
def fixtures() -> Path:
    """The folder with not-a-docx.doc, corrupt.docx and encrypted.docx (see make_fixtures.py)."""
    return Path(__file__).resolve().parents[1] / "docx" / "fixtures"


@pytest.fixture
def make_docx(tmp_path: Path) -> MakeDocx:
    """Writes a small Word file and returns its path.

    ``make_docx(body, parts=None, raw=None)``: ``body`` is the content of ``w:body``. ``parts``
    maps the name of a header, footer, footnotes, endnotes or comments part to the content of its
    root element; each is given its content type and a relationship from the document. ``raw``
    adds or replaces whole zip entries, byte for byte.
    """
    numbers = itertools.count(1)

    def make(
        body: str,
        parts: Mapping[str, str] | None = None,
        raw: Mapping[str, bytes] | None = None,
    ) -> Path:
        entries = _entries(body, parts or {})
        entries.update(raw or {})
        path = tmp_path / f"made-{next(numbers)}.docx"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
            for name, data in entries.items():
                package.writestr(name, data)
        return path

    return make
