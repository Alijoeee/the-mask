"""Variant grouping: the findings that stand for one real value become one group.

People (PERSON):

* the same name, with or without an honorific and in any case, is one person: "Mr John Smith",
  "JOHN SMITH" and "John Smith";
* a first initial with the surname ("J. Smith", "J. van der Berg") joins the one full name with
  that initial and surname;
* a surname on its own or after an honorific ("Smith", "Mr Smith") joins the one full name with
  that surname.

  The surname of a full name is everything after its first name ("van der Berg" of Jane van der
  Berg), and its last word alone ("Berg") counts too, as long as only one full name fits. When no
  full name fits, or more than one does, the mention is a group of its own. A surname mention is
  then marked for the owner to check, and so is an initial that more than one full name fits:
  "Mr Smith" after John Smith and Jane Smith is never silently given to either.

Companies (COMPANY):

* the same name with or without its legal form is one company: "Acme Supplies Ltd" and "Acme
  Supplies" ("Ltd" and "Limited", "Inc." and "Incorporated" are one legal form). One name with
  two different legal forms is two companies ("Northwind Trading B.V." and "Northwind Trading
  GmbH"), and the name without a legal form is then a group to check;
* a single word ("ACME") joins the one company whose name it is or whose first-word short form
  it is (``variants_of``), and is a group to check when it fits several.

Where several companies fit a short form, a strong one wins over the language model's guesses
that need a check: "Westerkade" belongs to Westerkade Insurance N.V. (a rule found it), not to the
running header "Westerkade / Liffey — Data Processing Agreement" the model took for a company.

The language model sometimes takes a company's short name for a person ("Acme signs.") or the
other way round. A "company" without a legal form that has an honorific or an initial is a person
("Mr Edwards", "S. Davies"), and a "person" with a legal form a company. A single word found as a
person that is nobody's surname or first name joins the company it fits, and a single word found
as a company that fits no company joins the one person whose surname it is.

Every other type: the findings with the same value, however it is spelt (``normalize``), are one
group.

The variants of a group are the forms it was seen in and the forms ``variants_of`` derives from
them ("J. Smith" of John Smith, "Northwind" of Northwind Trading B.V.); for a name of three words
or more also the initial with the whole surname ("J. van der Berg"). The sweep looks for every
variant, so a variant must belong to one group only. A form one group was seen in, or that is its
name, is that group's alone; any other form that more than one group derives belongs to none of
them, and where it stands in the text on its own it becomes a group of its own to check.

A group is also marked for checking when its best score is below 0.7. Sweep findings, at 1.0,
never count for this: a value the sweep found again is no surer for it. The canonical form is the
longest form the group was seen in, for a person the longest with a space in it, and of equal
lengths the one not in capitals, then the first. The placeholder is left empty for the caller to
number.

Seed groups, the groups of a case's key when a file is added to the case, keep their placeholder,
canonical form and variants; a finding of one of their variants joins them, and their variants
are theirs alone.
"""

from __future__ import annotations

import re
import sys
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace

from themask.detect.sweep import Spans, is_searchable, occurrences
from themask.model import Finding, Group, PlaceholderType
from themask.placeholders import find_placeholders
from themask.textnorm import HONORIFICS, has_legal_form, normalize, strip_legal_form, variants_of

PERSON = PlaceholderType.PERSON
COMPANY = PlaceholderType.COMPANY
_NAMES = frozenset({PERSON, COMPANY})

# A group whose best score from detection is below this is marked for the owner to check.
CHECK_BELOW = 0.7

_HONORIFIC_KEYS = frozenset(normalize(honorific) for honorific in HONORIFICS)
# The small words a surname may start with: "van der Berg", "de la Cruz", "von Bülow".
_PARTICLES = frozenset(
    {"van", "der", "den", "de", "del", "della", "di", "da", "du", "la", "le", "von", "zu"}
    | {"ter", "ten", "bin", "al", "el", "y"}
)
# A first name written as its initial: "J", "J." or "J.A.".
_INITIAL = re.compile(r"[^\W\d_]\.?|(?:[^\W\d_]\.){2,4}")
_LEADING_THE = re.compile(r"(?i:the)\s+")
# Spellings of one legal form, normalised.
_SAME_LEGAL_FORM = {"limited": "ltd", "incorporated": "inc", "corporation": "corp"}


# --- What a finding says about the name it holds ---------------------------------------------


