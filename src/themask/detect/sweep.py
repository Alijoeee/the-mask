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
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass

from themask.detect.contract_rules import is_job_title
from themask.detect.lists import is_default_term, is_month
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


# Spaces within a line: a space, a tab, a non-breaking space, but no line or paragraph break.
_SPACE = r"[^\S\n\r\f\v\x1c-\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]"
# The spaces between two words of one phrase: as _SPACE, but no tab either, which parts the
# fields of a form ("Name:\tSmith\tTitle:\tDirector").
_INLINE = r"[^\S\t\n\r\f\v\x1c-\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]"
_WORD = r"[^\W_][\w'\N{RIGHT SINGLE QUOTATION MARK}\-]*"
_WORD_BEFORE = re.compile(f"({_WORD}){_INLINE}+\\Z")
_WORD_AFTER = re.compile(f"{_INLINE}+({_WORD})(:?)")  # a colon after it makes the word a label
_AMPERSAND_BEFORE = re.compile(f"&{_INLINE}+\\Z")
_AMPERSAND_AFTER = re.compile(f"{_INLINE}+&")
_TOKEN = re.compile(_WORD)
_ONLY_SPACES = re.compile(f"{_SPACE}+\\Z")
# A word that opens a letter or a notice before a name parts it from the name: "Dear Price".
_SALUTATIONS = frozenset({"dear", "attn", "attention", "to", "from", "cc"})
# The small words that join the words of a title-case phrase: "Grant of Rights", "Smith & Co".
_CONNECTIVES = frozenset({"of", "and", "for", "to", "in", "on", "the"})
# How many words after a name are read for the job title that follows it ("Head of Sales").
_TITLE_WORDS = 4
_INITIAL = re.compile(r"[^\W\d_]\.?")
_NUMBER = re.compile(r"\d{1,4}(?:st|nd|rd|th)?", re.IGNORECASE)
# The longest term, in words, that a bare name may be part of ("Contracts Rights Third Parties").
_LONGEST_TERM = 6


def _line(text: str, start: int, end: int) -> tuple[int, int]:
    """The start and the end of the line that holds ``start``-``end``."""
    line_end = text.find("\n", end)
    return text.rfind("\n", 0, start) + 1, len(text) if line_end < 0 else line_end


def _belongs_to_the_name(word: str) -> bool:
    """Whether ``word``, beside a surname, is part of the name: an honorific ("Mr Price"), an
    initial ("J Price") or a particle ("van Berg").
    """
    return (
        normalize(word) in _HONORIFIC_KEYS
        or _INITIAL.fullmatch(word) is not None
        or word.casefold() in NAME_PARTICLES
    )


def _no_names(word: str) -> bool:
    return False


def _another_word(word: str, is_name: Callable[[str], bool]) -> bool:
    """Whether ``word``, near a surname, is a capitalised word of a phrase: not part of the name
    (an honorific, an initial, a particle) and not a name found (``is_name``).
    """
    return word[:1].isupper() and not _belongs_to_the_name(word) and not is_name(word)


def _phrase_before(text: str, line_start: int, start: int, is_name: Callable[[str], bool]) -> bool:
    """Whether the words right before ``start`` make a phrase of it: a capitalised word joined by
    nothing but spaces ("Business Day"), or one across a connective ("Rights of Grant"). A
    salutation parts them ("Dear Price"), and so does a name found beyond a connective.
    """
    found = _WORD_BEFORE.search(text, line_start, start)
    if found is None:
        ampersand = _AMPERSAND_BEFORE.search(text, line_start, start)
        if ampersand is None:
            return False
        beyond = _WORD_BEFORE.search(text, line_start, ampersand.start())
        return beyond is not None and _another_word(beyond[1], is_name)
    word = found[1]
    if word.casefold() in _SALUTATIONS or _belongs_to_the_name(word):
        return False
    if word.casefold() in _CONNECTIVES:
        beyond = _WORD_BEFORE.search(text, line_start, found.start())
        return beyond is not None and _another_word(beyond[1], is_name)
    return word[:1].isupper()


def _a_job_title_at(text: str, position: int, line_end: int) -> bool:
    """Whether a job title starts at ``position``: "Director", "Finance Director", "Head of
    Sales" (``contract_rules.is_job_title``).
    """
    words: list[str] = []
    while len(words) < _TITLE_WORDS:
        found = _TOKEN.match(text, position, line_end)
        if found is None:
            break
        words.append(found.group())
        spaces = _ONLY_SPACES.match(text, found.end(), found.end() + 1)
        if spaces is None or text[found.end() : found.end() + 1] == "\t":
            break
        position = found.end() + 1
    if not words or not words[0][:1].isupper():
        return False  # "of Attorney" is no title, however is_job_title reads "of"
    return any(is_job_title(" ".join(words[:count])) for count in range(len(words), 0, -1))


