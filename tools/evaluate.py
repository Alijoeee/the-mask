"""How well the detection does on the made-up corpus: the spec's pass marks (section 9).

    uv run python tools/evaluate.py [corpus_dir]

analyses every Word and PDF file the corpus's manifest lists, each on its own (an annex too), the
way the app does before the owner's review: ``load_sources``, ``combined_text``, ``analyze`` and
``ReviewState.from_analysis`` with empty lists of the owner's and one case's lists. It then holds
the review's plan against the file's truth and prints the section 9 table, per format and in all,
with the misses and the groups that hide no secret. Without ``corpus_dir`` the corpus is generated
into a temporary folder first.

A secret of the truth counts as found when every place its text holds it, in its full form and in
each of the other forms the truth lists, lies inside one replacement of the plan, of whatever type:
a company hidden as a person is found, and lowers the type accuracy instead. The places are found
the way the truth was made, exactly as written, a run of spaces matching any run of spaces. A
secret the text does not hold is left out only when the truth says it is in tracked-deleted or
hidden text (the prepared copy has neither), or when its file is a PDF with pages that are
pictures; any other secret the text does not hold is a miss, so that the pass marks never lose
part of their count unseen (ruling R95). A PDF without any text (a scan) is not analysed at all.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from themask.detect.lists import CaseLists, UserLists, never_hide_check
from themask.detect.pipeline import analyze
from themask.errors import ScannedPdfError
from themask.export import combined_text, load_sources
from themask.model import Finding, Group, MaskPlan, PlaceholderType
from themask.review import ReviewState
from themask.textnorm import flexible_pattern, normalize

if TYPE_CHECKING:
    from themask.detect.engine import Engine

# The two classes of the pass marks: pattern-type items (at least 99 % found before review) and
# names, companies and addresses (at least 95 %). The owner's own words (CUSTOM) are neither.
PATTERN_TYPES = frozenset(
    {
        PlaceholderType.EMAIL,
        PlaceholderType.PHONE,
        PlaceholderType.IBAN,
        PlaceholderType.ID,
        PlaceholderType.AMOUNT,
        PlaceholderType.PERCENT,
        PlaceholderType.QUANTITY,
        PlaceholderType.URL,
    }
)
NAME_TYPES = frozenset({PlaceholderType.PERSON, PlaceholderType.COMPANY, PlaceholderType.ADDRESS})

PASS_PATTERN = 0.99
PASS_NAMES = 0.95
PASS_SECONDS = 60.0

THIRTY_PAGES = "thirty_pages"
# The formats of the corpus's files, as the table names them.
FORMATS = {"docx": "Word", "pdf": "PDF"}


@dataclass(frozen=True)
class Secret:
    """One secret of a truth file: its type, its fullest form, its other forms and its flags."""

    type: PlaceholderType
    value: str
    variants: tuple[str, ...] = ()
    only_in_deletion: bool = False
    hidden: bool = False

    @classmethod
    def from_json(cls, item: dict[str, object]) -> Secret:
        """The secret a truth file lists as ``item`` (``tools/corpus/truth.py`` writes them)."""
        variants = item.get("variants", [])
        if not isinstance(variants, list):
            raise TypeError(f"The variants of {item.get('value')!r} are not a list.")
        return cls(
            PlaceholderType(str(item["type"])),
            str(item["value"]),
            tuple(str(v) for v in variants),
            bool(item.get("only_in_deletion", False)),
            bool(item.get("hidden", False)),
        )

    @property
    def forms(self) -> tuple[str, ...]:
        return (self.value, *self.variants)


@dataclass(frozen=True)
class ItemResult:
    """How one secret of a file fared: ``found`` when every place of it is hidden, ``typed_right``
    when every replacement over it has the secret's type; ``places`` counts its places in the
    text, ``placeholders`` the placeholders that hide them.
    """

    file: str
    type: PlaceholderType
    value: str
    found: bool
    typed_right: bool
    places: int
    placeholders: tuple[str, ...]


@dataclass(frozen=True)
class GroupResult:
    """A group the review would hide that is no secret of the truth: its type and canonical form,
    and whether it overlaps a place of a secret (part of a secret, or more than one).
    """

    file: str
    type: PlaceholderType
    canonical: str
    overlaps_secret: bool


@dataclass
class DocumentResult:
    """The evaluation of one file of the corpus.

    ``image_pages`` are the pages of a PDF that are pictures, as the manifest lists them.
    ``items`` are the secrets the evaluation counts; ``not_in_text`` the secrets of its truth it
    leaves out: those only in deleted or hidden text, and in a file with picture pages those its
    text does not hold (any other secret the text does not hold is a miss); ``false_positives``
    the groups
    that hide no secret, and ``stray`` the places that the groups of a secret hide outside every
    place of a secret (placeholder, text, the words around it); ``never_hide`` the never-hide
    terms its plan hides; ``seconds`` the time from reading the file to the end of the analysis.
    ``skipped`` says why a file was not analysed (a scanned PDF), and is None for one that was.
    """

    file: str
    format: str
    features: tuple[str, ...]
    image_pages: tuple[int, ...] = ()
    items: list[ItemResult] = field(default_factory=list)
    not_in_text: list[Secret] = field(default_factory=list)
    false_positives: list[GroupResult] = field(default_factory=list)
    stray: list[tuple[str, str, str]] = field(default_factory=list)
    never_hide: list[str] = field(default_factory=list)
    seconds: float = 0.0
    skipped: str | None = None


def _ratio(found: int, total: int) -> float:
    """``found`` of ``total``; no secret counted is no pass (ruling R95)."""
    return found / total if total else 0.0


@dataclass
class Evaluation:
    """The pass marks over a set of files (see the module), with each file's own result.

    ``recall_pattern`` and ``recall_names`` are the shares of the secrets of each class found
    before review, ``type_accuracy`` the share of the found secrets hidden as their own type
    (informational), ``never_hide_false_positives`` the never-hide terms hidden ("file: text"),
    ``misses`` the secrets not found (file, type, value) and ``seconds_thirty_pages`` the longest
    a thirty-page contract took to read and analyse.
    """

    recall_pattern: float
    recall_names: float
    type_accuracy: float
    never_hide_false_positives: list[str]
    misses: list[tuple[str, str, str]]
    seconds_thirty_pages: float
    documents: list[DocumentResult]

    @classmethod
    def of(cls, documents: list[DocumentResult]) -> Evaluation:
        items = [item for document in documents for item in document.items]
        pattern = [item for item in items if item.type in PATTERN_TYPES]
        names = [item for item in items if item.type in NAME_TYPES]
        found = [item for item in items if item.found]
        long_ones = [d.seconds for d in documents if THIRTY_PAGES in d.features and not d.skipped]
        return cls(
            recall_pattern=_ratio(sum(i.found for i in pattern), len(pattern)),
            recall_names=_ratio(sum(i.found for i in names), len(names)),
            type_accuracy=_ratio(sum(i.typed_right for i in found), len(found)),
            never_hide_false_positives=[
                f"{d.file}: {term}" for d in documents for term in d.never_hide
            ],
            misses=[(i.file, i.type.value, i.value) for i in items if not i.found],
            seconds_thirty_pages=max(long_ones, default=0.0),
            documents=documents,
        )

    def of_format(self, file_format: str) -> Evaluation:
        """The evaluation of this one format's files ("docx" or "pdf")."""
        return Evaluation.of([d for d in self.documents if d.format == file_format])

    def counts(self, types: frozenset[PlaceholderType]) -> tuple[int, int]:
        """Found and total secrets of ``types``."""
        items = [i for d in self.documents for i in d.items if i.type in types]
        return sum(i.found for i in items), len(items)

    @property
    def passed(self) -> bool:
        """Whether the pass marks hold: both recalls, no never-hide term, the time."""
        return (
            self.recall_pattern >= PASS_PATTERN
            and self.recall_names >= PASS_NAMES
            and not self.never_hide_false_positives
            and self.seconds_thirty_pages < PASS_SECONDS
        )


