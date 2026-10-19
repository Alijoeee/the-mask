"""The analysis pipeline: from a case's text to the numbered groups the owner reviews.

``CombinedText`` joins the texts of a case's files into one text, with a form feed on a line of
its own between them, and remembers where each file's text lies, so that a finding can be traced
back to its file. ``analyze`` runs the whole analysis on it:

1. The engine reads each file's text on its own (its language model takes at most a million
   characters at a time), and the contract rules collect each file's defined terms into the
   case's lists. The owner's always-hide entries are found wherever they stand.
2. A finding's edges that belong to the sentence (spaces, quotes, an ellipsis, a lone bracket) are
   trimmed, and a finding that runs over a line break is cut there: a replacement must lie within
   one paragraph. Nothing is found inside a placeholder the text holds already.
3. A finding that is a never-hide term is dropped; a finding longer than the term is not. The
   names in the text beat its defined terms: in a text that defines ``"Acme" means Acme
   Supplies Ltd``, every "Acme" is still hidden. The owner's never-hide lists and the defaults
   always win, over the always-hide lists too. What the language model finds that is made of
   the contract's own words only ("GOVERNING LAW") is dropped as well. No never-hide term, and
   no single word of the contract's own ("Quality" of Quality Foods Ltd), becomes a variant for
   the sweep.
4. Overlapping findings leave one: the longest wins (counted in letters and digits, so a trailing
   full stop or quote adds nothing). Of equal length, the owner's own values (the always-hide
   lists and the case's key) come first, then the type in this order: IBAN, EMAIL, URL, PHONE,
   ID, AMOUNT, PERCENT, QUANTITY, PERSON, COMPANY, ADDRESS, CUSTOM; then the higher score.
5. The findings are grouped (``grouping``) and every other occurrence of each group's variants
   is swept in (``sweep``). An occurrence that holds a shorter finding takes it over ("Project
   Falcon" over the model's "Falcon"), unless that finding is the owner's (an always-hide match,
   the case's key); a group left with no findings is dropped. A person's bare surname ("Smith"
   of Katie Smith, "van der Berg") is one of the person's variants, swept only where it stands
   as a name: capitalised and not after a determiner (ruling R50). A surname that is also an
   ordinary word of the contract ("Price", "Mill" defined as a term, a COMMON_WORDS word) marks
   the group for checking where it is swept, and a default never-hide word is swept only when
   one person found alone ends with it; the owner's never-hide list always wins.
6. The groups are numbered per type in order of first appearance, counting what the sweep
   found, after any placeholder the text holds already and after the case's key.

When a file is added to a case (``seed_entries``, the case's key), each entry is a group that
keeps its placeholder, and its variants are found before the overlaps are settled; an entry that
does not occur in the new text is left out of the result (the case's key keeps it).
"""

from __future__ import annotations

import re
import uuid
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from themask.detect.contract_rules import find_defined_terms, is_contract_wording
from themask.detect.grouping import PersonName, SurnamePolicy, group_findings
from themask.detect.lists import (
    CaseLists,
    UserLists,
    always_hide_entry,
    is_default_term,
    never_hide_check,
    on_never_hide_list,
    term_key,
)
from themask.detect.sweep import (
    LINE_BREAKS,
    Spans,
    existing_placeholders,
    is_bare_name,
    is_searchable,
    occurrences,
    stands_as_a_name,
    sweep,
)
from themask.model import Analysis, Finding, Group, KeyEntry, PlaceholderType
from themask.placeholders import PLACEHOLDER_RE, PlaceholderMatch, format_placeholder
from themask.textnorm import COMMON_WORDS, has_legal_form, normalize, strip_legal_form, variants_of

if TYPE_CHECKING:
    from themask.detect.engine import Engine

SEPARATOR = "\n\f\n"