def _phrase_after(text: str, end: int, line_end: int, is_name: Callable[[str], bool]) -> bool:
    """Whether the words right after ``end`` make a phrase of it: a capitalised word joined by
    nothing but spaces ("Long Stop"), or one across a connective ("Grant of Rights", "Power of
    Attorney"). A job title parts them ("Smith Finance Director"), as does a label's colon
    ("Smith Title: Director") and a name found beyond a connective ("Price and Smith").
    """
    found = _WORD_AFTER.match(text, end, line_end)
    if found is None:
        ampersand = _AMPERSAND_AFTER.match(text, end, line_end)
        if ampersand is None:
            return False
        beyond = _WORD_AFTER.match(text, ampersand.end(), line_end)
        return beyond is not None and _another_word(beyond[1], is_name)
    word = found[1]
    if found[2] or _a_job_title_at(text, found.start(1), line_end):
        return False
    if word.casefold() in _CONNECTIVES:
        beyond = _WORD_AFTER.match(text, found.end(1), line_end)
        return beyond is not None and _another_word(beyond[1], is_name)
    return word[:1].isupper() and not _belongs_to_the_name(word)


def _in_a_phrase(text: str, start: int, end: int, is_name: Callable[[str], bool]) -> bool:
    """Whether ``start``-``end`` stands in a title-case phrase on its line, as the words right
    before or after it show: "Business Day", "Companies House", "Grant of Rights" (ruling R56).
    """
    line_start, line_end = _line(text, start, end)
    return _phrase_before(text, line_start, start, is_name) or _phrase_after(
        text, end, line_end, is_name
    )


def _on_a_line_of_capitals(text: str, start: int, end: int) -> bool:
    """Whether ``start``-``end`` stands on a line whose letters are all capitals: a heading such
    as "2. GRANT OF LICENCE". A line that holds nothing but the name ("SMITH" under a signature
    line) is a name, not a heading.
    """
    line_start, line_end = _line(text, start, end)
    if not any(c.isalpha() for c in text[line_start:start] + text[end:line_end]):
        return False
    letters = [c for c in text[line_start:line_end] if c.isalpha()]
    return len(letters) > 1 and all(letter.isupper() for letter in letters)


def _month_by_a_number(text: str, start: int, end: int) -> bool:
    """Whether ``start``-``end`` is a month with a number as the word right before or after it on
    its line: "1 May 2026", "May 2026", "May 1, 2026".
    """
    if not is_month(text[start:end]):
        return False
    line_start, line_end = _line(text, start, end)
    before = text[line_start:start].split()
    after = text[end:line_end].split()
    # The end of a sentence parts them ("... 1 June 2026. May shall attend"); a comma does not.
    words = [before[-1].rstrip(",")] if before and before[-1][-1:] not in ".;:!?" else []
    words += [after[0].rstrip(".,;:)")] if after else []
    return any(_NUMBER.fullmatch(word) for word in words)


def _part_of_a_term(text: str, start: int, end: int, is_term: Callable[[str], bool]) -> bool:
    """Whether ``start``-``end`` is part of a longer term, in words that stand on its line with
    nothing but spaces between them, longest first: "Business Day", "Terms of Use", "Long Stop
    Date", "High Court of Justice" (``is_term``).
    """
    line_start, line_end = _line(text, start, end)
    run: list[tuple[int, int]] = []
    runs = [run]
    for token in _TOKEN.finditer(text, line_start, line_end):
        if run and _ONLY_SPACES.match(text, run[-1][1], token.start()) is None:
            run = []
            runs.append(run)
        run.append(token.span())
    for words in runs:
        inside = [i for i, (first, last) in enumerate(words) if first < end and last > start]
        if not inside:
            continue
        low, high = inside[0], inside[-1]
        for size in range(min(_LONGEST_TERM, len(words)), high - low + 1, -1):
            for first in range(max(0, high - size + 1), min(low, len(words) - size) + 1):
                if is_term(text[words[first][0] : words[first + size - 1][1]]):
                    return True
    return False