@dataclass(frozen=True)
class _Person:
    """A person's name as written: its words after any honorific, and whether one stood there."""

    words: tuple[str, ...]
    honorific: bool

    @classmethod
    def of(cls, text: str) -> _Person:
        words = text.split()
        honorific = False
        while words and normalize(words[0]) in _HONORIFIC_KEYS:
            words = words[1:]
            honorific = True
        return cls(tuple(words), honorific)

    @property
    def is_full(self) -> bool:
        """A first name and a surname: "John Smith", "Dr Jane van der Berg"."""
        return len(self.words) >= 2 and not self.is_initial and not self._starts_with_particle

    @property
    def is_initial(self) -> bool:
        """An initial and a surname: "J. Smith"."""
        return len(self.words) >= 2 and _INITIAL.fullmatch(self.words[0]) is not None

    @property
    def is_one_word(self) -> bool:
        """A single word and no honorific: "Smith", or a short name the model took for a person."""
        return len(self.words) == 1 and not self.honorific

    @property
    def _starts_with_particle(self) -> bool:
        return self.words[0].casefold() in _PARTICLES

    @property
    def key(self) -> str:
        return normalize("".join(self.words))

    @property
    def initial(self) -> str:
        return self.words[0][:1].casefold()

    @property
    def first(self) -> str:
        return normalize(self.words[0])

    @property
    def surname(self) -> str:
        """For a full name or an initial, everything after the first word; else every word."""
        words = self.words[1:] if self.is_full or self.is_initial else self.words
        return normalize("".join(words))

    @property
    def last(self) -> str:
        return normalize(self.words[-1]) if self.words else ""


def _without_the(text: str) -> str:
    """``text`` without a leading "the": the model's "the Northwind Group" is Northwind Group."""
    the = _LEADING_THE.match(text)
    return text[the.end() :] if the and the.end() < len(text) else text


@dataclass(frozen=True)
class _Company:
    """A company's name as written: its name without the legal form, and the legal form."""

    stem: str  # the name without its legal form, normalised
    form: str | None  # the legal form, normalised, or None when the name has none
    words: int  # how many words the name has without its legal form
    first_word: str  # its first-word short form, normalised, or "" when it has none

    @classmethod
    def of(cls, text: str) -> _Company:
        name = _without_the(text)
        stem_text = strip_legal_form(name) or name
        stem = normalize(stem_text)
        form = None
        if stem_text != name:
            whole = normalize(name)
            suffix = whole.removeprefix(stem)
            form = _SAME_LEGAL_FORM.get(suffix, suffix)
        short = {normalize(v) for v in variants_of(name, COMPANY) if len(v.split()) == 1}
        first = normalize(stem_text.split()[0]) if stem_text.split() else ""
        return cls(stem, form, len(stem_text.split()), first if first in short else "")

    @property
    def is_full(self) -> bool:
        """A name with a legal form or of two words or more: not just a short name."""
        return self.form is not None or self.words >= 2


# --- Groups in the making ----------------------------------------------------------------------


@dataclass(eq=False)
class _Bucket:
    """A group in the making: its findings, and what its name says for the mentions to join."""

    type: PlaceholderType
    findings: list[Finding] = field(default_factory=list)
    seed: Group | None = None
    names: set[str] = field(default_factory=set)  # keys that are this group's name
    flagged: bool = False
    person: _Person | None = None  # the full name, for a group of a person
    companies: list[_Company] = field(default_factory=list)  # its names, for a company
    variants: set[str] = field(default_factory=set)

    @classmethod
    def of_seed(cls, seed: Group) -> _Bucket:
        bucket = cls(seed.type, seed=seed, names={normalize(v) for v in seed.variants})
        bucket.names.add(normalize(seed.canonical))
        if seed.type is PERSON and _Person.of(seed.canonical).is_full:
            bucket.person = _Person.of(seed.canonical)
        if seed.type is COMPANY:
            bucket.companies.append(_Company.of(seed.canonical))
        return bucket

    def add(self, finding: Finding) -> None:
        self.findings.append(
            finding if finding.type is self.type else replace(finding, type=self.type)
        )

    def own(self) -> set[str]:
        """The keys of the forms that are this group's alone: its name and the forms seen."""
        return self.names | {normalize(f.text) for f in self.findings}

    def first_seen(self) -> int:
        return min((f.start for f in self.findings), default=sys.maxsize)

    @property
    def stems(self) -> set[str]:
        return {company.stem for company in self.companies}

    @property
    def first_words(self) -> set[str]:
        return {company.first_word for company in self.companies} - {""}


def _keep_all(variant: str) -> bool:
    return True