# Of two overlapping findings of equal length, the type that comes first here wins.
PRECEDENCE: tuple[PlaceholderType, ...] = (
    PlaceholderType.IBAN,
    PlaceholderType.EMAIL,
    PlaceholderType.URL,
    PlaceholderType.PHONE,
    PlaceholderType.ID,
    PlaceholderType.AMOUNT,
    PlaceholderType.PERCENT,
    PlaceholderType.QUANTITY,
    PlaceholderType.PERSON,
    PlaceholderType.COMPANY,
    PlaceholderType.ADDRESS,
    PlaceholderType.CUSTOM,
)
_RANK = {kind: rank for rank, kind in enumerate(PRECEDENCE)}

EXISTING_PLACEHOLDERS_WARNING = (
    "The document already contains placeholders such as {placeholder}; numbering continues after"
    " them."
)

_NAMES = frozenset({PlaceholderType.PERSON, PlaceholderType.COMPANY})
# The owner's own values among the findings before grouping: always-hide matches, and the case's
# key (matched as "sweep" findings).
_OWNERS = frozenset({"list", "sweep"})
# On one span, a score at least this much higher wins over the type order (ruling R46).
SCORE_MARGIN = 0.1
# A contract rule's name with its legal form, at least this sure, keeps its end (ruling R45).
RULE_NAME_SCORE = 0.9
_COMMON_WORDS = frozenset(word.casefold() for word in COMMON_WORDS)

# What may stand at the edge of a finding without being part of the value: spaces, quotes, an
# ellipsis, list and sentence marks. A full stop stays ("B.V.", "Inc."), and so does a bracket
# that closes one opened inside the finding ("Acme (UK)").
_EDGE_MARKS = frozenset(
    "\"'\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
    "\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
    "\N{LEFT-POINTING DOUBLE ANGLE QUOTATION MARK}\N{RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK}"
    "\N{DOUBLE LOW-9 QUOTATION MARK}\N{HORIZONTAL ELLIPSIS},;:!?*_|"
    "\N{BULLET}\N{MIDDLE DOT}-\N{EN DASH}\N{EM DASH}"
)
_BRACKETS = {"(": ")", "[": "]", "{": "}", "<": ">"}
_CLOSING = {closing: opening for opening, closing in _BRACKETS.items()}
# The word after a finding, on its line.
_NEXT_WORD = re.compile(r"[ \t]+([^\W\d_][\w\-']*)")


@dataclass
class CombinedText:
    """The texts of a case's files as one text; ``parts`` holds each file's name and the start
    and end of its text in ``text``.
    """

    text: str
    parts: list[tuple[str, int, int]]

    @classmethod
    def join(cls, named_texts: list[tuple[str, str]], separator: str = SEPARATOR) -> CombinedText:
        """``named_texts`` (name, text) joined with ``separator`` between them."""
        parts = []
        offset = 0
        for name, text in named_texts:
            parts.append((name, offset, offset + len(text)))
            offset += len(text) + len(separator)
        return cls(separator.join(text for _, text in named_texts), parts)

    def locate(self, offset: int) -> tuple[str, int]:
        """The file that holds ``offset`` and the offset in that file's text.

        The end of a file's text counts as that file's (a finding may end there). Raises
        ValueError for an offset between two files or outside the text.
        """
        index = bisect_right([start for _, start, _ in self.parts], offset) - 1
        if index >= 0:
            name, start, end = self.parts[index]
            if offset <= end:
                return name, offset - start
        raise ValueError(f"Offset {offset} is not in the text of any file.")


