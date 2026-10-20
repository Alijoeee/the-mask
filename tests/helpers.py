"""Helpers shared by tests of several modules."""

from __future__ import annotations

import copy
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from lxml import etree

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists
    from themask.export import SourceDoc
    from themask.model import Case
    from themask.review import ReviewState
    from themask.ui.app import AppContext


def plant(src: Path, part: str, payload: bytes, out: Path) -> Path:
    """A copy of the Word file ``src`` at ``out``, with ``payload`` written into ``part``.

    The payload goes just before the part's closing tag, so it lands inside the part's root
    element; a part the file does not have is added, holding the payload alone. Every other entry
    is copied byte for byte, in the zip's order. Returns ``out``.
    """
    with zipfile.ZipFile(src) as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for info, data in entries:
            if info.filename == part:
                closing = data.rindex(b"</")
                data = data[:closing] + payload + data[closing:]
            archive.writestr(info, data)
        if part not in {info.filename for info, _ in entries}:
            archive.writestr(part, payload)
    return out


def reviewed(
    paths: list[Path],
    engine: Engine,
    user_lists: UserLists,
    redline_split: bool = False,
    case: Case | None = None,
) -> tuple[list[SourceDoc], ReviewState]:
    """The files at ``paths`` loaded for an export, analysed, and their review as the app makes it.

    The review works with the case lists the analysis filled. A file added to ``case`` is
    analysed with the case's key, and its review reserves the key's placeholders (ruling R61).
    """
    # Imported here, not at the top: every test that plants a value imports this module.
    from themask.detect.lists import CaseLists
    from themask.detect.pipeline import analyze
    from themask.export import combined_text, load_sources
    from themask.review import ReviewState

    sources = load_sources(paths, redline_split)
    case_lists = CaseLists([], [], set())
    key = case.entries if case is not None else []
    analysis = analyze(combined_text(sources), engine, user_lists, case_lists, seed_entries=key)
    reserved = [entry.placeholder for entry in key]
    names = {entry.placeholder: entry.label for entry in key if entry.label is not None}
    return sources, ReviewState.from_analysis(analysis, user_lists, case_lists, reserved, names)


def analysed(ctx: AppContext, paths: list[Path]) -> tuple[list[SourceDoc], ReviewState]:
    """The files at ``paths`` loaded, analysed and reviewed the way the window does it, with the
    engine and the owner's lists of ``ctx``: what the export dialog is given.
    """
    assert ctx.engine is not None, "the context of a test has its engine"
    return reviewed(paths, ctx.engine, ctx.user_lists)


# What simulate_ai writes, named here rather than taken from the code under test.
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
_COMMENTS_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
_COMMENTS_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)
# A run's properties keep an order (CT_RPr): bold comes after a style and fonts, italics after
# those and bold.
_BEFORE_BOLD = ("rStyle", "rFonts")
_BEFORE_ITALICS = ("rStyle", "rFonts", "b", "bCs")
# The revision id of the run that holds the first half of the split placeholder: Word splits a
# run where an editing session ends, and marks each part with the session's id.
SPLIT_RSID = "00A1B2C3"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)  # every entry's date, so that the file is the same each time


def simulate_ai(masked: Path, out: Path) -> Path:
    """The masked Word file ``masked`` as an AI tool might give it back, written at ``out``.

    The changes are made the same way every time, in the body, and each only where its
    placeholder is there (the banner aside):

    * the first [PERSON_1] is written "[PERSON 1]", the one changed form;
    * each [AMOUNT_1] is put in a run of its own and made bold;
    * the first [COMPANY_1] is split across two runs, the first of them in italics and marked
      with the revision id ``SPLIT_RSID``;
    * a paragraph holding [PERSON_9], a placeholder the case is not meant to hold, is added at
      the end of the body, with a comment on it holding [COMPANY_1]; word/comments.xml, its
      relationship and its content type are added when the file has no comments yet;
    * the banner paragraph is copied in once more, just before that paragraph.

    Every other entry is copied as it is, in the zip's order. Returns ``out``.
    """
    from themask.instruction import BANNER_TEXT, BANNER_TEXT_NAMED

    with zipfile.ZipFile(masked) as archive:
        entries = {info.filename: archive.read(info) for info in archive.infolist()}
    document = etree.fromstring(entries["word/document.xml"])
    body = document.find(_w("body"))
    banner = body.find(_w("p"))
    if banner is None or "".join(banner.itertext()) not in (
        BANNER_TEXT,
        BANNER_TEXT_NAMED,
    ):
        raise ValueError("The masked file does not start with the banner.")

    def first(token: str) -> etree._Element | None:
        """The first w:t of the body that holds ``token``, the banner aside, as the body is now."""
        texts = (t for t in body.iter(_w("t")) if banner not in t.iterancestors())
        return next(
            (t for t in texts if token in (t.text or "") and not _bold_alone(t, token)), None
        )

    first_person = first("[PERSON_1]")
    if first_person is not None:
        first_person.text = first_person.text.replace("[PERSON_1]", "[PERSON 1]", 1)
    while (amount := first("[AMOUNT_1]")) is not None:
        start = amount.text.index("[AMOUNT_1]")
        _add_property(_split_off(amount, start, start + len("[AMOUNT_1]")), "b", _BEFORE_BOLD)
    company = first("[COMPANY_1]")
    if company is not None:
        start = company.text.index("[COMPANY_1]")
        whole = _split_off(company, start, start + len("[COMPANY_1]"))
        half = _split_off(whole.find(_w("t")), 0, len("[COMPANY_1]") // 2)
        _add_property(half, "i", _BEFORE_ITALICS)
        half.set(_w("rsidR"), SPLIT_RSID)

    note = _paragraph("Note from the AI tool: [PERSON_9] should countersign.")
    end = body.find(_w("sectPr"))
    if end is None:
        body.append(note)
    else:
        end.addprevious(note)
    note.addprevious(copy.deepcopy(banner))
    _comment_on(note, "Please confirm that [COMPANY_1] is the right party here.", entries)
    entries["word/document.xml"] = _xml(document)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=_ZIP_TIME), data, zipfile.ZIP_DEFLATED)
    return out