def group_findings(
    findings: list[Finding],
    text: str,
    *,
    seeds: Iterable[Group] = (),
    keep: Callable[[str], bool] | None = None,
) -> list[Group]:
    """The groups of ``findings``, in order of first appearance in ``text`` (see the module).

    ``seeds`` are groups that exist already (a case's key); they come back as the same objects,
    with the findings that joined them. ``keep`` says whether a form ``variants_of`` derives may
    be a variant (the pipeline leaves out the never-hide terms); the forms seen are always kept.
    Findings are expected not to overlap: the pipeline settles overlaps first.
    """
    keep_variant = keep or _keep_all
    seed_buckets = [_Bucket.of_seed(seed) for seed in seeds]
    by_seed_key: dict[str, _Bucket] = {}
    for bucket in seed_buckets:
        for key in sorted(bucket.names):
            by_seed_key.setdefault(key, bucket)

    pending: dict[PlaceholderType, list[Finding]] = defaultdict(list)
    for finding in sorted(map(_as_named, findings), key=lambda f: (f.start, f.end)):
        seed = by_seed_key.get(normalize(finding.text))
        if seed is not None and _may_join(finding.type, seed.type):
            seed.add(finding)
        else:
            pending[finding.type].append(finding)

    buckets = list(seed_buckets)
    for kind, found in pending.items():
        if kind not in _NAMES:
            buckets += _by_value(kind, found)
    people = _people(pending[PERSON], buckets)
    companies = _companies(pending[COMPANY], buckets)
    _place_people(people, buckets)
    _place_companies(companies, buckets)
    buckets = [b for b in buckets if b.findings or b.seed is not None]
    buckets += _settle_variants(buckets, text, keep_variant)
    buckets.sort(key=_Bucket.first_seen)
    return [_group(bucket) for bucket in buckets]


def _as_named(finding: Finding) -> Finding:
    """``finding`` with the type its words show where the model mixed up a person and a company:
    a company without a legal form that has an honorific or an initial is a person ("Mr
    Edwards", "S. Davies"), and a person with a legal form is a company.
    """
    if finding.type is COMPANY and not has_legal_form(finding.text):
        person = _Person.of(finding.text)
        if (person.honorific and person.words) or person.is_initial:
            return replace(finding, type=PERSON)
    if finding.type is PERSON and has_legal_form(finding.text):
        return replace(finding, type=COMPANY)
    return finding


def _may_join(finding_type: PlaceholderType, group_type: PlaceholderType) -> bool:
    return finding_type is group_type or {finding_type, group_type} <= _NAMES


def _by_value(kind: PlaceholderType, findings: list[Finding]) -> list[_Bucket]:
    """One group for each value, however it is spelt."""
    buckets: dict[str, _Bucket] = {}
    for finding in findings:
        key = normalize(finding.text)
        bucket = buckets.setdefault(key, _Bucket(kind, names={key}))
        bucket.add(finding)
    return list(buckets.values())


# --- People ------------------------------------------------------------------------------------


def _people(findings: list[Finding], buckets: list[_Bucket]) -> dict[str, list[Finding]]:
    """Full names into groups (``buckets`` grows), the other mentions by their spelling."""
    by_name = {b.person.key: b for b in buckets if b.seed is not None and b.person is not None}
    mentions: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        person = _Person.of(finding.text)
        if not person.is_full:
            mentions[normalize(finding.text)].append(finding)
            continue
        bucket = by_name.get(person.key)
        if bucket is None:
            bucket = by_name[person.key] = _Bucket(PERSON, names={person.key}, person=person)
            buckets.append(bucket)
        bucket.add(finding)
    return mentions


def _person_claims(person: _Person, buckets: list[_Bucket]) -> list[_Bucket]:
    """The groups of the full names a mention of ``person`` fits."""
    claims = []
    for bucket in buckets:
        full = bucket.person
        if full is None:
            continue
        if person.is_initial:
            fits = full.initial == person.initial and person.surname in {full.surname, full.last}
        else:
            fits = person.key in {full.surname, full.last}
        if fits:
            claims.append(bucket)
    return claims


def _company_claims(key: str, buckets: list[_Bucket]) -> list[_Bucket]:
    """The groups of the companies whose name, or first-word short form, is ``key``."""
    named = [b for b in buckets if b.type is COMPANY and key in b.stems]
    return named or [b for b in buckets if b.type is COMPANY and key in b.first_words]