def analyze(
    combined: CombinedText,
    engine: Engine,
    user_lists: UserLists,
    case_lists: CaseLists | None = None,
    seed_entries: list[KeyEntry] | None = None,
) -> Analysis:
    """The groups to hide in ``combined``, numbered, with warnings for the owner (see the module).

    The terms each file defines are added to ``case_lists.defined_terms``.
    """
    text = combined.text
    case = case_lists if case_lists is not None else CaseLists([], [], set())
    placeholders = existing_placeholders(text)  # the exact [TYPE_N] only (ruling R44)
    in_placeholder = Spans((p.start, p.end) for p in placeholders)

    found = _detected(combined, engine, case) + _listed(text, user_lists, case)
    found = [f for f in found if not in_placeholder.overlaps(f.start, f.end)]
    found = _people_among_parties(found, text)
    seeds = [_seed(entry) for entry in seed_entries or []]

    is_term = never_hide_check(user_lists, case)  # what a person's bare name may be part of
    names = _names(found, seeds, is_term)
    never_hidden = never_hide_check(user_lists, case, names=names)

    def keep(form: str) -> bool:
        # A single word of the contract's own ("Quality" of Quality Foods Ltd) would be swept
        # out of every clause that uses it.
        common = len(form.split()) == 1 and is_contract_wording(form)
        return is_searchable(form) and not never_hidden(form) and not common

    surnames = _surnames_kept(found, text, user_lists, case, is_term)
    defined = {term_key(term) for term in case.defined_terms}
    found = [
        f
        for f in found
        if (f.start, f.end) in surnames
        or not (never_hidden(f.text) or _names_nobody(f) or _starts_a_term(text, f))
    ]
    for seed in seeds:
        seed.variants = {v for v in seed.variants if keep(v)}
    _keep_shared_variants_out(seeds)
    found += _seed_matches(text, seeds, placeholders, is_term, names)

    policy = SurnamePolicy(
        allowed=lambda form: not on_never_hide_list(form, user_lists, case),
        only_one=is_default_term,
        is_term=is_term,
    )
    groups = group_findings(
        _one_per_place(found),
        text,
        seeds=seeds,
        keep=keep,
        aliases=case.defined_terms,
        surnames=policy,
    )
    for group in groups:
        # No never-hide word is swept, but a person's bare name, which the sweep takes only
        # where it stands as a name (rulings R42, R50).
        group.variants = {
            v for v in group.variants if is_bare_name(group.type, v) or not never_hidden(v)
        }
    sweep(text, groups, fixed=seeds, is_term=is_term)
    groups = [g for g in groups if g.findings]  # a seed not in this text, a group taken over
    for group in groups:
        group.findings.sort(key=lambda f: (f.start, f.end))
        if any((f.start, f.end) in surnames for f in group.findings) or any(
            is_bare_name(group.type, f.text) and _ordinary(f.text, defined) for f in group.findings
        ):
            group.needs_check = True
    groups.sort(key=lambda g: g.findings[0].start)
    _number(groups, seed_entries or [], placeholders)
    return Analysis(text, groups, _warnings(placeholders))


# --- Finding ---------------------------------------------------------------------------------


def _detected(combined: CombinedText, engine: Engine, case: CaseLists) -> list[Finding]:
    """What the engine finds in each file's text, placed in the combined text, trimmed and cut
    at line breaks; each file's defined terms go into ``case``.
    """
    found: list[Finding] = []
    for _, start, end in combined.parts:
        part = combined.text[start:end]
        if not part.strip():
            continue
        case.defined_terms |= find_defined_terms(part)
        for finding in engine.analyze(part):
            moved = replace(finding, start=finding.start + start, end=finding.end + start)
            found += _cleaned(combined.text, moved)
    return found


def _listed(text: str, user: UserLists, case: CaseLists) -> list[Finding]:
    """Every occurrence of the owner's and the case's always-hide entries."""
    found = []
    for entry in [*user.always_hide, *case.always_hide]:
        kind, value = always_hide_entry(entry)
        if is_searchable(value):
            for start, end in occurrences(text, value, Spans()):
                found.append(Finding(kind, start, end, text[start:end], 1.0, "list"))
    return found


def _cleaned(text: str, finding: Finding) -> list[Finding]:
    """``finding`` without the marks at its edges, cut into one piece per line; a piece with no
    letter or digit is dropped.
    """
    pieces = []
    start = finding.start
    for position in range(finding.start, finding.end + 1):
        if position == finding.end or text[position] in LINE_BREAKS:
            piece_start, piece_end = _trimmed(text, start, position)
            if any(character.isalnum() for character in text[piece_start:piece_end]):
                piece = text[piece_start:piece_end]
                pieces.append(replace(finding, start=piece_start, end=piece_end, text=piece))
            start = position + 1
    return pieces