def stands_as_a_name(
    text: str,
    start: int,
    end: int,
    is_term: Callable[[str], bool] = is_default_term,
    *,
    is_name: Callable[[str], bool] = _no_names,
    found_by_engine: bool = False,
) -> bool:
    """Whether ``text[start:end]``, an occurrence of a person's bare name (see ``is_bare_name``),
    stands there as that person's name and not as a word of the contract (rulings R50, R52,
    R54, R56).

    With ``found_by_engine`` the engine itself reported a name there, and only a determiner
    before it makes it a word ("the Smith file"). An occurrence a sweep finds stands as a name
    when all of these hold:

    * every word of it but the surname's particles is capitalised ("Price", "van der Berg");
    * the word before it on its line, particles aside, is none of the ``DETERMINERS`` ("the
      Price", "a Mill", "the van der Berg file" are words of the contract);
    * it is in no title-case phrase on its line: no capitalised word stands right beside it
      with nothing but spaces between ("Business Day", "Companies House", "Long Stop"), nor one
      across a connective ("Grant of Rights", "Power of Attorney"). An honorific, an initial
      or a particle beside it is part of the name ("Mr Price"); a comma, a tab, a salutation
      before it ("Dear Price") and a job title or a label after it ("Smith Finance Director",
      "Smith Title:") part it from its neighbours; a name found (``is_name``) beyond a
      connective is no phrase ("Price and Smith");
    * its line is not a heading in capitals ("2. GRANT OF LICENCE"); a line that holds nothing
      but the name is a name ("SMITH" under a signature line);
    * a month has no number right beside it ("dated 1 May 2026");
    * it is not part of a longer term (``is_term``, the default never-hide words unless the
      caller passes its own lists and the document's defined terms): "Terms of Use".

    ``text`` is any text the occurrence was found in, a whole document's or one paragraph's
    raw text, and ``start``-``end`` the occurrence's span in it. The sweep takes a bare name
    only where this holds, and the leak check looks for one the same way, so the occurrences a
    sweep left visible on purpose do not count as leaks.
    """
    if found_by_engine:
        return not after_a_determiner(text, start)
    words = [word for word in text[start:end].split() if word.casefold() not in NAME_PARTICLES]
    if not all(word[:1].isupper() for word in words):
        return False
    return not (
        after_a_determiner(text, start)
        or _in_a_phrase(text, start, end, is_name)
        or _on_a_line_of_capitals(text, start, end)
        or _month_by_a_number(text, start, end)
        or _part_of_a_term(text, start, end, is_term)
    )


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
    text: str,
    variant: str,
    taken: Spans,
    *,
    as_a_name: bool = False,
    is_term: Callable[[str], bool] = is_default_term,
    is_name: Callable[[str], bool] = _no_names,
) -> list[tuple[int, int]]:
    """Where ``variant`` stands in ``text`` within one line and outside the ``taken`` stretches,
    in text order; each occurrence found is taken too. With ``as_a_name``, only where it stands
    as a name (``stands_as_a_name`` with ``is_term``).

    A match that is refused does not hide one that starts inside it: the search goes on from the
    character after the refused match's start.
    """
    pattern = flexible_pattern(variant)
    found = []
    position = 0
    while (match := pattern.search(text, position)) is not None:
        start, end = match.span()
        refused = start == end or crosses_a_line(text, start, end) or taken.overlaps(start, end)
        named = as_a_name and not stands_as_a_name(text, start, end, is_term, is_name=is_name)
        if refused or named:
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


def name_test(groups: Iterable[Group]) -> Callable[[str], bool]:
    """Whether a word is one of the names of ``groups``' people and companies (any variant or
    form seen): the names a connective does not make a phrase of ("Price and Smith").
    """
    names = {
        normalize(form)
        for group in groups
        if group.type in (PlaceholderType.PERSON, PlaceholderType.COMPANY)
        for form in [*group.variants, *(f.text for f in group.findings)]
    }
    return lambda word: normalize(word) in names


def _within(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    """Whether ``start``-``end`` lies wholly inside one of the ordered, separate ``spans``."""
    index = bisect_right(spans, (start, 1 << 62)) - 1
    return index >= 0 and spans[index][0] <= start and end <= spans[index][1]


def sweep(
    text: str,
    groups: list[Group],
    fixed: Collection[Group] = (),
    is_term: Callable[[str], bool] = is_default_term,
    public: Collection[tuple[int, int]] = (),
) -> None:
    """Add to ``groups`` every further occurrence in ``text`` of their variants (see the module).

    ``fixed`` are groups whose findings are never taken over: the pipeline passes the groups of
    the case's key. ``is_term`` tells the terms a person's bare name may be part of
    (``stands_as_a_name``): the pipeline passes the owner's lists and the defined terms. New findings are appended to each group's findings, so the ones already there
    keep their order (a finding taken over leaves its group, and the indexes of the occurrences
    switched off follow). Sweeping again adds nothing.

    ``public`` are stretches of public text (references to laws, task D7): an occurrence that lies
    wholly inside one is left alone, so the 6698 of an agreement is not swept out of "Law No.
    6698". The owner's own values (always-hide entries, selections, the case's key) are swept
    there too.
    """
    places = _Places(groups, fixed)
    placeholders = Spans((p.start, p.end) for p in existing_placeholders(text))
    is_name = name_test(groups)
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
    public_spans = sorted(public)
    fixed_ids = {id(g) for g in fixed}
    for variant, index in variants:
        group = groups[index]
        owners = id(group) in fixed_ids or any(f.source in ("list", "user") for f in group.findings)
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
                or (not owners and _within(public_spans, start, end))
                or (as_a_name and not stands_as_a_name(text, start, end, is_term, is_name=is_name))
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