def _place_people(mentions: dict[str, list[Finding]], buckets: list[_Bucket]) -> None:
    """Each mention joins the one full name it fits; else it is a group of its own."""
    for found in mentions.values():
        person = _Person.of(found[0].text)
        claims = _person_claims(person, buckets)
        if len(claims) == 1:
            _join(claims[0], found)
            continue
        if not claims and person.is_one_word and not _is_a_first_name(person.key, buckets):
            company = _chosen(_company_claims(person.key, buckets))
            if company is not None:
                _join(company, found)
                continue
        # A surname without its full name is always checked; an initial when it fits several.
        flagged = not person.is_initial or len(claims) > 1
        buckets.append(_mention(PERSON, found, flagged))


def _is_a_first_name(key: str, buckets: list[_Bucket]) -> bool:
    return any(b.person is not None and b.person.first == key for b in buckets)


# --- Companies ---------------------------------------------------------------------------------


def _companies(findings: list[Finding], buckets: list[_Bucket]) -> dict[str, list[Finding]]:
    """Full company names into groups (``buckets`` grows), single words by their spelling.

    Names with one stem go together, unless they carry different legal forms: then each legal
    form is a company of its own and the stem without a legal form is a group to check.
    """
    by_stem: dict[str, list[tuple[_Company, Finding | _Bucket]]] = defaultdict(list)
    for bucket in buckets:
        if bucket.seed is not None and bucket.type is COMPANY:
            for company in bucket.companies:
                by_stem[company.stem].append((company, bucket))
    mentions: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        company = _Company.of(finding.text)
        if company.is_full:
            by_stem[company.stem].append((company, finding))
        else:
            mentions[normalize(finding.text)].append(finding)
    for stem, members in by_stem.items():
        forms = {company.form for company, _ in members if company.form is not None}
        targets: dict[str | None, _Bucket] = {}
        for company, member in members:
            if isinstance(member, _Bucket):
                targets.setdefault(company.form if len(forms) > 1 else None, member)
        for company, member in members:
            if isinstance(member, _Bucket):
                continue
            slot = company.form if len(forms) > 1 else None
            target = targets.get(slot)
            if target is None:
                names = {stem} if len(forms) <= 1 else set()
                target = targets[slot] = _Bucket(COMPANY, names=names)
                target.flagged = len(forms) > 1 and slot is None
                buckets.append(target)
            target.companies.append(company)
            target.add(member)
    return mentions


def _place_companies(mentions: dict[str, list[Finding]], buckets: list[_Bucket]) -> None:
    """Each single word joins the one company it fits, or the one person whose surname it is;
    else it is a group of its own, to check when it fits several companies.
    """
    for key, found in mentions.items():
        claims = _company_claims(key, buckets)
        company = _chosen(claims)
        if company is not None:
            _join(company, found)
            continue
        if not claims:
            people = _person_claims(_Person((found[0].text.strip(),), False), buckets)
            if len(people) == 1:
                _join(people[0], found)
                continue
        bucket = _mention(COMPANY, found, len(claims) > 1)
        bucket.companies.append(_Company.of(found[0].text))
        buckets.append(bucket)


# --- Together ----------------------------------------------------------------------------------


def _strong(bucket: _Bucket) -> bool:
    """Whether a group stands on firm ground: a seed, or a value found with a score that needs no
    check (not the model's guess at a heading or a running header).
    """
    if bucket.seed is not None:
        return True
    scores = [f.score for f in bucket.findings if f.source != "sweep"]
    return not bucket.flagged and bool(scores) and max(scores) >= CHECK_BELOW


def _chosen(claims: list[_Bucket]) -> _Bucket | None:
    """The one group of ``claims`` a company's short form belongs to: the only one, or the only
    strong one among them; None when that leaves more than one, or none.
    """
    if len(claims) == 1:
        return claims[0]
    strong = [bucket for bucket in claims if _strong(bucket)]
    return strong[0] if len(strong) == 1 else None


def _join(bucket: _Bucket, findings: list[Finding]) -> None:
    for finding in findings:
        bucket.add(finding)


def _mention(kind: PlaceholderType, findings: list[Finding], flagged: bool) -> _Bucket:
    bucket = _Bucket(kind, flagged=flagged)
    _join(bucket, findings)
    return bucket


def _derived(form: str, kind: PlaceholderType) -> set[str]:
    """The forms ``variants_of`` derives from ``form``, and for a full name of three words or
    more the initial with the whole surname ("J. van der Berg" of Jane van der Berg).
    """
    if kind is COMPANY:
        name = _without_the(form)
        return variants_of(name, kind) | {name}
    derived = variants_of(form, kind)
    if kind is PERSON:
        person = _Person.of(form)
        if person.is_full and len(person.words) >= 3 and person.words[0][:1].isalpha():
            derived.add(f"{person.words[0][0]}. {' '.join(person.words[1:])}")
    return derived