# --- One file ------------------------------------------------------------------------------------


def evaluate(corpus_dir: Path, engine: Engine, user_lists: UserLists) -> Evaluation:
    """The pass marks over every file of the corpus in ``corpus_dir`` (see the module)."""
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    return Evaluation.of([_evaluated(corpus_dir, e, engine, user_lists) for e in manifest])


def _evaluated(
    corpus_dir: Path, entry: dict[str, object], engine: Engine, user_lists: UserLists
) -> DocumentResult:
    file, file_format = str(entry["file"]), str(entry["format"])
    features = entry.get("features", [])
    image_pages = entry.get("image_pages", [])
    if not isinstance(features, list) or not isinstance(image_pages, list):
        raise TypeError(f"The features or image pages of {file} are not a list.")
    truth_file = corpus_dir / str(entry["truth"])
    truth = [Secret.from_json(item) for item in json.loads(truth_file.read_text("utf-8"))]
    document = DocumentResult(
        file, file_format, tuple(str(f) for f in features), tuple(int(p) for p in image_pages)
    )
    started = time.perf_counter()
    try:
        sources = load_sources([corpus_dir / file], False)
    except ScannedPdfError:
        document.skipped = "a scanned PDF, without text"
        return document
    case_lists = CaseLists([], [], set())
    analysis = analyze(combined_text(sources), engine, user_lists, case_lists)
    document.seconds = time.perf_counter() - started
    review = ReviewState.from_analysis(analysis, user_lists, case_lists)
    is_term = never_hide_check(
        user_lists, case_lists, names=[form for secret in truth for form in secret.forms]
    )
    score(document, review.text, review.groups, review.mask_plan(), truth, is_term)
    return document