def _trimmed(text: str, start: int, end: int) -> tuple[int, int]:
    """``start``-``end`` without spaces and edge marks at either end, and without a bracket at an
    end that is not matched inside the span.
    """
    while start < end:
        if _loose(text, start, end, text[start], _BRACKETS):
            start += 1
        elif _loose(text, start, end, text[end - 1], _CLOSING):
            end -= 1
        else:
            break
    return start, end


def _loose(text: str, start: int, end: int, mark: str, partners: dict[str, str]) -> bool:
    """Whether ``mark``, at one end of ``start``-``end``, is not part of the value: a space, an
    edge mark, or a bracket whose partner (``partners``) the span does not hold as often.
    """
    if mark.isspace() or mark in _EDGE_MARKS:
        return True
    partner = partners.get(mark)
    return partner is not None and text.count(partner, start, end) < text.count(mark, start, end)


# --- Never-hide terms and the names that beat them ----------------------------------------------


def _starts_a_term(text: str, finding: Finding) -> bool:
    """Whether a person or company of one word that the engine found is the first word of a
    default never-hide term with the word after it: "Disclosing" in "(1) The Disclosing Party",
    which the parties clause reads as a party's name.
    """
    if finding.type not in _NAMES or finding.source == "list" or len(finding.text.split()) != 1:
        return False
    following = _NEXT_WORD.match(text, finding.end)
    return following is not None and is_default_term(f"{finding.text} {following[1]}")


def _names_nobody(finding: Finding) -> bool:
    """Whether the language model found a text made of the contract's own words only, which
    names nobody: "GOVERNING LAW", "the Recipient for the Purpose" (``is_contract_wording``).
    """
    return finding.source == "model" and is_contract_wording(finding.text)


def _names(found: list[Finding], seeds: list[Group], is_term: Callable[[str], bool]) -> list[str]:
    """The names that beat a defined term: every form of the people and companies found (the
    texts, their variants, without their legal form), of the always-hide matches and of the
    case's key. A person or company found that is itself a never-hide term (``is_term``), or
    names nobody, gives none.
    """
    names: list[str] = []
    for finding in found:
        if finding.source == "list":
            names.append(finding.text)
        elif finding.type in _NAMES and not (is_term(finding.text) or _names_nobody(finding)):
            names += [finding.text, strip_legal_form(finding.text)]
            names += variants_of(finding.text, finding.type)
            if finding.type is PlaceholderType.PERSON:
                names += PersonName.of(finding.text).short_forms()
    for seed in seeds:
        if seed.type in _NAMES:
            names += [seed.canonical, *seed.variants]
        if seed.type is PlaceholderType.PERSON:
            names += PersonName.of(seed.canonical).short_forms()
    return names


# Words that make a name a company's: COMMON_WORDS, and these ("Kestrel Foods", "Oak Ventures").
_COMPANY_WORDS = frozenset(word.casefold() for word in COMMON_WORDS) | frozenset(
    {"foods", "food", "ventures", "associates", "partnership", "bank", "insurance", "media"}
    | {"properties", "engineering", "construction", "energy", "pharma", "healthcare", "retail"}
)
_OPEN_QUOTES = "\"'\N{LEFT DOUBLE QUOTATION MARK}\N{LEFT SINGLE QUOTATION MARK}"
_CLOSE_QUOTES = "\"'\N{RIGHT DOUBLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"


def _people_among_parties(found: list[Finding], text: str) -> list[Finding]:
    """``found`` with the parties a contract rule took for companies that are people (ruling
    R55): two or three capitalised words, no legal form and no company word, whose short name,
    defined in the bracket straight after them, is their last word. People are shortened to their
    surname and companies to their first word: 'John Smith ("Smith")' is a person.
    """
    people = []
    for finding in found:
        words = finding.text.split()
        if (
            finding.type is PlaceholderType.COMPANY
            and finding.source == "rule"
            and len(words) in (2, 3)
            and all(word[:1].isupper() for word in words)
            and not has_legal_form(finding.text)
            and not any(word.casefold().strip(".,") in _COMPANY_WORDS for word in words)
            and _defined_as(text, finding.end, words[-1])
        ):
            finding = replace(finding, type=PlaceholderType.PERSON)
        people.append(finding)
    return people