def _w(name: str) -> str:
    return f"{{{_W}}}{name}"


def _xml(root: etree._Element) -> bytes:
    data: bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return data


def _paragraph(text: str) -> etree._Element:
    """A paragraph of one run holding ``text``."""
    p = etree.Element(_w("p"), nsmap={"w": _W})
    t = etree.SubElement(etree.SubElement(p, _w("r")), _w("t"))
    t.text = text
    t.set(_XML_SPACE, "preserve")
    return p


def _bold_alone(t: etree._Element, token: str) -> bool:
    """Whether ``t`` holds ``token`` alone, in a bold run of its own: an amount already done."""
    run = t.getparent()
    alone = [child for child in run if child.tag != _w("rPr")] == [t]
    return t.text == token and alone and run.find(f"{_w('rPr')}/{_w('b')}") is not None


def _split_off(t: etree._Element, start: int, end: int) -> etree._Element:
    """Splits the run of ``t`` so that ``t.text[start:end]`` has a run of its own; returns it.

    What comes before that text in the run, text, tabs or breaks, goes into a run before it, and
    what comes after it into a run after it; each run has the formatting of the run split.
    """
    run = t.getparent()
    properties = run.find(_w("rPr"))
    content = [child for child in run if child.tag != _w("rPr")]
    at = content.index(t)
    text = t.text or ""
    if not text[start:end]:
        raise ValueError("simulate_ai splits off a stretch with text in it.")
    parts = (
        [*content[:at], *_text_nodes(text[:start])],
        _text_nodes(text[start:end]),
        [*_text_nodes(text[end:]), *content[at + 1 :]],
    )
    made: dict[int, etree._Element] = {}
    for index, part in enumerate(parts):
        if part:
            twin = etree.Element(_w("r"))
            if properties is not None:
                twin.append(copy.deepcopy(properties))
            twin.extend(part)
            run.addprevious(twin)
            made[index] = twin
    run.getparent().remove(run)
    return made[1]


def _text_nodes(text: str) -> list[etree._Element]:
    """A w:t holding ``text``, or none for no text."""
    if not text:
        return []
    t = etree.Element(_w("t"))
    t.text = text
    t.set(_XML_SPACE, "preserve")
    return [t]


def _add_property(run: etree._Element, name: str, after: tuple[str, ...]) -> None:
    """Gives ``run`` the property ``w:<name>``, after the ones of ``after`` that it has."""
    properties = run.find(_w("rPr"))
    if properties is None:
        properties = etree.Element(_w("rPr"))
        run.insert(0, properties)
    if properties.find(_w(name)) is not None:
        return
    element = etree.Element(_w(name))
    earlier = [child for child in properties if etree.QName(child).localname in after]
    if earlier:
        earlier[-1].addnext(element)
    else:
        properties.insert(0, element)


def _comment_on(p: etree._Element, text: str, entries: dict[str, bytes]) -> None:
    """Adds a comment holding ``text`` on paragraph ``p``, and the parts Word finds it by."""
    name = "word/comments.xml"
    if name in entries:
        comments = etree.fromstring(entries[name])
        ids = [int(c.get(_w("id"), "0")) for c in comments.iter(_w("comment"))]
        number = str(max(ids, default=-1) + 1)
    else:
        comments = etree.Element(_w("comments"), nsmap={"w": _W})
        number = "0"
        rels = etree.fromstring(entries["word/_rels/document.xml.rels"])
        taken = [int(m[1]) for r in rels if (m := re.fullmatch(r"rId(\d+)", r.get("Id", "")))]
        etree.SubElement(
            rels,
            f"{{{_RELS}}}Relationship",
            Id=f"rId{max(taken, default=0) + 1}",
            Type=_COMMENTS_RELATIONSHIP,
            Target="comments.xml",
        )
        entries["word/_rels/document.xml.rels"] = _xml(rels)
        types = etree.fromstring(entries["[Content_Types].xml"])
        etree.SubElement(
            types,
            f"{{{_TYPES}}}Override",
            PartName="/word/comments.xml",
            ContentType=_COMMENTS_TYPE,
        )
        entries["[Content_Types].xml"] = _xml(types)
    comment = etree.SubElement(
        comments,
        _w("comment"),
        {_w("id"): number, _w("author"): "AI tool", _w("date"): "2026-10-17T09:00:00Z"},
    )
    comment.append(_paragraph(text))
    entries[name] = _xml(comments)
    p.insert(0, etree.Element(_w("commentRangeStart"), {_w("id"): number}))
    p.append(etree.Element(_w("commentRangeEnd"), {_w("id"): number}))
    reference = etree.SubElement(p, _w("r"))
    etree.SubElement(reference, _w("commentReference"), {_w("id"): number})
