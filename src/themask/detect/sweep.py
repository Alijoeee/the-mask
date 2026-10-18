"""The sweep: once a value is found anywhere, every other occurrence of it is hidden too.

``sweep`` searches the text for every variant of every group, the way ``flexible_pattern`` finds a
value (ignoring case, however it is spaced), and adds each occurrence that nothing covers yet to
its group as a finding with source "sweep" and score 1.0. Longer variants go first, across all
groups, so "Acme Supplies" is found whole before "Acme" is looked for.

An occurrence is never taken when it overlaps a finding of any group or a placeholder already in
the text (a placeholder inside a placeholder would break both), and never when it runs from one
line into the next: a replacement must lie within one paragraph, and the analysis joins the files
of a case with line breaks. A variant that is blank, or shorter than two letters or digits once
normalised, is not searched for at all: it would be found all over the text.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections.abc import Iterable

from themask.model import Finding, Group
from themask.placeholders import find_placeholders
from themask.textnorm import flexible_pattern, normalize

# A variant needs at least this many letters or digits, once normalised, to be searched for.
MIN_VARIANT_LENGTH = 2

# The characters that end a line or a paragraph: no finding may hold one.
LINE_BREAKS = frozenset("\n\r\f\v\x1c\x1d\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}")


def is_searchable(variant: str) -> bool:
    """Whether ``variant`` is worth searching for: not blank, and not too short."""
    return bool(variant.strip()) and len(normalize(variant)) >= MIN_VARIANT_LENGTH


def crosses_a_line(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]`` holds a line or paragraph break."""
    return not LINE_BREAKS.isdisjoint(text[start:end])


class Spans:
    """Stretches of a text that are taken, kept in order; they may be given overlapping."""

    def __init__(self, spans: Iterable[tuple[int, int]] = ()) -> None:
        self._spans: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if self._spans and start < self._spans[-1][1]:
                last_start, last_end = self._spans[-1]
                self._spans[-1] = (last_start, max(last_end, end))
            else:
                self._spans.append((start, end))

    def overlaps(self, start: int, end: int) -> bool:
        """Whether ``start``-``end`` shares a character with a taken stretch."""
        index = bisect_left(self._spans, (end,))
        return index > 0 and self._spans[index - 1][1] > start

    def add(self, start: int, end: int) -> None:
        """Take ``start``-``end``, which must not overlap a stretch taken already."""
        insort(self._spans, (start, end))


def occurrences(text: str, variant: str, taken: Spans) -> list[tuple[int, int]]:
    """Where ``variant`` stands in ``text`` within one line and outside the ``taken`` stretches,
    in text order; each occurrence found is taken too.

    A match that is refused does not hide one that starts inside it: the search goes on from the
    character after the refused match's start.
    """
    pattern = flexible_pattern(variant)
    found = []
    position = 0
    while (match := pattern.search(text, position)) is not None:
        start, end = match.span()
        if start == end or crosses_a_line(text, start, end) or taken.overlaps(start, end):
            position = start + 1
            continue
        taken.add(start, end)
        found.append((start, end))
        position = end
    return found


def sweep(text: str, groups: list[Group]) -> None:
    """Add to ``groups`` every further occurrence in ``text`` of their variants (see the module).

    New findings are appended to each group's findings, so the ones already there keep their
    places (and the indexes a review keeps of them). Sweeping again adds nothing.
    """
    taken = Spans(
        [(f.start, f.end) for group in groups for f in group.findings]
        + [(p.start, p.end) for p in find_placeholders(text)]
    )
    variants = sorted(
        (
            (variant, index)
            for index, group in enumerate(groups)
            for variant in group.variants
            if is_searchable(variant)
        ),
        key=lambda pair: (-len(pair[0]), pair[1], pair[0]),
    )
    for variant, index in variants:
        group = groups[index]
        for start, end in occurrences(text, variant, taken):
            group.findings.append(Finding(group.type, start, end, text[start:end], 1.0, "sweep"))