def _defined_as(text: str, end: int, word: str) -> bool:
    """Whether a bracket straight after ``end`` defines ``word`` as a short name: ' ("Smith")',
    ' (the "Smith")'.
    """
    bracket = re.compile(
        rf"\s*\(\s*[^()\n]{{0,40}}?[{_OPEN_QUOTES}]\s*{re.escape(word)}\s*[{_CLOSE_QUOTES}]",
        re.IGNORECASE,
    )
    return bracket.match(text, end) is not None


def _ordinary(word: str, defined: set[str]) -> bool:
    """Whether a person's bare name is also an ordinary word of the contract: a default
    never-hide word, one of COMMON_WORDS, a term the document defines (``defined``, as term
    keys), or a single word of the contract's own. Swept as a name, it marks its group for
    checking (ruling R50).
    """
    single_contract_word = len(word.split()) == 1 and is_contract_wording(word)
    return (
        is_default_term(word)
        or word.casefold() in _COMMON_WORDS
        or term_key(word) in defined
        or single_contract_word
    )


def _surnames_kept(
    found: list[Finding],
    text: str,
    user: UserLists,
    case: CaseLists,
    is_term: Callable[[str], bool],
) -> set[tuple[int, int]]:
    """The spans of the people found as one capitalised word, after an honorific or not, that is
    a default never-hide term ("Price", "Ms Banks"), where that word is a surname all the same
    (ruling R42): exactly one full name found ends with it, and it stands as a name
    (``stands_as_a_name`` for what the engine saw: no determiner before it, ruling R56). The
    owner's own
    never-hide lists always win. These stay hidden, and their groups are marked for checking.
    """
    full_names: dict[str, set[str]] = defaultdict(set)
    for finding in found:
        person = PersonName.of(finding.text)
        if finding.type is PlaceholderType.PERSON and person.is_full:
            full_names[person.last].add(person.key)
    spans = set()
    for finding in found:
        person = PersonName.of(finding.text)
        if finding.type is not PlaceholderType.PERSON or len(person.words) != 1:
            continue
        word = person.words[0]
        if (
            word[:1].isupper()
            and is_default_term(word)
            and not on_never_hide_list(word, user, case)
            and not on_never_hide_list(finding.text, user, case)
            and len(full_names.get(person.last, ())) == 1
            and stands_as_a_name(text, finding.start, finding.end, found_by_engine=True)
        ):
            spans.add((finding.start, finding.end))
    return spans


# --- The case's key -------------------------------------------------------------------------


def _seed(entry: KeyEntry) -> Group:
    """A group for a key entry: its placeholder, its value as the canonical form, its variants."""
    variants = {entry.value, *entry.variants, *variants_of(entry.value, entry.type)}
    return Group(uuid.uuid4().hex, entry.type, entry.value, variants, [], entry.placeholder)


def _keep_shared_variants_out(seeds: list[Group]) -> None:
    """Take a variant two seeds share away from both: it cannot tell which of them is meant."""
    holders: dict[str, int] = {}
    for seed in seeds:
        for key in {normalize(v) for v in seed.variants}:
            holders[key] = holders.get(key, 0) + 1
    for seed in seeds:
        seed.variants = {v for v in seed.variants if holders[normalize(v)] == 1}


def _seed_matches(
    text: str,
    seeds: list[Group],
    placeholders: list[PlaceholderMatch],
    is_term: Callable[[str], bool],
    names: list[str],
) -> list[Finding]:
    """Every occurrence of the seeds' variants, longest first, as sweep findings."""
    taken = Spans((p.start, p.end) for p in placeholders)
    known = {normalize(name) for name in names}

    def is_name(word: str) -> bool:
        return normalize(word) in known

    variants = sorted(
        ((v, seed) for seed in seeds for v in seed.variants if is_searchable(v)),
        key=lambda pair: (-len(pair[0]), pair[0]),
    )
    found = []
    for variant, seed in variants:
        as_a_name = is_bare_name(seed.type, variant)
        spans = occurrences(
            text, variant, taken, as_a_name=as_a_name, is_term=is_term, is_name=is_name
        )
        for start, end in spans:
            found.append(Finding(seed.type, start, end, text[start:end], 1.0, "sweep"))
    return found


