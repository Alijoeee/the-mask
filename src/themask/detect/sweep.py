"""The sweep: once a value is found anywhere, every other occurrence of it is hidden too.

``sweep`` searches the text for every variant of every group, the way ``flexible_pattern`` finds a
value (ignoring case, however it is spaced), and adds each occurrence that nothing covers yet to
its group as a finding with source "sweep" and score 1.0. Longer variants go first, across all
groups, so "Acme Supplies" is found whole before "Acme" is looked for. A group the owner switched
off sweeps nothing. A person's bare name ("Smith", "van der Berg") is swept only where it stands
as a name: capitalised, and not after a determiner, so "the Mill" and "the Price" stay as they
are (ruling R50); the leak check must look for such a variant the same way.

An occurrence that holds shorter findings with room to spare takes them over (ruling R35): they
leave their groups and the whole occurrence joins the sweeping group, so "Project Falcon" swept
over the model's "Falcon" gives one replacement and one group. A group whose findings are all
taken over is left with none, for the caller to drop. The owner's decisions are never taken over;
the occurrence is skipped instead: a finding of the always-hide list or of the owner's own
selection, a finding of a ``fixed`` group (the case's key), and a finding or a group the owner
switched off.

Otherwise an occurrence is never taken when it overlaps a finding of any group (the same span, or
only part of it), or a placeholder the text holds already (an exact ``[TYPE_N]``, ruling R44; a
placeholder inside a placeholder would break both), and never when it runs from one line into the
next: a replacement must lie within one paragraph, and the analysis joins the files of a case with
line breaks. A variant that is blank, or shorter than two letters or digits once normalised, is
not searched for at all: it would be found all over the text.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right, insort
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from themask.model import Finding, FindingSource, Group, PlaceholderType
from themask.placeholders import PlaceholderMatch, find_placeholders
from themask.textnorm import HONORIFICS, NAME_PARTICLES, flexible_pattern, normalize

# A variant needs at least this many letters or digits, once normalised, to be searched for.
MIN_VARIANT_LENGTH = 2

# What the owner chose: a finding from these sources is never taken over by the sweep.
OWNER_SOURCES: frozenset[FindingSource] = frozenset({"list", "user"})

# The characters that end a line or a paragraph: no finding may hold one.
LINE_BREAKS = frozenset("\n\r\f\v\x1c\x1d\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}")


# A word one of these stands before is a word, not a person's name: "the Price", "a Mill".
DETERMINERS = frozenset({"the", "such", "this", "that", "any", "each", "no", "a", "an"})

_HONORIFIC_KEYS = frozenset(normalize(honorific) for honorific in HONORIFICS)
_LETTERS = re.compile(r"[^\W\d_]+")


def is_bare_name(kind: PlaceholderType, variant: str) -> bool:
    """Whether ``variant`` of a group of type ``kind`` is a person's bare name: one word ("Smith",
    "Price") or a surname with its particles ("van der Berg"), with no honorific (ruling R50).
    """
    words = variant.split()
    if kind is not PlaceholderType.PERSON or not words or normalize(words[0]) in _HONORIFIC_KEYS:
        return False
    return len(words) == 1 or words[0].casefold() in NAME_PARTICLES


def after_a_determiner(text: str, start: int) -> bool:
    """Whether the word before ``start``, on its line, is one of the ``DETERMINERS``; the
    particles of a surname do not count, so "Berg" of "the van der Berg file" follows "the".
    """
    line_start = text.rfind("\n", 0, start) + 1
    words = _LETTERS.findall(text, max(line_start, start - 60), start)
    while words and words[-1].casefold() in NAME_PARTICLES:
        words.pop()
    return bool(words) and words[-1].casefold() in DETERMINERS


def stands_as_a_name(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]``, a person's bare name, stands there as a name (ruling R50):
    capitalised (its particles aside: "van der Berg"), and not after a determiner ("the Mill").
    """
    words = [word for word in text[start:end].split() if word.casefold() not in NAME_PARTICLES]
    return all(word[:1].isupper() for word in words) and not after_a_determiner(text, start)


def existing_placeholders(text: str) -> list[PlaceholderMatch]:
    """The placeholders a source text holds already: only the exact ``[TYPE_N]`` (ruling R44).

    An altered or bracketless form in an original ("Customer ID-55821", "PERSON-2") is a value
    like any other, to be found and hidden; telling such forms apart is the restore's business.
    """
    return [match for match in find_placeholders(text) if match.exact]


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