def _settle_variants(
    buckets: list[_Bucket], text: str, keep: Callable[[str], bool]
) -> list[_Bucket]:
    """Give each group its variants, each variant to one group only (see the module), and
    return the new groups to check for the shared forms that stand in the text on their own.
    """
    own = {bucket: bucket.own() for bucket in buckets}
    owners: dict[str, list[_Bucket]] = defaultdict(list)
    for bucket, keys in own.items():
        for key in keys:
            owners[key].append(bucket)
    seeded = {key for key, found in owners.items() if any(b.seed is not None for b in found)}
    derived: dict[_Bucket, dict[str, set[str]]] = {}
    claimants: dict[str, list[_Bucket]] = defaultdict(list)
    for bucket in buckets:
        if bucket.seed is not None:
            bucket.variants = set(bucket.seed.variants)
            continue
        seen = {f.text for f in bucket.findings}
        bucket.variants = set(seen)
        forms: dict[str, set[str]] = defaultdict(set)
        for form in (form for text_seen in seen for form in _derived(text_seen, bucket.type)):
            if keep(form) and is_searchable(form):
                forms[normalize(form)].add(form)
        derived[bucket] = forms
        for key in forms.keys() - own[bucket]:
            claimants[key].append(bucket)
    shared: dict[str, set[str]] = defaultdict(set)
    shared_type: dict[str, PlaceholderType] = {}
    for bucket, forms in derived.items():
        for key, spellings in forms.items():
            if key in seeded:
                continue  # a seed's variant is the seed's alone
            if key in own[bucket]:
                bucket.variants |= spellings
            elif key in owners:
                continue  # the form is another group's own
            elif _chosen(claimants[key]) is bucket:
                bucket.variants |= spellings
            elif _chosen(claimants[key]) is None:
                shared[key] |= spellings
                shared_type.setdefault(key, bucket.type)
    return _shared_form_groups(buckets, shared, shared_type, text)


def _shared_form_groups(
    buckets: list[_Bucket],
    shared: dict[str, set[str]],
    shared_type: dict[str, PlaceholderType],
    text: str,
) -> list[_Bucket]:
    """A group to check for each shared form that stands in ``text`` outside every finding."""
    taken = Spans(
        [(f.start, f.end) for bucket in buckets for f in bucket.findings]
        + [(p.start, p.end) for p in find_placeholders(text)]
    )
    new = []
    for key in sorted(shared, key=lambda k: (-max(map(len, shared[k])), k)):
        kind = shared_type[key]
        bucket = _Bucket(kind, flagged=True, variants=set(shared[key]))
        for spelling in sorted(shared[key], key=lambda s: (-len(s), s)):
            for start, end in occurrences(text, spelling, taken):
                bucket.add(Finding(kind, start, end, text[start:end], 1.0, "sweep"))
        if bucket.findings:
            bucket.variants |= {f.text for f in bucket.findings}
            new.append(bucket)
    return new


def _canonical(bucket: _Bucket) -> str:
    """The longest form seen (a person's: the longest with a space; a company's without a
    leading "the"), counting a run of spaces as one; of equal length the one not in capitals,
    then the first.
    """
    forms = [f.text for f in sorted(bucket.findings, key=lambda f: f.start)]
    if bucket.type is PERSON and any(len(form.split()) > 1 for form in forms):
        forms = [form for form in forms if len(form.split()) > 1]
    if bucket.type is COMPANY:
        forms = [_without_the(form) for form in forms]
    return max(forms, key=lambda form: (len(" ".join(form.split())), not form.isupper()))


def _needs_check(bucket: _Bucket) -> bool:
    scores = [f.score for f in bucket.findings if f.source != "sweep"]
    return bucket.flagged or (bool(scores) and max(scores) < CHECK_BELOW)


def _group(bucket: _Bucket) -> Group:
    findings = sorted(bucket.findings, key=lambda f: (f.start, f.end))
    if bucket.seed is not None:
        bucket.seed.findings.extend(findings)
        return bucket.seed
    canonical = _canonical(bucket)
    return Group(
        id=uuid.uuid4().hex,
        type=bucket.type,
        canonical=canonical,
        variants=bucket.variants | {canonical},
        findings=findings,
        placeholder="",
        needs_check=_needs_check(bucket),
    )
