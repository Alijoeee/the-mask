"""The export: from the files the owner chose to masked copies, checked, and the case's key.

``load_sources`` reads each file and prepares the versions of it that will be masked, before the
analysis reads them (ruling R2). A Word file is opened as it is, and nothing changes that package
afterwards; a copy of it has every tracked change accepted and is cleaned (``cleaner.clean``), and
for a redline review of a file with tracked changes a second copy has every change rejected and
is cleaned too. A PDF is first written into a new Word file (``pdf_to_docx``, ruling R73), which
is then prepared like any other. The review works on the text of those prepared copies, joined by
``combined_text``: every file's version after its changes, then the versions before them.

``export_case`` masks a copy of each prepared version with its part of the review's plan, and takes
every value of the case's key out of its link addresses, field instructions and bookmark names
(ruling R82): the review's key, or for a file added to a case the case's whole key as it will be
saved (ruling R83). It puts the banner on top and saves the file under a neutral name in a
private temporary folder, where the leak check searches it for every value of that key. A value
found in more places than the owner left it visible on purpose (ruling R60) blocks the export:
the files are deleted and nothing is saved. Otherwise the detection runs again on the masked
files, for what nobody marked; the files are written into the output folder, never over a file
that is there; and the case's key is saved. If the key cannot be saved, the files written go
again: a masked file without its key could never be restored. A file added to an existing case
keeps the case's code, continues the numbering of its files and adds to its key. Nothing here
writes to the log.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from bisect import bisect_right
from collections.abc import Callable, Collection
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from themask.detect.pipeline import CombinedText
from themask.docx.cleaner import clean
from themask.docx.masker import apply_mask, insert_banner, neutral_name, new_case_code
from themask.docx.package import DocxPackage
from themask.docx.reader import DocText, extract_text, has_revisions
from themask.docx.revisions import accept_all, reject_all
from themask.errors import UnsupportedFileError
from themask.instruction import AI_INSTRUCTION
from themask.leakcheck import (
    LeakHit,
    hits_by_placeholder,
    rescan_detection,
    scan_package,
    unverifiable,
)
from themask.model import Case, Group, KeyEntry, MaskedFile, MaskPlan, Replacement
from themask.pdf.extractor import PdfReport
from themask.pdf.to_docx import pdf_to_docx
from themask.textnorm import normalize

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists
    from themask.review import ReviewState

UNSUPPORTED_MESSAGE = "The MASK reads Word (.docx) and PDF files."

SourceKind = Literal["docx", "pdf"]
Side = Literal["after", "before"]

# The private folders the export and the PDF reading write into: the name says nothing more.
_TEMP_PREFIX = "themask-"


@dataclass
class SourceDoc:
    """A file the owner chose, read and prepared for masking.

    ``pkg`` is the file as it was opened, which nothing changes (for a PDF, the Word file made
    from it). ``pkg_after`` is a copy of it with every tracked change accepted, then cleaned, and
    ``text_after`` that copy's text. ``pkg_before`` and ``text_before`` are the same with every
    change rejected; they are made only for a redline review of a file with tracked changes, and
    are None otherwise. The analysis, the review and the masker all work on the prepared copies,
    so the places of the review's plan are theirs. ``has_revisions`` says whether the file has
    tracked changes, and ``pdf_report`` what reading the PDF left out (None for a Word file).
    """

    path: Path
    kind: SourceKind
    pkg: DocxPackage
    pkg_after: DocxPackage
    text_after: DocText
    pkg_before: DocxPackage | None
    text_before: DocText | None
    has_revisions: bool
    pdf_report: PdfReport | None


@dataclass
class ExportOptions:
    """How to export: where to, as a redline or not, and for which case.

    ``out_dir`` is the folder the masked files go into, made when it is missing.
    ``redline_split`` says the files were loaded for a redline review, each file with tracked
    changes in a version before and after them. ``retention_days`` is how long the case's key is
    kept. ``existing_case`` is the case a file is added to: its review was analysed with the
    case's key and reserves its placeholders, the case keeps its code and date, the new files
    continue its numbering and the key grows. ``existing_codes`` are the codes of the cases the
    store holds, readable or not, which a new case never takes (ruling R74).
    """

    out_dir: Path
    redline_split: bool = False
    retention_days: int = 30
    existing_case: Case | None = None
    existing_codes: Collection[str] = ()


@dataclass
class ExportResult:
    """What an export did.

    ``case`` is the case saved, with its key, and ``outputs`` the masked files written; when the
    export is ``blocked`` the first is None and the second empty, as nothing was saved.
    ``leak_hits`` are all the places the leak check found a value of the key, and
    ``allowed_hits`` those of them that are the occurrences the owner left visible on purpose
    (ruling R60): the export is blocked by the others. When the export makes several files, a
    hit's ``part`` begins with the name of its file, "MASKED-K4F7-2.docx: word/header1.xml"
    (ruling R81). ``unmarked`` holds what the detection finds in the masked files that the owner
    never marked (only after an export that was not blocked), ``unverifiable`` the placeholders
    whose values are too short to be checked, and ``instruction`` the instruction to paste into
    the AI tool.
    """

    case: Case | None
    outputs: list[Path]
    leak_hits: list[LeakHit]
    unmarked: list[Group]
    instruction: str
    blocked: bool
    allowed_hits: list[LeakHit] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)


def load_sources(paths: list[Path], redline_split: bool) -> list[SourceDoc]:
    """The files at ``paths``, each read and prepared for masking (see ``SourceDoc``), in order.

    A file is read as a Word file or as a PDF by its extension, in any case; any other file is
    refused with UnsupportedFileError. With ``redline_split``, a Word file with tracked changes
    is also prepared in its version before them. What reading a file raises comes through:
    UnsupportedFileError and ProtectedFileError for a file The MASK cannot read, ScannedPdfError
    for a PDF without text, OSError for a file that cannot be read at all.
    """
    return [_load(path, redline_split) for path in paths]


def combined_text(sources: list[SourceDoc]) -> CombinedText:
    """The text the analysis and the review work on: the text of each version to mask, named
    "<file name> (after)" and "<file name> (before)". Every file's version after its changes
    comes first, in the order of ``sources``, then the versions before them.
    """
    return _joined(_views(sources))


def export_case(
    sources: list[SourceDoc],
    review: ReviewState,
    options: ExportOptions,
    engine: Engine,
    user_lists: UserLists,
    save_case: Callable[[Case], object],
) -> ExportResult:
    """Masks every version of ``sources`` as ``review`` says, checks the files and saves the case.

    The files are named ``MASKED-<code>.docx`` for one file, ``-1``, ``-2`` ... for several, and
    ``-before`` and ``-after`` for the two versions of a redline (``-1-before`` among several).
    The key is ``review.key_entries()``, or for a file added to a case the case's key merged with
    it, as the case will be saved (ruling R83). Every file has the key's values taken out of its
    addresses, instructions and bookmark names, the values marked in the other files too (ruling
    R82), and is checked for all of them; a placeholder found in more places than the owner left
    visible on purpose blocks the export (ruling R60). Not blocked, the files go into
    ``options.out_dir`` and the case is passed to ``save_case``.

    Raises ValueError, before anything is written, when there is no file, when ``review`` was not
    made on the text of ``sources`` (``combined_text``), when the sources were loaded for a
    redline review but the options say otherwise, and when a file is added to a case whose
    placeholders the review does not reserve (ruling R61). What saving raises comes through,
    after the masked files written are deleted again.
    """
    views = _views(sources)
    combined = _joined(views)
    _check(sources, combined, review, options)
    existing = options.existing_case
    code = existing.id if existing is not None else new_case_code(existing=options.existing_codes)
    names = _file_names(code, sources, existing)
    plans = _plans(review.mask_plan(), combined)
    entries = review.key_entries()
    # A file added to a case is masked and checked for the whole key the case will keep: also for
    # the values its own review did not find in its text (ruling R83).
    key = _merged(existing.entries, entries) if existing is not None else entries
    not_checkable = unverifiable(key)
    # The files in the order they are listed: by source, a redline's version before first.
    order = sorted(range(len(views)), key=lambda i: (views[i].index, views[i].side == "after"))
    staging = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX))
    try:
        staged = [
            _mask(views[i], plans[i], key, staging / names[views[i].index, views[i].side])
            for i in order
        ]
        found = [scan_package(path, key) for path in staged]
        blocking = _blocking([hit for hits in found for hit in hits], _allowances(review.groups))
        if blocking:
            hits = _named(found, staged)
            allowed = [hit for hit in hits if hit.placeholder not in blocking]
            return ExportResult(None, [], hits, [], AI_INSTRUCTION, True, allowed, not_checkable)
        unmarked = _unmarked(staged, engine, user_lists, key)
        outputs, case = _save(staged, sources, key, code, options, save_case)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    hits = _named(found, outputs)  # by the names the files were written under
    return ExportResult(case, outputs, hits, unmarked, AI_INSTRUCTION, False, hits, not_checkable)


# ---- loading ------------------------------------------------------------------------------------


def _load(path: Path, redline_split: bool) -> SourceDoc:
    suffix = path.suffix.casefold()
    report: PdfReport | None = None
    if suffix == ".docx":
        kind: SourceKind = "docx"
        pkg = DocxPackage.open(path)
    elif suffix == ".pdf":
        kind = "pdf"
        pkg, report = _from_pdf(path)
    else:
        raise UnsupportedFileError(UNSUPPORTED_MESSAGE)
    tracked = kind == "docx" and has_revisions(pkg)
    after = _prepared(pkg, accept_all)
    before = _prepared(pkg, reject_all) if redline_split and tracked else None
    text_before = None if before is None else extract_text(before)
    return SourceDoc(
        path, kind, pkg, after, extract_text(after), before, text_before, tracked, report
    )


def _from_pdf(path: Path) -> tuple[DocxPackage, PdfReport]:
    """The Word file made from the PDF at ``path``, read into memory, and what was left out.

    The Word file is written into a private temporary folder, deleted once the file is read.
    """
    folder = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX))
    try:
        converted = folder / "converted.docx"
        report = pdf_to_docx(path, converted)
        return DocxPackage.open(converted), report
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _prepared(pkg: DocxPackage, resolve: Callable[[DocxPackage], int]) -> DocxPackage:
    """A copy of ``pkg`` with its tracked changes resolved by ``resolve``, then cleaned."""
    copy = pkg.copy()
    resolve(copy)
    clean(copy)
    return copy


# ---- the versions and their plans ---------------------------------------------------------------


@dataclass(frozen=True)
class _View:
    """One version to mask: the source it is of (its index), which side, and its name in the
    combined text, with the prepared package and its text.
    """

    index: int
    side: Side
    name: str
    pkg: DocxPackage
    text: DocText


def _views(sources: list[SourceDoc]) -> list[_View]:
    """Every version to mask, in the order of the combined text: each file after its changes,
    then each file's version before them where it has one.
    """
    views = [
        _View(i, "after", f"{s.path.name} (after)", s.pkg_after, s.text_after)
        for i, s in enumerate(sources)
    ]
    views += [
        _View(i, "before", f"{s.path.name} (before)", s.pkg_before, s.text_before)
        for i, s in enumerate(sources)
        if s.pkg_before is not None and s.text_before is not None
    ]
    return views


def _joined(views: list[_View]) -> CombinedText:
    return CombinedText.join([(view.name, view.text.text) for view in views])


def _check(
    sources: list[SourceDoc], combined: CombinedText, review: ReviewState, options: ExportOptions
) -> None:
    """Raises ValueError for an export that cannot be made as asked (see ``export_case``)."""
    if not sources:
        raise ValueError("There is no file to export.")
    if review.text != combined.text:
        # Its plan's places would be someone else's: it would hide the wrong characters.
        raise ValueError("The review was not made on these files; analyse them again.")
    if not options.redline_split and any(s.pkg_before is not None for s in sources):
        raise ValueError("The files were loaded for a redline review, which this export is not.")
    case = options.existing_case
    if case is not None and not {e.placeholder for e in case.entries} <= review.reserved:
        # A group made in such a review could take the number of a value of the case that the
        # new file does not hold, and the merged key would then restore the case's other files
        # with the wrong value.
        raise ValueError(
            "The review of a file added to a case must reserve the case's placeholders."
        )


def _plans(plan: MaskPlan, combined: CombinedText) -> list[MaskPlan]:
    """The review's plan cut into one plan for each version, counted from the start of its text.

    A replacement never lies across two versions, as no finding takes in the separator between
    them; raises ValueError for one that does.
    """
    starts = [start for _, start, _ in combined.parts]
    parts: list[list[Replacement]] = [[] for _ in combined.parts]
    for r in plan.replacements:
        index = bisect_right(starts, r.start) - 1
        if index < 0 or r.end > combined.parts[index][2]:
            raise ValueError(
                f"The replacement {r.placeholder} at {r.start}-{r.end} lies in no single file."
            )
        start = starts[index]
        parts[index].append(Replacement(r.start - start, r.end - start, r.placeholder))
    return [MaskPlan(replacements) for replacements in parts]


# ---- names --------------------------------------------------------------------------------------


def _file_names(
    code: str, sources: list[SourceDoc], case: Case | None
) -> dict[tuple[int, Side], str]:
    """The neutral name of each version, by the index of its source and its side.

    One file of a new case is ``MASKED-<code>.docx``; several are numbered from 1, and the files
    added to a case after the number its files have reached. A redline's versions add "before"
    and "after".
    """
    first = 1 + (_numbers_used(case) if case is not None else 0)
    numbered = case is not None or len(sources) > 1
    names: dict[tuple[int, Side], str] = {}
    for i, source in enumerate(sources):
        number = str(first + i) if numbered else None
        if source.pkg_before is None:
            names[i, "after"] = neutral_name(code, number)
            continue
        for side in ("before", "after"):
            names[i, side] = neutral_name(code, side if number is None else f"{number}-{side}")
    return names


def _numbers_used(case: Case) -> int:
    """The highest number a masked file of ``case`` has; a file without one (the case's only
    file, or the two versions of its only redline) is its first.
    """
    numbered = re.compile(
        rf"MASKED-{re.escape(case.id)}-(?P<number>[0-9]+)(?:-(?:before|after))?"
        r"(?: \([0-9]+\))?\.docx"
    )
    found = (numbered.fullmatch(file.name) for file in case.masked_files)
    return max((int(match["number"]) if match else 1 for match in found), default=0)


# ---- masking and checking -----------------------------------------------------------------------


def _mask(view: _View, plan: MaskPlan, key: list[KeyEntry], out: Path) -> Path:
    """Masks a copy of the version ``view`` with ``plan`` and the case's ``key``, puts the banner
    on top and saves it at ``out``. The prepared package stays as it was, so the same sources can
    be exported again.
    """
    pkg = view.pkg.copy()
    doc_text = extract_text(pkg)  # the copy has paragraphs of its own
    if doc_text.text != view.text.text:
        raise ValueError("A file has changed since it was read; load it again.")
    apply_mask(pkg, doc_text, plan, entries=key)
    insert_banner(pkg)
    pkg.save(out)
    return out


def _allowances(groups: list[Group]) -> dict[str, int]:
    """For each placeholder, how many of its occurrences the owner left visible on purpose (ruling
    R60): those switched off one by one, and all those of a group switched off whole. The key
    holds such a group's value only when a file is added to a case that has it (ruling R83).
    """
    allowed: dict[str, int] = {}
    for group in groups:
        off = len(group.findings) - len(group.active_findings())
        if off:
            allowed[group.placeholder] = allowed.get(group.placeholder, 0) + off
    return allowed


def _blocking(hits: list[LeakHit], allowed: dict[str, int]) -> set[str]:
    """The placeholders the leak check found in more places, over all the files, than allowed."""
    return {
        placeholder
        for placeholder, count in hits_by_placeholder(hits).items()
        if count > allowed.get(placeholder, 0)
    }


def _named(found: list[list[LeakHit]], files: list[Path]) -> list[LeakHit]:
    """The hits ``found`` in each of ``files``, in their order. With several files each hit's
    part begins with the name of its file (ruling R81); the hits of one file keep their parts.
    """
    if len(files) == 1:
        return list(found[0])
    return [
        replace(hit, part=f"{file.name}: {hit.part}")
        for file, hits in zip(files, found, strict=True)
        for hit in hits
    ]


def _unmarked(
    paths: list[Path], engine: Engine, user_lists: UserLists, entries: list[KeyEntry]
) -> list[Group]:
    """What the detection finds in the masked files that the owner never marked, each value
    once however many of the files hold it.
    """
    seen: set[str] = set()
    found: list[Group] = []
    for path in paths:
        for group in rescan_detection(path, engine, user_lists, entries):
            key = normalize(group.canonical)
            if key not in seen:
                seen.add(key)
                found.append(group)
    return found


# ---- saving -------------------------------------------------------------------------------------


def _save(
    staged: list[Path],
    sources: list[SourceDoc],
    key: list[KeyEntry],
    code: str,
    options: ExportOptions,
    save_case: Callable[[Case], object],
) -> tuple[list[Path], Case]:
    """Writes the checked files into the output folder and saves the case with their
    fingerprints. When anything fails on the way, the files written are deleted again.
    """
    options.out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        files = []
        for path in staged:
            data = path.read_bytes()
            written.append(_write_new(options.out_dir, path.name, data))
            files.append(MaskedFile(written[-1].name, hashlib.sha256(data).hexdigest()))
        case = _case(code, sources, files, key, options)
        save_case(case)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return written, case


def _write_new(folder: Path, name: str, data: bytes) -> Path:
    """Writes ``data`` as a new file ``name`` in ``folder``, or, when there is a file of that name,
    as "<name> (2).docx", "<name> (3).docx" ...: a file that is there is never overwritten.
    """
    stem = name.removesuffix(".docx")
    number = 1
    while True:
        target = folder / (name if number == 1 else f"{stem} ({number}).docx")
        number += 1
        try:
            file = target.open("xb")  # only a file that is not there yet
        except FileExistsError:
            continue
        try:
            with file:
                file.write(data)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target


def _case(
    code: str,
    sources: list[SourceDoc],
    files: list[MaskedFile],
    key: list[KeyEntry],
    options: ExportOptions,
) -> Case:
    """The case to save with ``key``: a new one, or the existing case with the new files added."""
    names = [source.path.name for source in sources]
    existing = options.existing_case
    if existing is None:
        return Case(code, datetime.now(UTC), names, files, key, options.retention_days)
    return Case(
        existing.id,
        existing.created_at,
        [*existing.source_files, *names],
        [*existing.masked_files, *files],
        key,
        options.retention_days,
    )


def _merged(kept: list[KeyEntry], added: list[KeyEntry]) -> list[KeyEntry]:
    """The key of a case a file was added to: its entries, in their order, each with the variants
    the new review adds or replaced by the new review's entry where the value changed; then the
    new review's other entries, in their order.
    """
    new = {entry.placeholder: entry for entry in added}
    merged = []
    for entry in kept:
        update = new.pop(entry.placeholder, None)
        if update is None:
            merged.append(replace(entry, variants=list(entry.variants)))
        elif update.value == entry.value:
            merged.append(replace(entry, variants=sorted({*entry.variants, *update.variants})))
        else:
            merged.append(update)
    return merged + list(new.values())
