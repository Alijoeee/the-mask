"""The analysis pipeline: from a case's text to the numbered groups the owner reviews.

``CombinedText`` joins the texts of a case's files into one text, with a form feed on a line of
its own between them, and remembers where each file's text lies, so that a finding can be traced
back to its file. ``analyze`` runs the whole analysis on it:

1. The engine reads each file's text on its own (its language model takes at most a million
   characters at a time), and the contract rules collect each file's defined terms into the
   case's lists. The owner's always-hide entries are found wherever they stand.
2. A finding's edges that belong to the sentence (spaces, quotes, an ellipsis, a lone bracket) are
   trimmed, and a finding that runs over a line break is cut there: a replacement must lie within
   one paragraph. The notes the cleaner leaves for a picture, an object, an equation or an
   embedded document cut a finding the same way (ruling R113): the model reads "Acme Supplies
   Ltd[image removed]" as one name, which it is not. Nothing is found inside a placeholder the
   text holds already.
3. A finding that is a never-hide term is dropped; a finding longer than the term is not. The
   names in the text beat its defined terms: in a text that defines ``"Acme" means Acme
   Supplies Ltd``, every "Acme" is still hidden. The owner's never-hide lists and the defaults
   always win over what the engine finds; a value the owner asked to hide (an always-hide entry,
   a stored key's value) loses to a default never-hide term only when it is not hers (training
   round 1): only her own never-hide lists beat it. What the language model finds that is made of
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
from themask.detect.grouping import CHECK_BELOW, PersonName, SurnamePolicy, group_findings
from themask.detect.identity import value_key
from themask.detect.legal import legal_spans, public_spans
from themask.detect.lists import (
    CaseLists,
    UserLists,
    always_hide_entry,
    is_default_term,
    is_it_acronym,
    is_it_guess,
    is_it_word,
    is_vocabulary_word,
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
from themask.instruction import NOTES
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
# The cleaner's notes, which part a finding like a line break (ruling R113).
_NOTE = re.compile("|".join(re.escape(note) for note in NOTES))


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
    found = _vendor_trimmed(_extended_people(found, text), text)
    unlegal_source = found
    legal = legal_spans(text)
    unlegal = _without_legal_references(found, legal)
    found = _people_among_parties(unlegal, text)
    seeds = [_seed(entry) for entry in seed_entries or []]

    is_term = never_hide_check(user_lists, case)  # what a person's bare name may be part of
    names = _names(found, seeds, is_term)
    # A legal term that is part of a name of this document ("Data Act" of "Data Act Ltd") is the
    # party's: what was dropped for it comes back, and the sweep takes it.
    legal = public_spans(text, names)
    if legal != legal_spans(text):
        found = _people_among_parties(_without_legal_references(unlegal_source, legal), text)
    never_hidden = never_hide_check(user_lists, case, names=names)
    owners_never = never_hide_check(user_lists, case, names=names, owners_only=True)
    stems = _legal_stems(found, seeds)

    def is_term_here(form: str, whole: bool) -> bool:
        """A default never-hide term, unless it is (a part of) the name of a company with a legal
        form found in the text: "SIEM Ltd" makes "SIEM" its short name (training round 1).
        """
        return never_hidden(form) and not _of_a_legal_name(form, stems, whole)

    def keep(form: str) -> bool:
        # A single word of the contract's own ("Quality" of Quality Foods Ltd) would be swept
        # out of every clause that uses it.
        common = len(form.split()) == 1 and is_contract_wording(form)
        blocked = owners_never(form) or is_term_here(form, True)
        return is_searchable(form) and not blocked and not common

    def keep_owned(form: str) -> bool:
        return is_searchable(form) and not owners_never(form)

    name_keys = [_words_key(name) for name in names]
    surnames = _surnames_kept(found, text, user_lists, case, is_term)
    defined = {term_key(term) for term in case.defined_terms}
    found = [
        f
        for f in found
        if (f.start, f.end) in surnames
        or not (
            _is_a_term(f, owners_never, is_term_here)
            or (_names_nobody(f, is_term) and not _part_of_a_name(f, name_keys))
            or _starts_a_term(text, f)
        )
    ]
    for seed in seeds:
        seed.variants = {v for v in seed.variants if keep_owned(v)}
    _keep_shared_variants_out(seeds)
    found += _seed_matches(text, seeds, placeholders, is_term, names)

    policy = SurnamePolicy(
        allowed=lambda form: not on_never_hide_list(form, user_lists, case),
        only_one=is_default_term,
        is_term=is_term,
    )
    placed, united = _one_per_place(found, text)
    placed_spans = {(f.start, f.end) for f in placed}
    lost = [
        f
        for f in [*_lost_companies(found, placed), *united]
        if (f.start, f.end) not in placed_spans
    ]
    groups = group_findings(
        [*placed, *lost],
        text,
        seeds=seeds,
        keep=keep,
        aliases=case.defined_terms,
        surnames=policy,
    )
    stored = {seed.id for seed in seeds}
    lost_spans = {(f.start, f.end) for f in lost}
    for group in groups:  # a lost company is a group of variants only: its place is the model's
        group.findings = [f for f in group.findings if (f.start, f.end) not in lost_spans]
    for group in groups:
        # No never-hide word is swept, but a person's bare name, which the sweep takes only
        # where it stands as a name (rulings R42, R50). What the owner asked to hide (her
        # always-hide entries, her key) loses only to her own never-hide lists.
        owned = group.id in stored or any(f.source == "list" for f in group.findings)
        group.variants = {
            v
            for v in group.variants
            if is_bare_name(group.type, v)
            or not (owners_never(v) if owned else is_term_here(v, True))
        }
    sweep(text, groups, fixed=seeds, is_term=is_term, public=legal)
    groups = [g for g in groups if g.findings]  # a seed not in this text, a group taken over
    groups = _with_own_groups(groups, stored)
    for group in groups:
        group.findings.sort(key=lambda f: (f.start, f.end))
        if any((f.start, f.end) in surnames for f in group.findings) or any(
            is_bare_name(group.type, f.text) and _ordinary(f.text, defined) for f in group.findings
        ):
            group.needs_check = True
    for group in _unsure_guesses(groups, stored):
        group.enabled, group.needs_check = False, True
    groups.sort(key=lambda g: g.findings[0].start)
    _number(groups, seed_entries or [], placeholders)
    return Analysis(text, groups, _warnings(placeholders))


# --- Finding ---------------------------------------------------------------------------------


def _detected(combined: CombinedText, engine: Engine, case: CaseLists) -> list[Finding]:
    """What the engine finds in each file's text, placed in the combined text, trimmed and cut
    at line breaks; each file's defined terms go into ``case``.
    """
    found: list[Finding] = []
    notes = Spans(match.span() for match in _NOTE.finditer(combined.text))
    for _, start, end in combined.parts:
        part = combined.text[start:end]
        if not part.strip():
            continue
        case.defined_terms |= find_defined_terms(part)
        for finding in engine.analyze(part):
            moved = replace(finding, start=finding.start + start, end=finding.end + start)
            found += _cleaned(combined.text, moved, notes)
    return found


def _without_legal_references(found: list[Finding], spans: list[tuple[int, int]]) -> list[Finding]:
    """``found`` without what the model or a pattern took from inside a reference to a law, a
    regulation, a standard or a code ("6698" of "Law No. 6698", "GDPR", "Kanun No"): public text
    (task D7). What the owner listed, a rule found or a person selected stays, and so does a
    finding that is longer than the reference ("Act No. 5237 Holdings Ltd").
    """
    if not spans:
        return found
    starts = [start for start, _ in spans]

    def inside(finding: Finding) -> bool:
        index = bisect_right(starts, finding.start) - 1
        return index >= 0 and finding.end <= spans[index][1]

    return [f for f in found if f.source not in ("model", "pattern") or not inside(f)]


def _listed(text: str, user: UserLists, case: CaseLists) -> list[Finding]:
    """Every occurrence of the owner's and the case's always-hide entries."""
    found = []
    for entry in [*user.always_hide, *case.always_hide]:
        kind, value = always_hide_entry(entry)
        if is_searchable(value):
            for start, end in occurrences(text, value, Spans()):
                found.append(Finding(kind, start, end, text[start:end], 1.0, "list"))
    return found


def _cleaned(text: str, finding: Finding, notes: Spans | None = None) -> list[Finding]:
    """``finding`` without the marks at its edges, cut into one piece per line and at each of the
    cleaner's ``notes`` (ruling R113); a piece with no letter or digit is dropped.
    """
    pieces = []
    start = finding.start
    for position in range(finding.start, finding.end + 1):
        if (
            position == finding.end
            or text[position] in LINE_BREAKS
            or (notes is not None and notes.overlaps(position, position + 1))
        ):
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


def _is_a_term(
    finding: Finding,
    owners_never: Callable[[str], bool],
    is_term_here: Callable[[str, bool], bool],
) -> bool:
    """Whether ``finding`` is a never-hide term and is dropped. The owner's own never-hide lists
    beat everything; a value she asked to hide (an always-hide match) is beaten by nothing else;
    a person is never dropped for being an IT acronym ("PAM", "DAM"); the rest is dropped when it
    is a default term and not (part of) the name of a company with a legal form.
    """
    if owners_never(finding.text):
        return True
    if finding.source == "list":
        return False
    if finding.type is PlaceholderType.PERSON and is_it_acronym(finding.text):
        return False
    return is_term_here(finding.text, False)


def _legal_stems(found: list[Finding], seeds: list[Group]) -> set[str]:
    """The names of the companies with a legal form that the text names, without the legal form,
    as ``_words_key`` gives them: "SIEM Ltd" gives "siem".
    """
    forms = [f.text for f in found if f.type is PlaceholderType.COMPANY]
    for seed in seeds:
        if seed.type is PlaceholderType.COMPANY:
            forms += [seed.canonical, *seed.variants]
    return {
        key
        for form in forms
        if has_legal_form(form) and (key := _words_key(strip_legal_form(form)))
    }


def _of_a_legal_name(form: str, stems: set[str], whole: bool) -> bool:
    """Whether ``form`` is the name of a company with a legal form (``stems``), or, unless
    ``whole``, a run of two words or more inside it: "Integration Services" of "Advanced
    Integration Services Ltd". Such a form is a name, whatever its words are.
    """
    key = _words_key(form)
    if not key:
        return False
    if key in stems:
        return True
    return not whole and len(key.split()) > 1 and any(_inside(key, stem) for stem in stems)


# What a product name is made of besides the vendor's own name ("Kron PAM User Subscription").
_PRODUCT_WORDS = frozenset(
    [
        "privileged",
        "access",
        "management",
        "data",
        "classification",
        "protection",
        "prevention",
        "loss",
        "suite",
        "user",
        "users",
        "subscription",
        "security",
        "digital",
        "platform",
        "enterprise",
        "edition",
        "server",
        "client",
        "agent",
        "module",
        "end",
        "point",
        "cloud",
        "web",
        "email",
        "network",
        "application",
        "applications",
        "identity",
        "governance",
        "monitoring",
        "analytics",
        "threat",
        "detection",
        "response",
        "insight",
        "vault",
        "console",
        "manager",
        "studio",
        "pro",
        "plus",
        "lite",
        "core",
        "standard",
        "advanced",
        "service",
        "services",
        "product",
        "products",
        "solution",
        "solutions",
    ]
)


def _ordinary_around(text: str, finding: Finding, owned: list[Finding]) -> bool:
    """Whether ``finding``, besides the owner's values it holds, has only ordinary words: filler,
    numbers, lower case words, IT words, product words ("Kron PAM User Subscription").
    """
    rest = list(text[finding.start : finding.end])
    for value in owned:
        for position in range(value.start - finding.start, value.end - finding.start):
            rest[position] = " "
    for word in re.findall(r"[^\W_]+", "".join(rest)):
        if not (
            word.casefold() in _FILLER
            or word.casefold() in _PRODUCT_WORDS
            or (word.isdigit() and len(word) < 4)
            or word[0].islower()
            or is_it_word(word)
        ):
            return False
    return True


def _vendor_trimmed(found: list[Finding], text: str) -> list[Finding]:
    """``found`` without the language model's guesses of a company that hold a value of the
    owner's own and nothing else but ordinary words: "Kron PAM User Subscription" with Kron on
    her always-hide list is hidden as Kron alone, which the list finding already does. A name with
    a legal form, and anything a rule found, is never cut this way.
    """
    owned = [f for f in found if f.source == "list"]
    if not owned:
        return found
    kept = []
    for finding in found:
        if (
            finding.source == "model"
            and finding.type is PlaceholderType.COMPANY
            and not has_legal_form(finding.text)
        ):
            inside = [
                o
                for o in owned
                if finding.start <= o.start
                and o.end <= finding.end
                and (o.start, o.end) != (finding.start, finding.end)
            ]
            if inside and _ordinary_around(text, finding, inside):
                continue
        kept.append(finding)
    return kept


_POSSESSIVE_END = re.compile(r"['\N{RIGHT SINGLE QUOTATION MARK}][sS]\Z")
# The next word of a name, with the apostrophes inside it ("O'Brien", "D'Souza'nın").
_NAME_WORD = re.compile(r"[ \t]+([^\W\d_][\w\-]*(?:['\N{RIGHT SINGLE QUOTATION MARK}][\w\-]+)*)")
# A Turkish case suffix after the last apostrophe of a name: "Ahmet'in", "Berg'in", "O'Brien'ın".
_TURKISH_SUFFIX = re.compile(
    r"['\N{RIGHT SINGLE QUOTATION MARK}](?:n?[ıiuü]n|n?[ae]|[dt][ae]|[dt][ae]n|l[ae]|y[ae]|y[ıiuü])\Z",
    re.IGNORECASE,
)
_TITLE_WORDS = frozenset(
    [
        "director",
        "managing",
        "ceo",
        "cfo",
        "coo",
        "cto",
        "chairman",
        "president",
        "manager",
        "secretary",
        "counsel",
        "general",
        "genel",
        "müdürü",
        "müdür",
        "müşaviri",
        "mr",
        "mrs",
        "ms",
        "mx",
        "dr",
        "prof",
        "sir",
        "dame",
        "mah",
        "mahallesi",
        "cad",
        "cadde",
        "sok",
        "sokak",
        "street",
    ]
)


def _extended_people(found: list[Finding], text: str) -> list[Finding]:
    """``found`` with each person of the language model's that ends on a capitalised word extended
    to the capitalised word after it, when the two together are a full name found elsewhere in
    the text: the model's "A.Ş. Genel Müdürü Ahmet" in front of "Yılmaz" must not leave the surname
    visible where "Ahmet Yılmaz" is hidden at the next sentence. A name that ends on a job title or an honorific is not extended, and neither over a word that
    belongs to another finding.
    """
    full_names = {
        normalize(f.text)
        for f in found
        if f.type is PlaceholderType.PERSON and len(f.text.split()) > 1
    }
    extended = []
    for finding in found:
        words = finding.text.split()
        following = _NAME_WORD.match(text, finding.end)
        if (
            finding.type is PlaceholderType.PERSON
            and finding.source == "model"
            and words
            and words[-1][:1].isupper()
            and words[-1].casefold().strip(".,") not in _TITLE_WORDS
            and following is not None
            and following[1][:1].isupper()
        ):
            word = _POSSESSIVE_END.sub("", following[1])
            word = _TURKISH_SUFFIX.sub("", word)
            end = following.start(1) + len(word)
            if normalize(f"{words[-1]} {word}") in full_names and not any(
                o is not finding and o.start < end and following.start(1) < o.end for o in found
            ):
                finding = replace(finding, end=end, text=text[finding.start : end])
        extended.append(finding)
    return extended


def _lost_companies(found: list[Finding], placed: list[Finding]) -> list[Finding]:
    """The companies with a legal form that a contract rule found and that lost their place to a
    longer finding of the language model ("Teknoloji A.Ş. ile GLOBAL Gıda A.Ş. arasında
    imzalanmıştır" over two companies). The model's span is hidden as it is found, nothing is cut;
    these companies are grouped as well, without their finding in that place, so that their other
    occurrences are swept ("GLOBAL Teknoloji öder").
    """
    taken = {(f.start, f.end) for f in placed}
    models = [f for f in placed if f.source == "model" and f.type in _NAMES]
    return [
        f
        for f in found
        if f.type is PlaceholderType.COMPANY
        and f.source == "rule"
        and f.score >= RULE_NAME_SCORE
        and has_legal_form(f.text)
        and (f.start, f.end) not in taken
        and any(m.start < f.end and f.start < m.end for m in models)
    ]


def _starts_a_term(text: str, finding: Finding) -> bool:
    """Whether a person or company of one word that the engine found is the first word of a
    default never-hide term with the word after it: "Disclosing" in "(1) The Disclosing Party",
    which the parties clause reads as a party's name.
    """
    if finding.type not in _NAMES or finding.source == "list" or len(finding.text.split()) != 1:
        return False
    following = _NEXT_WORD.match(text, finding.end)
    return following is not None and is_default_term(f"{finding.text} {following[1]}")


def _names_nobody(finding: Finding, is_term: Callable[[str], bool]) -> bool:
    """Whether the language model found a text made of the contract's own words only, which
    names nobody: "GOVERNING LAW", "the Recipient for the Purpose" (``is_contract_wording``), or
    a never-hide term with filler words, at low confidence: "the Confidential Information of
    the other" (ruling R122, item 2). A confident guess, and any word that is not a default
    never-hide term, keeps the finding: "The Capital Group" is a company.
    """
    if finding.source != "model":
        return False
    if is_contract_wording(finding.text):
        return True
    return (
        finding.type in _NAMES
        and finding.score < CHECK_BELOW
        and _plain_words(finding.text, whole=True) == _WITH_FILLER
    )


# Small words that join the ordinary words of a phrase without naming anybody.
_FILLER = frozenset(
    {"the", "of", "a", "an", "and", "or", "to", "in", "on", "for", "by", "with", "from", "other"}
    | {"another", "any", "each", "either", "neither", "such", "this", "that", "these", "those"}
    | {"its", "their", "his", "her", "as", "at", "between", "under", "upon", "&"}
)
_PLAIN_WORD = re.compile(r"[^\W\d_]+(?:['\N{RIGHT SINGLE QUOTATION MARK}\-][^\W\d_]+)*")
# What ``_plain_words`` reports: made of default never-hide words with at least one filler word
# (``_WITH_FILLER``); made of them with no filler (``_PLAIN``); anything else (``_NAME_SHAPED``).
_WITH_FILLER, _PLAIN, _NAME_SHAPED = "filler", "plain", "name"


def _plain_words(text: str, whole: bool = False) -> str:
    """How ``text`` reads: ``_WITH_FILLER``, ``_PLAIN`` or ``_NAME_SHAPED`` (see above).

    Only the default never-hide terms count (ruling R122), not COMMON_WORDS and not the terms a
    document defines: every word must be a word of a default term and not a place, a month or a
    body. Every run of words between filler words must be a default term itself ("Confidential
    Information", not "Standard") or, unless ``whole``, made of default terms ("Services Agreement").
    A word with a digit makes it name-shaped.
    """
    words = [word.strip(".,:;()\"'") for word in text.split()]
    words = [word for word in words if word]
    if not words or any(not _PLAIN_WORD.fullmatch(word) for word in words):
        return _NAME_SHAPED
    others = [word for word in words if word.casefold() not in _FILLER]
    if not others or not all(is_vocabulary_word(word) for word in others):
        return _NAME_SHAPED
    runs: list[list[str]] = [[]]
    for word in words:
        if word.casefold() in _FILLER:
            runs.append([])
        else:
            runs[-1].append(word)
    for run in filter(None, runs):
        if not (is_default_term(" ".join(run)) or (not whole and all(map(is_default_term, run)))):
            return _NAME_SHAPED
    return _WITH_FILLER if len(others) < len(words) else _PLAIN


def _words_key(text: str) -> str:
    """``text`` as its normalised words joined by single spaces: "Bank-Services  Ltd." gives
    "bank services ltd". A hyphen, a dash or a slash parts words, and "and" and "&" are left
    out, so "Software & Services" and "Software-and-Services" key alike.
    """
    words = map(normalize, re.split(r"[\s/\-\N{HYPHEN}-\N{HORIZONTAL BAR}]+", text))
    return " ".join(word for word in words if word and word != "and")


def _inside(short: str, long: str) -> bool:
    """Whether the words of ``short`` stand as a run of whole words in ``long`` (both as
    ``_words_key`` gives them).
    """
    a, b = short.split(), long.split()
    return bool(a) and any(b[i : i + len(a)] == a for i in range(len(b) - len(a) + 1))


def _part_of_a_name(finding: Finding, name_keys: list[str]) -> bool:
    """Whether the words of ``finding`` stand as a run inside a name that is found in the text:
    "Equipment and Software" of "Equipment and Software Group Ltd" is that company's short form,
    not a phrase of the contract (R122 item 2 leaves it to the normal handling).
    """
    key = _words_key(finding.text)
    return any(_inside(key, name) for name in name_keys)


def _unsure_guesses(groups: list[Group], stored: set[str]) -> list[Group]:
    """The groups that are low-confidence guesses of the language model made only of default
    never-hide words ("Personal Services"): shown, not hidden, and the owner is asked (ruling
    R122, item 1). Only a company is asked about, and only when the guess comes from the model
    alone: a value a rule, a pattern, the owner or a stored key found, a person, anything
    name-shaped, and any form that is, or holds, or sits inside a form of a name that stays
    hidden is not.
    """

    def guess(group: Group) -> bool:
        found = [f for f in group.findings if f.source != "sweep"]
        return (
            group.type is PlaceholderType.COMPANY
            and group.id not in stored
            and bool(found)
            and all(f.source == "model" and f.score < CHECK_BELOW for f in found)
            and all(
                _plain_words(form) == _PLAIN or is_it_guess(form) or is_it_word(form)
                for form in {group.canonical, *group.variants}
            )
        )

    asked = [g for g in groups if guess(g)]
    kept = {id(g) for g in asked}
    hidden = [
        _words_key(form)
        for g in groups
        if id(g) not in kept and g.type in _NAMES
        for form in {g.canonical, *g.variants}
    ]
    return [
        g
        for g in asked
        if not any(
            _inside(_words_key(form), other) or _inside(other, _words_key(form))
            for form in {g.canonical, *g.variants}
            for other in hidden
        )
    ]


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
        elif finding.type in _NAMES and not (
            is_term(finding.text) or _names_nobody(finding, is_term)
        ):
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
        for key in {value_key(seed.type, v) for v in seed.variants}:
            holders[key] = holders.get(key, 0) + 1
    for seed in seeds:
        seed.variants = {v for v in seed.variants if holders[value_key(seed.type, v)] == 1}


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


def _with_own_groups(groups: list[Group], stored: set[str]) -> list[Group]:
    """``groups`` where each finding that is no form of its group (the words of its text are not
    all words of the group's canonical form and it is none of the forms the group lists, as a union
    a growth made) is moved to a group of its
    own, with that text as its canonical form and its only variant. A restore writes the
    canonical form back in every place: a place whose words the canonical form does not hold
    would lose them. A short form of the value (fewer words, all of them the canonical form's)
    stays. The case's key is left as it is.
    """

    def words(text: str) -> set[str]:
        return {normalize(word) for word in re.findall(r"[^\W_]+", text)}

    out: list[Group] = []
    for group in groups:
        out.append(group)
        if group.id in stored:
            continue
        held = words(group.canonical)
        forms = {normalize(form) for form in (group.canonical, *group.variants)}
        foreign: dict[str, list[Finding]] = defaultdict(list)
        for finding in group.findings:
            if not words(finding.text) <= held and normalize(finding.text) not in forms:
                foreign[normalize(finding.text)].append(finding)
        if not foreign:
            continue
        moved = {id(f) for found in foreign.values() for f in found}
        group.findings = [f for f in group.findings if id(f) not in moved]
        group.disabled = set()
        for found in foreign.values():
            first = found[0]
            out.append(
                Group(
                    uuid.uuid4().hex,
                    group.type,
                    first.text,
                    {f.text for f in found},
                    found,
                    "",
                    enabled=group.enabled,
                    needs_check=group.needs_check,
                )
            )
    return [g for g in out if g.findings]


# --- Overlaps, numbers, warnings --------------------------------------------------------------


# The types whose findings carry text to hide, and so are grown to the union when they overlap
# (``_one_per_place``).
_WORDS = frozenset(
    {
        PlaceholderType.PERSON,
        PlaceholderType.COMPANY,
        PlaceholderType.ADDRESS,
        PlaceholderType.CUSTOM,
    }
)
_EDGE_DOTS = ".,;:"


def _one_per_place(found: list[Finding], text: str) -> tuple[list[Finding], list[Finding]]:
    """Of the findings that overlap, the one that wins (see the module), in text order, and the
    findings that lost their place or were changed by it, to be grouped for the sweep.

    Hiding only grows. A person, company or address that loses to a finding it overlaps only in
    part is not dropped: the winner grows to the union of the two spans (and takes in what that
    reaches). A value (an amount, a phone number, an identifier) that loses to a person, company or
    address is not dropped either: the winner is trimmed to stop where the value starts or ends.
    The owner's own values never grow and are never trimmed. Each loser is visited once.
    """
    spans: dict[tuple[int, int], list[Finding]] = defaultdict(list)
    for finding in _without_overruns(found):
        spans[(finding.start, finding.end)].append(finding)
    taken = Spans()
    kept: list[Finding] = []
    rejected: list[Finding] = []
    for finding in sorted(map(_span_winner, spans.values()), key=_strength):
        if not taken.overlaps(finding.start, finding.end):
            taken.add(finding.start, finding.end)
            kept.append(finding)
        else:
            rejected.append(finding)
    kept.sort(key=lambda f: f.start)
    starts = [f.start for f in kept]
    registered: list[Finding] = []
    stands = {(f.type, normalize(f.text)) for f in kept}
    for loser in rejected:
        block = _span_block(kept, starts, loser.start, loser.end)
        inside_a_rule = any(
            kept[i].source == "rule" and kept[i].start <= loser.start and loser.end <= kept[i].end
            for i in block
        )
        if (
            loser.type in _WORDS
            and not inside_a_rule  # a company's own words are its variants already
            and (loser.type, normalize(loser.text)) not in stands
        ):
            registered.append(loser)  # its value is swept elsewhere, whatever happens here
        if not block:
            continue
        if loser.type in _WORDS:
            _grow(kept, starts, block, loser, text, registered)
        else:
            _trim(kept, starts, block, loser, text)
    return kept, registered


def _span_block(kept: list[Finding], starts: list[int], start: int, end: int) -> list[int]:
    """The indexes of the kept findings that overlap ``start``-``end``."""
    first = max(0, bisect_right(starts, start) - 1)
    out = []
    for i in range(first, len(kept)):
        if kept[i].start >= end:
            break
        if start < kept[i].end:
            out.append(i)
    return out


def _grow(
    kept: list[Finding],
    starts: list[int],
    block: list[int],
    loser: Finding,
    text: str,
    registered: list[Finding],
) -> None:
    """Grow the first winner of ``block`` that holds ``loser`` in part to the union with it and
    with everything the union reaches (a person's, a company's or an address, never the owner's
    own); nothing changes when the union would reach an owner's value or a value of another kind,
    or when ``loser`` lies within a winner.
    """
    winner = next((kept[i] for i in block if kept[i].type in _WORDS), None)
    if winner is None or winner.source in _OWNERS:
        return
    if all(kept[i].start <= loser.start and loser.end <= kept[i].end for i in block):
        return  # held whole by a winner: hidden already
    start, end = min(winner.start, loser.start), max(winner.end, loser.end)
    while True:
        reached = _span_block(kept, starts, start, end)
        if any(kept[i].source in _OWNERS or kept[i].type not in _WORDS for i in reached):
            return
        low = min([start] + [kept[i].start for i in reached])
        high = max([end] + [kept[i].end for i in reached])
        if (low, high) == (start, end):
            break
        start, end = low, high
    registered += [kept[i] for i in reached]
    grown = replace(winner, start=start, end=end, text=text[start:end])
    kept[reached[0] : reached[-1] + 1] = [grown]
    starts[reached[0] : reached[-1] + 1] = [start]


def _trim(
    kept: list[Finding], starts: list[int], block: list[int], value: Finding, text: str
) -> None:
    """Make room for ``value`` (an amount, a phone number, an identifier) that lost its place to
    names: each person, company or address of ``block`` is trimmed to stop where the value starts
    and ends, and the value takes its place. Nothing changes when the owner's own values or a
    finding of another kind are in the way."""
    if any(kept[i].source in _OWNERS or kept[i].type not in _WORDS for i in block):
        return
    if all(kept[i].start <= value.start and value.end <= kept[i].end for i in block):
        return  # held whole by a winner: hidden already
    pieces: list[Finding] = []
    for i in block:
        winner = kept[i]
        for lo, hi in ((winner.start, value.start), (value.end, winner.end)):
            if lo < hi:
                lo, hi = _trimmed(text, lo, hi)
                while lo < hi and text[lo] in _EDGE_DOTS:
                    lo, hi = _trimmed(text, lo + 1, hi)
                if lo < hi and any(c.isalnum() for c in text[lo:hi]):
                    pieces.append(replace(winner, start=lo, end=hi, text=text[lo:hi]))
    pieces.append(value)
    pieces.sort(key=lambda f: f.start)
    kept[block[0] : block[-1] + 1] = pieces
    starts[block[0] : block[-1] + 1] = [f.start for f in pieces]


def _without_overruns(found: list[Finding]) -> list[Finding]:
    """``found`` without the model's findings that run on past a contract rule's name with its
    legal form and a full stop that ends the sentence, from the same start and of the same type
    (ruling R45): the rule knows where the company ends, and the model's "Acme Supplies Ltd. Passport" would become the canonical form
    that a restore writes back everywhere.
    """
    ends: dict[tuple[PlaceholderType, int], list[int]] = defaultdict(list)
    for f in found:
        if f.source == "rule" and f.score >= RULE_NAME_SCORE and has_legal_form(f.text):
            ends[(f.type, f.start)].append(f.end)
    return [
        f
        for f in found
        if not (
            f.source == "model"
            and any(
                end < f.end and f.text[end - f.start : end - f.start + 1] == "."
                for end in ends.get((f.type, f.start), ())
            )
        )
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
