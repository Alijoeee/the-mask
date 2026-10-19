"""Restoring a Word file: the real values put back into the .docx an AI tool gives back.

``restore_docx`` reads the AI's file into memory and writes the restored copy as a new file,
"<name> – restored.docx", next to it or in the folder asked for, and never over a file that is
there; the AI's file itself is never written to. Every paragraph of the text parts (the document,
its headers, footers, footnotes and endnotes) and of the comments is restored the way
``restore_text`` restores a text, and one report counts them all: exact placeholders are always
put back, changed ones only once the owner confirms them, unknown ones are left as written. The
value goes in through ``replace_in_paragraph``, so it takes the formatting of the placeholder's
first run, also where Word split the placeholder across runs, and a tab or line break in a value
becomes a ``w:tab`` or ``w:br`` as Word writes them. A text box's fallback copy, which Word keeps
for old readers, is restored the same way but not counted again.

The AI's tracked changes are restored too (ruling R88), so that neither accepting nor rejecting
one brings a placeholder back. A paragraph is restored first with every change accepted, its
insertions with it, then with every change rejected, for the text only that view holds: what the
AI deleted (``w:del``) or moved away (``w:moveFrom``). Each is counted like any other, and the
text the two views share is restored and reported once.

The MASK's banner and its instruction for the AI are taken out (``banner_spans``). A paragraph
of the body that holds nothing but one of them is deleted, with an empty paragraph right after
it; elsewhere (a table cell, a header, a note, a comment) the paragraph stays, emptied, since
the place must keep a paragraph, and so does a paragraph that holds anything besides the line.
A paragraph that ends a section is never deleted, as its section would go with it.

Not restored: placeholders in field instructions, link addresses and bookmark names. The AI
reads and writes the text, not those, and changing them could break the field or the link.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from themask.docx.cleaner import _comment_parts
from themask.docx.package import NS, DocxPackage
from themask.docx.reader import paragraph_nodes
from themask.docx.restorer import replace_in_paragraph
from themask.model import Case
from themask.restore.matcher import banner_spans
from themask.restore.report import RestoreReport
from themask.restore.text import TextRestorer

_W = f"{{{NS['w']}}}"
_BODY = f"{_W}body"
_P = f"{_W}p"
_PPR = f"{_W}pPr"
_R = f"{_W}r"
_RPR = f"{_W}rPr"
_SECT_PR = f"{_W}sectPr"
_FALLBACK = f"{{{NS['mc']}}}Fallback"
# What a tracked change took out: deleted text, and text moved away from here.
_TAKEN_OUT = (f"{_W}del", f"{_W}moveFrom")


def restore_docx(
    src: Path, case: Case, confirm_altered: bool, out_dir: Path | None = None
) -> tuple[Path, RestoreReport]:
    """Restores the AI's Word file ``src`` with the key of ``case``; returns the new file and
    the report of what was done.

    ``confirm_altered`` says the owner confirmed the placeholders the AI changed. The new file
    goes into ``out_dir``, made when it is missing, or else next to ``src``: "<stem> – restored
    .docx", or "<stem> – restored (2).docx", "(3)" ... when that name is taken. Raises what
    ``DocxPackage.open`` raises for a file that is not a Word file or is protected.
    """
    pkg = DocxPackage.open(src)
    restorer = TextRestorer(case, confirm_altered)
    copies = TextRestorer(case, confirm_altered)  # for fallback copies, its report unused
    texts = pkg.TEXT_PARTS
    # The comments' parts, found the way the cleaner finds them; only word/comments.xml holds
    # text, the others (extensions, ids, people) no paragraph.
    parts = texts + [name for name in _comment_parts(pkg, texts[0]) if name not in texts]
    for part in parts:
        doomed: dict[etree._Element, None] = {}
        for p in list(pkg.xml(part).iter(_P)):
            in_copy = next(p.iterancestors(_FALLBACK), None) is not None
            doomed.update(dict.fromkeys(_restore_paragraph(p, copies if in_copy else restorer)))
        for p in doomed:
            p.getparent().remove(p)
    target = _new_file(
        src.parent if out_dir is None else out_dir, f"{src.stem} \N{EN DASH} restored"
    )
    try:
        pkg.save(target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target, restorer.report


def _restore_paragraph(p: etree._Element, restorer: TextRestorer) -> list[etree._Element]:
    """Restores paragraph ``p``; returns the paragraphs to delete once the part is done.

    That is ``p`` when it stands in the body and held one of The MASK's own lines and nothing
    else, with the paragraph after it when that one is empty.
    """
    text, nodes = paragraph_nodes(p, "accepted")
    # A placeholder in a field instruction stays (see the module's docstring).
    instructions = [(node.start, node.end) for node in nodes if node.kind == "instr"]
    edits = restorer.edits(text, keep=instructions)
    if edits:
        replace_in_paragraph(p, "accepted", edits, breaks=True)
    if next(p.iter(*_TAKEN_OUT), None) is not None:
        _restore_taken_out(p, restorer)
    own_line = bool(text) and banner_spans(text) == [(0, len(text))]
    if not (own_line and p.getparent().tag == _BODY and _is_empty(p)):
        return []
    after = p.getnext()
    return [p, after] if after is not None and _is_empty(after) else [p]


def _restore_taken_out(p: etree._Element, restorer: TextRestorer) -> None:
    """Restores the text that the AI's tracked changes took out of paragraph ``p``.

    The paragraph is read with every change rejected, and only the text that view alone holds is
    planned: the rest was restored, and reported, with every change accepted. Field instructions
    stay, as they do there.
    """
    accepted = {node.elem for node in paragraph_nodes(p, "accepted")[1]}
    text, nodes = paragraph_nodes(p, "rejected")
    keep = [(n.start, n.end) for n in nodes if n.elem in accepted or n.kind == "instr"]
    edits = restorer.edits(text, keep=keep)
    if edits:
        replace_in_paragraph(p, "rejected", edits, breaks=True)


def _is_empty(element: etree._Element) -> bool:
    """Whether ``element`` is a paragraph with nothing in it but properties and empty runs.

    A paragraph whose properties end a section (``w:sectPr``) is not: it holds the section's
    page setup.
    """
    return element.tag == _P and all(
        (child.tag == _PPR and child.find(_SECT_PR) is None)
        or (child.tag == _R and all(c.tag == _RPR for c in child))
        for child in element
    )


def _new_file(folder: Path, stem: str) -> Path:
    """A new empty file "<stem>.docx" in ``folder``, made when missing, or "<stem> (2).docx",
    "<stem> (3).docx" ... when the name is taken: a file that is there is never written over.
    """
    folder.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        target = folder / (f"{stem}.docx" if number == 1 else f"{stem} ({number}).docx")
        number += 1
        try:
            target.open("xb").close()  # only a file that is not there yet
        except FileExistsError:
            continue
        return target