def places(text: str, form: str) -> list[tuple[int, int]]:
    """Where ``form`` stands in ``text``: written exactly as it is, but for its spaces (any run of
    white space matches any other), and not as part of a longer word or number.
    """
    pattern = re.compile(flexible_pattern(form).pattern)  # the same edges, but case counts
    return [match.span() for match in pattern.finditer(text)]


def _around(text: str, finding: Finding) -> str:
    """The words around ``finding``, on one line, to show where it stands."""
    return " ".join(text[max(0, finding.start - 30) : finding.end + 30].split())


def _outermost(spans: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """``spans`` in text order, without those inside another one ("Acme" in "Acme Supplies Ltd")."""
    return sorted(
        (start, end)
        for start, end in spans
        if not any(s <= start and end <= e and (s, e) != (start, end) for s, e in spans)
    )


def score(
    document: DocumentResult,
    text: str,
    groups: list[Group],
    plan: MaskPlan,
    truth: list[Secret],
    is_term: Callable[[str], bool],
) -> None:
    """Fill ``document`` with how the plan for ``text`` fares against ``truth``.

    ``groups`` are the review's groups and ``plan`` its replacements; ``is_term`` tells a
    never-hide term (the names of the truth beat the document's defined terms).
    """
    kinds = {group.placeholder: group.type for group in groups}
    replacements = plan.replacements
    starts = [r.start for r in replacements]

    def cover(start: int, end: int) -> str | None:
        index = bisect_right(starts, start) - 1
        if index >= 0 and replacements[index].end >= end:
            return replacements[index].placeholder
        return None

    secret_places: list[tuple[int, int]] = []
    for secret in truth:
        spans = _outermost({span for form in secret.forms for span in places(text, form)})
        on_a_picture = not spans and bool(document.image_pages)
        if secret.only_in_deletion or secret.hidden or on_a_picture:
            document.not_in_text.append(secret)
            continue
        secret_places += spans
        covers = [cover(start, end) for start, end in spans]
        hidden_by = tuple(sorted({c for c in covers if c is not None}))
        found = bool(covers) and all(c is not None for c in covers)  # no place: nothing hidden
        document.items.append(
            ItemResult(
                document.file,
                secret.type,
                secret.value,
                found,
                found and all(kinds[c] is secret.type for c in hidden_by),
                len(spans),
                hidden_by,
            )
        )
    truth_keys = {normalize(form) for secret in truth for form in secret.forms}
    for group in groups:
        active = group.active_findings()
        if not active:
            continue
        outside = [
            f for f in active if not any(f.start < e and s < f.end for s, e in secret_places)
        ]
        if normalize(group.canonical) not in truth_keys:
            document.false_positives.append(
                GroupResult(document.file, group.type, group.canonical, len(outside) < len(active))
            )
        else:
            document.stray += [(group.placeholder, f.text, _around(text, f)) for f in outside]
        texts = dict.fromkeys([group.canonical, *(f.text for f in active)])
        document.never_hide += [
            f"{group.type.value} {t!r}"
            for t in texts
            if is_term(t) and normalize(t) not in truth_keys
        ]


# --- The table -------------------------------------------------------------------------------------


def _share(value: float) -> str:
    return f"{value * 100:5.1f} %"


def _percent(value: float, counts: tuple[int, int]) -> str:
    found, total = counts
    return f"{_share(value)} ({found}/{total})" if total else "   n/a"


def report(evaluation: Evaluation, out: Callable[[str], object] = print) -> None:
    """Print the section 9 table of ``evaluation`` per format and in all, then the details."""
    parts = [(name, evaluation.of_format(file_format)) for file_format, name in FORMATS.items()]
    parts.append(("All", evaluation))
    analysed = [d for d in evaluation.documents if not d.skipped]
    skipped = [d for d in evaluation.documents if d.skipped]
    out(f"Pass marks (spec section 9) on {len(analysed)} files analysed")
    for document in skipped:
        out(f"  not analysed: {document.file} ({document.skipped})")
    out("")
    rows: list[tuple[str, list[str], str]] = [
        (
            "Pattern-type items found before review",
            [_percent(e.recall_pattern, e.counts(PATTERN_TYPES)) for _, e in parts],
            f">= {PASS_PATTERN:.0%}",
        ),
        (
            "Names, companies, addresses found before review",
            [_percent(e.recall_names, e.counts(NAME_TYPES)) for _, e in parts],
            f">= {PASS_NAMES:.0%}",
        ),
        (
            "Never-hide terms hidden by mistake",
            [str(len(e.never_hide_false_positives)) for _, e in parts],
            "0",
        ),
        (
            "Thirty-page contract analysed (slowest)",
            [f"{e.seconds_thirty_pages:.1f} s" for _, e in parts],
            f"< {PASS_SECONDS:.0f} s",
        ),
        (
            "Found items hidden as their own type (info)",
            [_share(e.type_accuracy) for _, e in parts],
            "",
        ),
    ]
    widths = [48, 22, 22, 22]
    out(_row(["Check", *(name for name, _ in parts), "Pass mark"], widths))
    for label, cells, mark in rows:
        out(_row([label, *cells, mark], widths))
    out("")
    out("PASS" if evaluation.passed else "FAIL")
    out("")
    _by_type(evaluation, out)
    _by_file(evaluation, out)
    _details(evaluation, out)


def _row(cells: Sequence[str], widths: Sequence[int]) -> str:
    padded = [cell.ljust(width) for cell, width in zip(cells, widths, strict=False)]
    return "  ".join([*padded, *cells[len(widths) :]]).rstrip()


def _by_type(evaluation: Evaluation, out: Callable[[str], object]) -> None:
    out("Per type (all formats): found / total, hidden as its own type")
    for kind in PlaceholderType:
        items = [i for d in evaluation.documents for i in d.items if i.type is kind]
        if items:
            found = sum(i.found for i in items)
            typed = sum(i.typed_right for i in items)
            out(f"  {kind.value:<9} {found:>4} / {len(items):<4} own type {typed:>4}")
    out("")


def _by_file(evaluation: Evaluation, out: Callable[[str], object]) -> None:
    out("Per file: pattern found/total, names found/total, groups hiding no secret, seconds")
    for d in evaluation.documents:
        if d.skipped:
            out(f"  {d.file:<24} not analysed: {d.skipped}")
            continue
        single = Evaluation.of([d])
        pattern = "{}/{}".format(*single.counts(PATTERN_TYPES))
        names = "{}/{}".format(*single.counts(NAME_TYPES))
        out(
            f"  {d.file:<24} pattern {pattern:>7}  names {names:>7}"
            f"  other groups {len(d.false_positives):>3}  {d.seconds:6.1f} s"
        )
    out("")


def _details(evaluation: Evaluation, out: Callable[[str], object]) -> None:
    out(f"Misses ({len(evaluation.misses)}):")
    for file, kind, value in evaluation.misses:
        out(f"  {file:<24} {kind:<9} {value!r}")
    out("")
    terms = evaluation.never_hide_false_positives
    out(f"Never-hide terms hidden ({len(terms)}):")
    for term in terms:
        out(f"  {term}")
    out("")
    others = [g for d in evaluation.documents for g in d.false_positives]
    out(f"Groups hiding no secret ({len(others)}; * = overlaps a secret):")
    for g in others:
        mark = "*" if g.overlaps_secret else " "
        out(f"  {mark} {g.file:<24} {g.type.value:<9} {g.canonical!r}")
    out("")
    stray = [(d.file, *place) for d in evaluation.documents for place in d.stray]
    out(f"Places a secret's group hides outside every secret ({len(stray)}):")
    for file, placeholder, value, around in stray:
        out(f"  {file:<24} {placeholder:<13} {value!r} in '{around}'")
    out("")
    split = [
        i for d in evaluation.documents for i in d.items if i.found and len(i.placeholders) > 1
    ]
    out(f"Secrets found under more than one placeholder ({len(split)}):")
    for i in split:
        out(f"  {i.file:<24} {i.type.value:<9} {i.value!r} {', '.join(i.placeholders)}")
    out("")
    absent = [(d.file, s) for d in evaluation.documents if not d.skipped for s in d.not_in_text]
    out(f"Secrets of the truth not in the text analysed ({len(absent)}):")
    for file, secret in absent:
        why = (
            "only deleted"
            if secret.only_in_deletion
            else "only hidden"
            if secret.hidden
            else "not in the text of a file with picture pages"
        )
        out(f"  {file:<24} {secret.type.value:<9} {secret.value!r} ({why})")


# --- Running it ------------------------------------------------------------------------------------


def _generated(folder: Path) -> Path:
    """The corpus, generated into ``folder``."""
    # Run as a script, Python puts this file's folder on the path, not the repository's.
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tools.make_corpus import generate

    generate(folder)
    return folder


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python tools/evaluate.py",
        description="Measure the detection on the made-up corpus against the spec's pass marks.",
    )
    parser.add_argument(
        "corpus_dir",
        nargs="?",
        type=Path,
        help="a folder written by tools.make_corpus (default: the corpus, generated afresh)",
    )
    args = parser.parse_args(argv)
    from themask.detect.engine import Engine

    with tempfile.TemporaryDirectory(prefix="themask-corpus-") as temporary:
        corpus_dir = args.corpus_dir or _generated(Path(temporary))
        evaluation = evaluate(corpus_dir, Engine(), UserLists([], []))
        report(evaluation)
    return 0 if evaluation.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