def occurrences(
    text: str, variant: str, taken: Spans, *, as_a_name: bool = False
) -> list[tuple[int, int]]:
    """Where ``variant`` stands in ``text`` within one line and outside the ``taken`` stretches,
    in text order; each occurrence found is taken too. With ``as_a_name``, only where it stands
    as a name (``stands_as_a_name``).

    A match that is refused does not hide one that starts inside it: the search goes on from the
    character after the refused match's start.
    """
    pattern = flexible_pattern(variant)
    found = []
    position = 0
    while (match := pattern.search(text, position)) is not None:
        start, end = match.span()
        refused = start == end or crosses_a_line(text, start, end) or taken.overlaps(start, end)
        if refused or (as_a_name and not stands_as_a_name(text, start, end)):
            position = start + 1
            continue
        taken.add(start, end)
        found.append((start, end))
        position = end
    return found


@dataclass(eq=False)
class _Place:
    """A finding where it stands, with its group."""

    finding: Finding
    group: Group


class _Places:
    """The findings of the groups, in order of where they start."""

    def __init__(self, groups: list[Group], fixed: Collection[Group]) -> None:
        self._fixed = {id(group) for group in fixed}
        places = [_Place(f, group) for group in groups for f in group.findings]
        self._places = sorted(places, key=lambda place: place.finding.start)
        self._starts = [place.finding.start for place in self._places]
        self._longest = max((p.finding.end - p.finding.start for p in self._places), default=0)

    def overlapping(self, start: int, end: int) -> list[_Place]:
        """The findings that share a character with ``start``-``end``."""
        found = []
        index = bisect_left(self._starts, end) - 1
        while index >= 0 and self._starts[index] + self._longest > start:
            place = self._places[index]
            if place.finding.end > start:
                found.append(place)
            index -= 1
        return found

    def may_take_over(self, place: _Place, start: int, end: int, sweeper: Group) -> bool:
        """Whether an occurrence at ``start``-``end`` that ``sweeper`` found may take over
        ``place``: the sweeping group is switched on, the occurrence holds the finding with room
        to spare, and the finding is not the owner's decision.
        """
        finding, group = place.finding, place.group
        if not sweeper.enabled:
            return False
        holds = (
            start <= finding.start
            and finding.end <= end
            and finding.end - finding.start < end - start
        )
        return holds and not (
            finding.source in OWNER_SOURCES
            or id(group) in self._fixed
            or not group.enabled
            or _index(group, finding) in group.disabled
        )

    def take_over(self, place: _Place) -> None:
        """Take ``place``'s finding out of its group and out of the places."""
        index = bisect_left(self._starts, place.finding.start)
        while self._places[index] is not place:
            index += 1
        del self._places[index]
        del self._starts[index]
        _remove(place.group, place.finding)

    def add(self, finding: Finding, group: Group) -> None:
        index = bisect_right(self._starts, finding.start)
        self._places.insert(index, _Place(finding, group))
        self._starts.insert(index, finding.start)
        self._longest = max(self._longest, finding.end - finding.start)


def _index(group: Group, finding: Finding) -> int:
    """Where ``finding`` (this very object) stands in ``group.findings``."""
    return next(i for i, found in enumerate(group.findings) if found is finding)


def _remove(group: Group, finding: Finding) -> None:
    """Take ``finding`` out of ``group``, keeping the indexes of its switched-off occurrences."""
    index = _index(group, finding)
    del group.findings[index]
    group.disabled = {i - (i > index) for i in group.disabled if i != index}


def sweep(text: str, groups: list[Group], fixed: Collection[Group] = ()) -> None:
    """Add to ``groups`` every further occurrence in ``text`` of their variants (see the module).

    ``fixed`` are groups whose findings are never taken over: the pipeline passes the groups of
    the case's key. New findings are appended to each group's findings, so the ones already there
    keep their order (a finding taken over leaves its group, and the indexes of the occurrences
    switched off follow). Sweeping again adds nothing.
    """
    places = _Places(groups, fixed)
    placeholders = Spans((p.start, p.end) for p in existing_placeholders(text))
    variants = sorted(
        (
            (variant, index)
            for index, group in enumerate(groups)
            if group.enabled  # a group the owner switched off neither sweeps nor takes over
            for variant in group.variants
            if is_searchable(variant)
        ),
        key=lambda pair: (-len(pair[0]), pair[1], pair[0]),
    )
    for variant, index in variants:
        group = groups[index]
        as_a_name = is_bare_name(group.type, variant)
        pattern = flexible_pattern(variant)
        position = 0
        while (match := pattern.search(text, position)) is not None:
            start, end = match.span()
            inside = places.overlapping(start, end)
            refused = (
                start == end
                or crosses_a_line(text, start, end)
                or placeholders.overlaps(start, end)
                or (as_a_name and not stands_as_a_name(text, start, end))
                or not all(places.may_take_over(place, start, end, group) for place in inside)
            )
            if refused:
                position = start + 1  # a match that starts inside this one may still fit
                continue
            for place in inside:
                places.take_over(place)
            finding = Finding(group.type, start, end, text[start:end], 1.0, "sweep")
            group.findings.append(finding)
            places.add(finding, group)
            position = end