# --- Overlaps, numbers, warnings --------------------------------------------------------------


def _one_per_place(found: list[Finding]) -> list[Finding]:
    """Of the findings that overlap, the one that wins (see the module), in text order."""
    spans: dict[tuple[int, int], list[Finding]] = defaultdict(list)
    for finding in _without_overruns(found):
        spans[(finding.start, finding.end)].append(finding)
    taken = Spans()
    kept = []
    for finding in sorted(map(_span_winner, spans.values()), key=_strength):
        if not taken.overlaps(finding.start, finding.end):
            taken.add(finding.start, finding.end)
            kept.append(finding)
    return sorted(kept, key=lambda f: (f.start, f.end))


def _without_overruns(found: list[Finding]) -> list[Finding]:
    """``found`` without the model's findings that run on past a contract rule's name with its
    legal form, from the same start and of the same type (ruling R45): the rule knows where the
    company ends, and the model's "Acme Supplies Ltd. Passport" would become the canonical form
    that a restore writes back everywhere.
    """
    ends: dict[tuple[PlaceholderType, int], list[int]] = defaultdict(list)
    for f in found:
        if f.source == "rule" and f.score >= RULE_NAME_SCORE and has_legal_form(f.text):
            ends[(f.type, f.start)].append(f.end)
    return [
        f
        for f in found
        if not (f.source == "model" and any(end < f.end for end in ends.get((f.type, f.start), ())))
    ]


def _span_winner(findings: list[Finding]) -> Finding:
    """Of findings on one span, the one that wins (ruling R46): the owner's own values first;
    then a score at least ``SCORE_MARGIN`` higher than the others'; between scores closer than
    that, the type order; then the higher score.
    """
    pool = [f for f in findings if f.source in _OWNERS] or findings
    best = max(f.score for f in pool)
    close = [f for f in pool if best - f.score < SCORE_MARGIN - 1e-9]  # 0.85 - 0.75 is 0.0999...
    return min(close, key=lambda f: (_RANK[f.type], -f.score))


def _strength(finding: Finding) -> tuple[int, int, int, float, int, int]:
    """Sorts the strongest finding first."""
    owners = 0 if finding.source in _OWNERS else 1
    return (
        -len(normalize(finding.text)),
        owners,
        _RANK[finding.type],
        -finding.score,
        -(finding.end - finding.start),
        finding.start,
    )


def _number(
    groups: list[Group], seed_entries: list[KeyEntry], placeholders: list[PlaceholderMatch]
) -> None:
    """Number the groups without a placeholder, per type in order of first appearance, after
    every number the text's placeholders and the case's key use already.
    """
    next_number = dict.fromkeys(PlaceholderType, 1)
    for placeholder in [p.placeholder for p in placeholders] + [
        e.placeholder for e in seed_entries
    ]:
        kind, number = _type_and_number(placeholder)
        next_number[kind] = max(next_number[kind], number + 1)
    for group in groups:
        if not group.placeholder:
            group.placeholder = format_placeholder(group.type, next_number[group.type])
            next_number[group.type] += 1


def _warnings(placeholders: list[PlaceholderMatch]) -> list[str]:
    """The warnings for the owner: the text holds numbered placeholders already."""
    numbered = [p.placeholder for p in placeholders if _type_and_number(p.placeholder)[1] > 0]
    if numbered:
        return [EXISTING_PLACEHOLDERS_WARNING.format(placeholder=numbered[0])]
    return []


def _type_and_number(placeholder: str) -> tuple[PlaceholderType, int]:
    """The type and the number of an exact placeholder, "[COMPANY_2]" or one in the case's key."""
    parsed = PLACEHOLDER_RE.fullmatch(placeholder)
    if parsed is None:
        raise ValueError(f"{placeholder!r} is not a placeholder.")
    return PlaceholderType(parsed["type"]), int(parsed["number"])
