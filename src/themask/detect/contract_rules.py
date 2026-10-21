"""Contract-aware rules: the parties, the people who sign, the addresses and the defined terms.

The language model finds names in running text. A contract also names its parties, its signatories
and their addresses in set places, and these rules read those places:

* the parties clause: "BETWEEN: (1) Northwind Trading B.V., ...; and (2) Acme Supplies Ltd, ...";
* a name that ends in a legal form, wherever it is: "Baltic Fasteners GmbH";
* signature and notice blocks: "Name:", "By:", "Signed by", "Attention:", "Attn:", "FAO:";
* addresses: an "Address:" or "Registered office:" line, "whose registered office is at ...", a
  street with a house number, and a postcode with its town.

The rules also collect the defined terms ("the Supplier", "the Buyer"), which stay visible so that
the AI can still read the contract. A term that is a party's short name, as in Acme Supplies Ltd
("Acme"), is a name and not a term: it is found as a name, so that it is hidden too.

Every function is a pure function of the text. Each finding has source "rule".
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass

from themask.model import Finding, PlaceholderType
from themask.textnorm import HONORIFICS, has_legal_form, normalize, strip_legal_form

PERSON = PlaceholderType.PERSON
COMPANY = PlaceholderType.COMPANY
ADDRESS = PlaceholderType.ADDRESS

# How sure each rule is. A name with a legal form is a company wherever it stands; a name in a place
# where contracts put names (the parties clause, a signature or notice block) is nearly as sure.
LEGAL_FORM_SCORE = 0.95
NAME_SCORE = 0.9
# An address after its label or a registered-office phrase; a street with a house number; a postcode
# with its town on its own.
LABELLED_ADDRESS_SCORE = 0.9
STREET_ADDRESS_SCORE = 0.85
POSTCODE_ADDRESS_SCORE = 0.8

# The parties clause is at the start of a contract.
PARTIES_WITHIN = 4000
# A company name has at most this many words before its legal form.
MAX_NAME_WORDS = 6

# --- Vocabulary ----------------------------------------------------------------------------------


def _vocabulary(words: str) -> frozenset[str]:
    """The words of ``words``, a list of words written as one text."""
    return frozenset(words.split())


# The small words of a sentence, which are never part of a name or an address in capitals ("THE",
# "AND"), and the words that start a sentence without being a name ("Accordingly Acme Ltd shall").
_FUNCTION_WORDS = _vocabulary(
    """
    a an the this that these those and or nor but of to in on at by for from with without into onto
    upon under over between among within about after before during since until unless if as such
    each every any all both either neither no not other another its their his her our your my we you
    they he she it who whom whose which what where when whereas while whether than then there here
    thereof hereof herein hereto hereby therein thereto thereby so also only same said shall will
    may must can should would could is are was were be been being has have had do does did
    accordingly additionally alternatively consequently furthermore further however moreover
    nevertheless nonetheless notwithstanding otherwise subject thereafter therefore thus hence
    meanwhile provided save except including following prior pursuant according regarding concerning
    dear please see note per via
    """
)
# The words that label a line of a signature, notice or bank details block.
_LABEL_WORDS = _vocabulary(
    """
    name title date signature signed sign executed witness address tel telephone phone fax mobile
    email e-mail website web contact position role attention attn fao iban bic swift vat
    """
)
# The parties' roles and the document's own words: defined terms, never names.
_ROLE_WORDS = _vocabulary(
    """
    agreement contract deed schedule schedules annex annexes appendix appendices exhibit clause
    clauses section sections article articles paragraph recital recitals background definitions
    interpretation supplier suppliers buyer buyers customer customers seller sellers purchaser
    purchasers client clients contractor subcontractor licensor licensee provider processor
    sub-processor controller party parties agent distributor vendor lessor lessee landlord tenant
    employer employee employees consultant lender borrower guarantor recipient discloser beneficiary
    affiliate affiliates goods
    """
)
_MONTHS_AND_DAYS = _vocabulary(
    """
    january february march april may june july august september october november december monday
    tuesday wednesday thursday friday saturday sunday
    """
)
_COUNTRIES = _vocabulary(
    """
    england wales scotland ireland britain kingdom uk gb netherlands holland germany deutschland
    france belgium luxembourg spain portugal italy switzerland austria denmark sweden norway finland
    iceland poland czechia czech slovakia hungary romania bulgaria greece croatia slovenia serbia
    estonia latvia lithuania malta cyprus turkey türkiye usa america canada mexico brazil argentina
    chile china japan korea india singapore australia zealand africa egypt morocco israel emirates
    uae qatar europe eu eea
    """
)
# The words of a country's name in an address: "the Netherlands", "United Kingdom", "United States
# of America", "Czech Republic".
_COUNTRY_WORDS = _COUNTRIES | _vocabulary("the of united states republic federal")
_CURRENCIES = _vocabulary(
    """
    euro euros eur pound pounds gbp sterling dollar dollars usd franc francs chf lira liras yen jpy
    yuan renminbi cny rupee rupees krona kronor krone kroner zloty
    """
)
# Words that never start or continue a name read after a label ("Name: Jane Smith Date: ...").
# Months and days are names there ("Name: April Jones"); before a legal form they are not, and in
# the parties clause neither are countries, currencies and "the Company" ("made between Monday and
# Friday", "between England and Wales", "(1) The Company").
_NOT_IN_A_NAME = _FUNCTION_WORDS | _LABEL_WORDS | _ROLE_WORDS
_NOT_IN_A_COMPANY = _NOT_IN_A_NAME | _MONTHS_AND_DAYS
_NOT_A_PARTY = _NOT_IN_A_COMPANY | _COUNTRIES | _CURRENCIES | frozenset({"company", "companies"})

# The words of a contract's own headings ("TERMINATION", "GOVERNING LAW") and titles ("LOGISTICS
# SERVICES AGREEMENT", "NON-DISCLOSURE AGREEMENT"): with the roles and the labels, the words a
# part of a model finding may consist of and still name nobody.
_HEADING_WORDS = _vocabulary(
    """
    operative provisions agreed terms term termination duration commencement renewal expiry notices
    notice payment payments price prices pricing charges charge fees fee invoicing invoices costs
    expenses taxes tax rebates discounts delivery deliveries supply products services scope
    specification specifications quality warranty warranties representations liability limitation
    indemnity indemnities insurance confidentiality intellectual property data protection privacy
    security audit audits compliance force majeure assignment subcontracting general miscellaneous
    governing law jurisdiction disputes dispute resolution arbitration execution signatures contents
    index key personnel contacts validity variation variations amendment amendments waiver severance
    severability entire counterparts remedies rights obligations responsibilities performance levels
    credits reports reporting meetings governance records forecasts orders ordering acceptance risk
    ownership retention packaging labelling transport shipping storage inspection testing training
    support maintenance hosting access staff non-solicitation competition exclusivity survival
    effect consequences return materials processing transfers breach breaches remedy part parts
    attachment attachments date dates period periods effective completion closing exchange purpose
    purposes logistics non-disclosure and of the for to in on &
    """
)
_CONTRACT_WORDS = _ROLE_WORDS | _LABEL_WORDS | _HEADING_WORDS
_CONNECTING_WORDS = frozenset({"and", "of", "the", "for", "to", "in", "on", "&"})

# Small words inside a name: "Van der Valk Hotels B.V.", "Jane van der Berg", "Banco de Sabadell".
_NAME_PARTICLES = _vocabulary(
    """
    van der den de del della di da du la le von zu ter ten bin al el y
    """
)
_HONORIFIC_KEYS = frozenset(normalize(honorific) for honorific in HONORIFICS)

# "ve" ("and") joins the two trade words of a Turkish company name: "Sanayi ve Ticaret A.Ş.", "San.
# ve Tic. Ltd. Şti.". Only between these words (compared by normalize, so "Ticaret" and "TİCARET"
# are one): "Acme ve Beta A.Ş." is two names.
_TURKISH_TRADE_WORDS = frozenset(
    normalize(word)
    for word in """
    Sanayi San Ticaret Tic Turizm İnşaat Insaat Taahhüt Pazarlama Dış Dis Mühendislik Danışmanlık
    """.split()
)

# Job titles and departments: a "Name:" or "Attention:" line that holds one names nobody. A title is
# made of these words only, with at least one of the first kind ("Head of Sales", "Legal Counsel").
_JOB_TITLE_NOUNS = _vocabulary(
    """
    director directors officer officers manager managers head counsel secretary president chairman
    chairwoman chairperson chair ceo cfo coo cto cio cmo cpo cso dpo md vp evp svp gm treasurer
    controller lead leader representative signatory attorney solicitor lawyer notary accountant
    auditor consultant adviser advisor administrator coordinator specialist engineer analyst
    assistant associate clerk owner founder proprietor trustee executive department team division
    """
)
_JOB_TITLE_WORDS = _JOB_TITLE_NOUNS | _vocabulary(
    """
    managing general legal chief senior junior deputy vice acting interim group global regional
    country area national international sales purchasing procurement finance financial operating
    operations technology technical information marketing commercial business development account
    accounts key customer client supply chain logistics quality compliance privacy data protection
    risk audit internal external human resources hr it company corporate contracts contract project
    programme program product products service services site plant facility facilities office
    warehouse transport category buyer authorised authorized duly board partner partners member
    members of and the for in &
    """
)

# Legal forms that are also English words. "SE", "AB", "AS" and "Co" are legal forms only after a
# name in ordinary case ("Siemens SE", "Smith & Co"): in a heading in capitals they are words ("THE
# GOODS AS DESCRIBED"). "LIMITED" between capitals is a word too ("PRODUCT LIMITED WARRANTY").
_SHORT_FORMS = frozenset({"se", "ab", "as", "co"})
_WORD_FORMS = frozenset({"limited", "incorporated", "corporation"})
# A legal form written as a word is part of a term when one of these words follows it in capitals:
# "UK Corporation Tax", "the Product Limited Warranty".
_TERM_AFTER_A_WORD_FORM = frozenset({"tax", "taxes", "warranty", "warranties", "guarantee"})
# "KG" after one of these words is a weight in kilograms, as a packing table heads its columns
# ("NET WEIGHT KG", "Max Load KG"), not the German legal form.
_BEFORE_KILOGRAMS = frozenset(
    {"weight", "net", "gross", "tare", "mass", "load", "payload", "capacity", "max", "min"}
    | {"maximum", "minimum", "total", "per", "in"}
)

# --- Words ---------------------------------------------------------------------------------------

# A word: letters and digits, and the marks that stand inside names, abbreviations and numbers.
_WORD = re.compile(r"[\w&'\N{RIGHT SINGLE QUOTATION MARK}./\-]+")
# Marks that a word does not start or end with: quotes, dashes and slashes ('Buyer', -, /).
_EDGE_MARKS = "'\N{RIGHT SINGLE QUOTATION MARK}-/"
_POSSESSIVE = re.compile(r"['\N{RIGHT SINGLE QUOTATION MARK}][sS]\Z")
# The spaces that may stand between the words of one name; a tab or a line break never does.
_SPACES = frozenset(" \N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}\N{THIN SPACE}")


@dataclass(frozen=True)
class _Word:
    text: str
    start: int
    end: int


def _core(word: str) -> str:
    """``word`` without a possessive "'s": "Acme's" gives "Acme"."""
    return _POSSESSIVE.sub("", word)


def _letters(word: str) -> str:
    return "".join(character for character in word if character.isalpha())


class _Document:
    """A text and its words, read once for all the rules."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.words: list[_Word] = []
        for match in _WORD.finditer(text):
            start, end = match.span()
            while start < end and text[start] in _EDGE_MARKS + ".":
                start += 1
            while end > start and text[end - 1] in _EDGE_MARKS:
                end -= 1
            if start < end:
                self.words.append(_Word(text[start:end], start, end))
        self._starts = [word.start for word in self.words]
        # _legal_form_length for each word it has been asked about: the rules ask often.
        self.legal_forms: dict[int, int] = {}

    def __len__(self) -> int:
        return len(self.words)

    def word(self, i: int) -> str:
        return self.words[i].text

    def first_word_from(self, offset: int) -> int:
        """The index of the first word that starts at ``offset`` or later (len(self) if none)."""
        return bisect_left(self._starts, offset)

    def gap(self, i: int) -> str:
        """The text between word ``i - 1`` and word ``i``."""
        before = self.words[i - 1].end if i > 0 else 0
        return self.text[before : self.words[i].start]

    def joined(self, i: int, *, comma: bool = False) -> bool:
        """Whether word ``i`` follows word ``i - 1`` with only spaces between: on one line, with no
        tab and no punctuation. With ``comma``, a comma straight after word ``i - 1`` is allowed.
        """
        if not 0 < i < len(self.words):
            return False
        gap = self.gap(i)
        if comma and gap.startswith(","):
            gap = gap[1:]
        return bool(gap) and all(character in _SPACES for character in gap)

    def rest_of_line(self, offset: int) -> str:
        end = self.text.find("\n", offset)
        return self.text[offset : len(self.text) if end < 0 else end]


# --- Names ---------------------------------------------------------------------------------------


def _is_name_word(word: str, stop: frozenset[str]) -> bool:
    """Whether ``word`` can be a word of a name: capitalised, with a letter, and not in ``stop``."""
    core = _core(word).rstrip(".")
    return bool(core) and core[0].isupper() and bool(_letters(core)) and core.casefold() not in stop


def _is_honorific(word: str) -> bool:
    return normalize(word) in _HONORIFIC_KEYS


def _written_as_a_legal_form(doc: _Document, i: int, count: int) -> bool:
    """Whether words ``i`` to ``i + count - 1``, a legal form by spelling, are one in running text.

    In lower case only "plc" is ("ltd", "kg" and "limited" are words); see also _SHORT_FORMS,
    _TERM_AFTER_A_WORD_FORM and _BEFORE_KILOGRAMS.
    """
    form = _core(doc.text[doc.words[i].start : doc.words[i + count - 1].end])
    key = normalize(form)
    if form.islower():
        return key == "plc"
    if key == "kg" and doc.joined(i) and _core(doc.word(i - 1)).casefold() in _BEFORE_KILOGRAMS:
        return False
    following = i + count
    goes_on = doc.joined(following)  # a word follows on the same line
    next_word = _core(doc.word(following)).rstrip(".,;:") if goes_on else ""
    if key in _WORD_FORMS and _is_a_term_word(next_word):
        return False  # "Corporation Tax"
    after_capitals = doc.joined(i, comma=True) and _core(doc.word(i - 1)).isupper()
    if key in _SHORT_FORMS and not any(mark in form for mark in "./"):
        return not after_capitals and (form.isupper() or form == "Co")
    if key in _WORD_FORMS and after_capitals and goes_on:
        word = _core(doc.word(following))
        return not (word.isupper() and not has_legal_form(word))
    return True


def _is_a_term_word(word: str) -> bool:
    """Whether ``word``, after a legal form written as a word, makes a term with it: one of
    _TERM_AFTER_A_WORD_FORM in capitals ("Corporation Tax"). In lower case it follows the company
    ("Acme Corporation warranty claims").
    """
    return word[:1].isupper() and word.casefold() in _TERM_AFTER_A_WORD_FORM


def _legal_form_length(doc: _Document, i: int) -> int:
    """How many words from word ``i`` on make up a legal form in running text: 0, 1 or 2."""
    length = doc.legal_forms.get(i)
    if length is None:
        length = doc.legal_forms[i] = _legal_form_words_at(doc, i)
    return length


def _legal_form_words_at(doc: _Document, i: int) -> int:
    if i + 1 < len(doc) and doc.joined(i + 1):
        pair = _core(doc.text[doc.words[i].start : doc.words[i + 1].end])
        if (
            has_legal_form(pair)
            and not strip_legal_form(pair)
            and _written_as_a_legal_form(doc, i, 2)
        ):
            return 2
    if has_legal_form(_core(doc.word(i))) and _written_as_a_legal_form(doc, i, 1):
        return 1
    return 0


def _last_legal_form_word(doc: _Document, last: int) -> int:
    """The last word of a legal form that ends at word ``last`` and may go on ("GmbH & Co. KG")."""
    while doc.joined(last + 1):
        following = last + 1
        if doc.word(following) == "&" and doc.joined(following + 1):
            length = _legal_form_length(doc, following + 1)
            if not length:
                break
            last = following + length
        else:
            length = _legal_form_length(doc, following)
            if not length:
                break
            last = following + length - 1
    return last


def _sentence_goes_on(doc: _Document, offset: int) -> bool:
    """Whether the sentence goes on after ``offset``, so that a full stop there is not its end."""
    rest = doc.rest_of_line(offset).lstrip("".join(_SPACES))
    return bool(rest) and not rest[0].isupper() and rest[0] != "\t"


def _name_end(doc: _Document, last: int, *, legal_form: bool) -> int:
    """Where a name whose last word is word ``last`` ends.

    A possessive "'s" is not part of it. A full stop is, when it belongs to an initial ("J."), a
    legal form written with full stops ("B.V."), or a legal form in the middle of a sentence ("Acme
    Ltd. shall"); a full stop that ends the sentence is not ("We buy from Acme Ltd.").
    """
    word = doc.words[last]
    core = _core(word.text)
    end = word.start + len(core)
    if not core.endswith("."):
        return end
    bare = core.rstrip(".")
    if legal_form:
        keep = "." in bare or _sentence_goes_on(doc, end)
    else:
        keep = len(bare) == 1
    return end if keep else word.start + len(bare)


@dataclass(frozen=True)
class _Name:
    start: int
    end: int
    words: tuple[str, ...]  # the words of the name, without honorifics and legal form
    honorific: bool
    legal_form: bool


def _joins_forward(doc: _Document, j: int, stop: frozenset[str]) -> bool:
    """Whether word ``j`` (an "&", an "and" or a particle) joins the words of a name, read on."""
    following = j + 1
    if not doc.joined(following):
        return False
    word = doc.word(j).casefold()
    if word == "&":
        return _is_name_word(doc.word(following), stop) or _legal_form_length(doc, following) > 0
    if word == "and":
        # "Smith and Co." and "Marlowe Print and Packaging Ltd": one name word, then a legal form.
        if normalize(doc.word(following)) == "co" and _legal_form_length(doc, following):
            return True
        return (
            _is_name_word(doc.word(following), stop)
            and doc.joined(following + 1)
            and _legal_form_length(doc, following + 1) > 0
        )
    if word in _NAME_PARTICLES:
        return _is_name_word(doc.word(following), stop) or doc.word(following) in _NAME_PARTICLES
    if word == "ve":
        return _between_trade_words(doc, j)
    return False


def _between_trade_words(doc: _Document, j: int) -> bool:
    """Whether the "ve" at word ``j`` stands between two Turkish trade words ("Sanayi ve Ticaret")."""
    return (
        0 < j < len(doc) - 1
        and doc.joined(j)
        and doc.joined(j + 1)
        and normalize(_core(doc.word(j - 1))) in _TURKISH_TRADE_WORDS
        and normalize(_core(doc.word(j + 1))) in _TURKISH_TRADE_WORDS
    )


def _read_name(doc: _Document, i: int, stop: frozenset[str] = _NOT_IN_A_NAME) -> _Name | None:
    """The name that starts at word ``i``: honorifics, name words and maybe a legal form, on one
    line. None when word ``i`` does not start a name.
    """
    n = len(doc)
    j = i
    honorific = False
    while j + 1 < n and _is_honorific(doc.word(j)) and doc.joined(j + 1):
        honorific, j = True, j + 1
    words: list[str] = []
    last = j
    legal_form = False
    while j < n and len(words) < MAX_NAME_WORDS:
        length = _legal_form_length(doc, j) if words else 0
        # "Acme, Inc." is one name; "Acme, a company" is not.
        if j > i and not doc.joined(j) and not (length and doc.joined(j, comma=True)):
            break
        if length:
            last, legal_form = _last_legal_form_word(doc, j + length - 1), True
            break
        word = doc.word(j)
        if _is_name_word(word, stop):
            words.append(_core(word).rstrip("."))
            last = j
            if _POSSESSIVE.search(word):
                break
        elif not ((words or honorific) and _joins_forward(doc, j, stop)):
            break  # "Mevr. van der Berg": a particle may follow an honorific
        j += 1
    if not words:
        return None
    end = _name_end(doc, last, legal_form=legal_form)
    return _Name(doc.words[i].start, end, tuple(words), honorific, legal_form)


def _joins_backward(doc: _Document, j: int, words: int, form: int) -> bool:
    """Whether word ``j`` (an "&", an "and" or a particle) joins the words of a company name read
    backward from its legal form at word ``form``, ``words`` name words having been read so far.
    """
    word = doc.word(j).casefold()
    if word == "ve":
        return words > 0 and _between_trade_words(doc, j)
    if words == 0:  # straight before the legal form: only "Smith & Co." and "Smith and Co."
        if not (word in {"&", "and"} and normalize(doc.word(form)) == "co"):
            return False
    elif word == "and":
        if words != 1:  # "Marlowe Print and Packaging Ltd", not "Acme and Northwind Trading B.V."
            return False
    elif word != "&" and word not in _NAME_PARTICLES:
        return False
    before = j - 1
    return (
        doc.joined(j)
        and _is_name_word(doc.word(before), _NOT_IN_A_COMPANY)
        and not _legal_form_length(doc, before)
    )


def _company_start(doc: _Document, form: int) -> int | None:
    """The first word of the company name that ends in the legal form at word ``form``."""
    if not doc.joined(form, comma=True):
        return None
    first = None
    words = 0
    j = form - 1
    while j >= 0 and words < MAX_NAME_WORDS:
        word = doc.word(j)
        name_word = (
            _is_name_word(word, _NOT_IN_A_COMPANY)
            and not _POSSESSIVE.search(word)
            and not _legal_form_length(doc, j)
        )
        if name_word:
            first, words = j, words + 1
        elif not _joins_backward(doc, j, words, form):
            break
        if not doc.joined(j):
            break
        j -= 1
    return first


def _finding(doc: _Document, kind: PlaceholderType, start: int, end: int, score: float) -> Finding:
    return Finding(kind, start, end, doc.text[start:end], score, "rule")


def _legal_form_companies(doc: _Document) -> list[Finding]:
    findings = []
    i = 0
    while i < len(doc):
        length = _legal_form_length(doc, i)
        first = _company_start(doc, i) if length else None
        if first is None:
            i += 1
            continue
        last = _last_legal_form_word(doc, i + length - 1)
        end = _name_end(doc, last, legal_form=True)
        findings.append(_finding(doc, COMPANY, doc.words[first].start, end, LEGAL_FORM_SCORE))
        i = last + 1
    return findings


def is_job_title(text: str) -> bool:
    """Whether ``text`` is a job title or a department and no name: "Managing Director", "CEO",
    "Head of Sales", "Legal Counsel", "Legal Department"; not "Jane Smith" or "Laura Head".
    """
    words = [word.casefold().strip(".,") for word in text.split()]
    return (
        bool(words)
        and all(word in _JOB_TITLE_WORDS for word in words)
        and any(word in _JOB_TITLE_NOUNS for word in words)
    )


# A reference after a heading word: "SCHEDULE 1", "EXHIBIT A", "ANNEX II", "Clause 4.2".
_REFERENCE = re.compile(r"\d{1,3}(?:\.\d{1,3})*[a-z]?|[a-z]|[ivxlc]{1,6}")
_DASHES = frozenset("-\N{EN DASH}\N{EM DASH}")


def is_contract_wording(text: str) -> bool:
    """Whether ``text`` is made of the contract's own words and names nobody: a role ("SUPPLIER",
    "the Buyer"), a heading ("TERMINATION", "GOVERNING LAW", "SCHEDULE 1", "EXHIBIT A") or a label
    ("Attention", "IBAN"). "JOHN CARTER" and "Northwind" are names.
    """
    words = [word.casefold().strip(".,:;()") for word in text.split()]
    words = [word for word in words if word and word not in _DASHES]
    for index, word in enumerate(words):
        reference = index > 0 and words[index - 1] in _CONTRACT_WORDS and _REFERENCE.fullmatch(word)
        if word not in _CONTRACT_WORDS and not reference:
            return False
    return any(word in _CONTRACT_WORDS and word not in _CONNECTING_WORDS for word in words)


def _name_finding(doc: _Document, name: _Name, kind: PlaceholderType) -> Finding:
    score = LEGAL_FORM_SCORE if name.legal_form else NAME_SCORE
    return _finding(doc, COMPANY if name.legal_form else kind, name.start, name.end, score)


# --- The parties clause --------------------------------------------------------------------------

# "BETWEEN", "Between:" at the start of a line, "made ... between", and a "PARTIES" heading.
_PARTIES_START = re.compile(
    r"\bBETWEEN\b|^[ \t]*Between\b|\b(?i:between)[ \t]*:"
    r"|\b(?i:made|entered[ \t]+into|concluded|executed)\b[^.\n]{0,60}?\b(?i:between)\b"
    r"|^[ \t]*(?i:parties)[ \t]*:?[ \t]*$",
    re.MULTILINE,
)
# What follows the parties clause.
_PARTIES_END = re.compile(
    r"^[ \t]*(?i:whereas|background|recitals|introduction|preamble|it[ \t]+is[ \t]+"
    r"(?:hereby[ \t]+)?agreed|now[ ,]+(?:it[ \t]+is|therefore)|agreed[ \t]+terms|operative"
    r"[ \t]+provisions|the[ \t]+parties[ \t]+agree|(?:1\.?|article[ \t]+1|clause[ \t]+1)[ \t.]+"
    r"(?:definitions|interpretation))\b",
    re.MULTILINE,
)
_PARTIES_LENGTH = 3000
# Where a party's name may begin on a line: after "(1)", "(b)" or "1." at its start, after "(2)"
# anywhere, and after the "and" that ends the previous party.
_PARTY_MARKER = re.compile(
    r"^[ \t]*(?:\(?(?:\d{1,2}|[A-Za-z]|[ivxIVX]{1,4})[.)])[ \t]+"
    r"|(?<=\s)\((?:\d{1,2}|[A-Za-z]|[ivxIVX]{1,4})\)[ \t]+"
    r"|(?:[;,)]|^)[ \t]*(?i:and)\b[ \t]*",
    re.MULTILINE,
)
_SKIP_TO_NAME = re.compile(r"[ \t:]*(?:\(?(?:\d{1,2}|[A-Za-z]|[ivxIVX]{1,4})[.)][ \t]+)?")
# A heading's number: "1.", "2.1", "10".
_HEADING_NUMBER = re.compile(r"[ \t]*\d{1,3}(?:\.\d{1,3})*\.?[ \t]+")
# What tells that a party with no legal form and no honorific is a person.
_PERSON_PARTY = re.compile(
    r"[ \t]*,?[ \t]*(?i:of[ \t]+\d|an[ \t]+individual|born\b|residing|resident[ \t]+(?:at|in)"
    r"|a[ \t]+sole[ \t]+trader)"
)
_AND_NEXT_PARTY = re.compile(r"[ \t]+(?i:and)[ \t]+")
# The parties of a list: "Northwind Trading, Glenmore Freight and Kestrel Analytics".
_LIST_COMMA = re.compile(r"[ \t]*,[ \t]*(?!(?i:and)\b)")
_LIST_END = re.compile(r"[ \t]*,?[ \t]*(?i:and)[ \t]+")
# How a line ends when the next one starts with a party: "BETWEEN:", "...(the "Supplier"); and".
_ENDS_BEFORE_A_PARTY = re.compile(r"(?:[:;,]|\b(?i:and))\Z")
# How a line ends when it ends a party's description, so that the next line is not part of it.
_ENDS_A_PARTY = re.compile(
    r"(?:[;.)\"\N{RIGHT DOUBLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}]|;[ \t]*(?i:and))\Z"
)
# A party's number: "(1)", "1." or "1)". Recitals are lettered: "(A)" is no party's number.
_PARTY_NUMBER = re.compile(r"\(?\d{1,2}[.)][ \t]+|(?i:and)\b")
# A party's number in brackets, straight before its name: "(1) ", "(2) THE ".
_PARTY_NUMBER_BEFORE = re.compile(r"\(\d{1,2}\)[ \t]+(?:(?i:the)[ \t]+)?\Z")
# A bracket that defines a short name: (the "Supplier"), ("Buyer"), (each a "Party").
_DEFINING_BRACKET = (
    r"\([ \t]*(?i:(?:the|each[ \t]+an?|together[ \t]+the|hereinafter\b[^()\n]{0,40}?)[ \t]+)?"
    r"[\"\N{LEFT DOUBLE QUOTATION MARK}\N{LEFT SINGLE QUOTATION MARK}']"
)
_DEFINED_AFTER = re.compile(r"[ \t]*" + _DEFINING_BRACKET)
# What, straight after a name, shows that it is a party: a description of a company or a person
# ("a company registered in", "whose registered office", "of 12 Mill Lane", "an individual"), or
# a bracket that defines its short name.
_PARTY_DESCRIPTION = re.compile(
    r"[ \t]*,?[ \t]*(?:(?i:(?:a|an)[ \t]+(?:(?:private|public)[ \t]+)?(?:limited[ \t]+"
    r"(?:liability[ \t]+)?)?(?:company|corporation|partnership|individual|sole[ \t]+trader)\b"
    r"|incorporated\b|registered[ \t]+(?:in|under|at|with|office|number|address)\b"
    r"|(?:established|organi[sz]ed)[ \t]+(?:in|under)\b|whose[ \t]+(?:registered|principal)\b"
    r"|(?:having|with)[ \t]+(?:its[ \t]+)?(?:registered|principal)\b|of[ \t]+\d|residing\b"
    r"|resident[ \t]+(?:at|in)\b|born\b|hereinafter\b"
    r"|\([ \t]*(?:company|registration|registered)[ \t]+(?:number|no)\b)|" + _DEFINING_BRACKET + ")"
)


def _is_heading_line(line: str) -> bool:
    """Whether ``line`` is a heading in capitals, such as "1. PRODUCTS", rather than a party."""
    if line.lstrip().startswith("("):
        return False  # "(1) ACME SUPPLIES; and" is a party
    number = _HEADING_NUMBER.match(line)
    heading = line[number.end() if number else 0 :].strip()
    return bool(_letters(heading)) and heading.isupper() and not has_legal_form(heading)


def _party_at(doc: _Document, offset: int, line_end: int) -> _Name | None:
    """The name that begins at ``offset`` (after its number, if any), on its line."""
    skipped = _SKIP_TO_NAME.match(doc.text, offset, line_end)
    if skipped is not None:
        offset = skipped.end()
    i = doc.first_word_from(offset)
    if i >= len(doc) or doc.words[i].start != offset:
        return None
    if doc.word(i).casefold() == "the" and doc.joined(i + 1):
        i += 1  # "(1) THE NORTHWIND GROUP LIMITED"
    name = _read_name(doc, i, _NOT_A_PARTY)
    if name is None or is_job_title(" ".join(name.words)):
        return None
    return name


def _shows_a_party(doc: _Document, name: _Name) -> bool:
    """Whether ``name`` shows that it is a party: a legal form, an honorific, its number in
    brackets before it ("(1) Northwind Trading"), or a description or a defining bracket after it
    ("Northwind Trading, a company registered in", "Northwind Trading (the "Supplier")"). Any other
    name in a parties clause may be a town: "between Kronberg Medical AG, Frankfurt and ...".
    """
    if name.legal_form or name.honorific:
        return True
    if _PARTY_NUMBER_BEFORE.search(doc.text, max(0, name.start - 16), name.start):
        return True
    return _PARTY_DESCRIPTION.match(doc.text, name.end) is not None


def _listed_names(doc: _Document, offset: int, end: int) -> list[_Name]:
    """The names after the first one of a list, from ``offset`` on: ", Glenmore Freight and
    Kestrel Analytics". All of them, or none when the words after the commas are no list of names
    ending in "and" and a name ("Acme Ltd, Amsterdam, the Netherlands").
    """
    names: list[_Name] = []
    while True:
        last = _LIST_END.match(doc.text, offset, end) if names else None
        if last is not None:
            name = _party_at(doc, last.end(), end)
            return [*names, name] if name is not None else []
        comma = _LIST_COMMA.match(doc.text, offset, end)
        name = _party_at(doc, comma.end(), end) if comma else None
        if name is None:
            return []
        names.append(name)
        offset = name.end


def _is_a_list_of_parties(doc: _Document, names: list[_Name]) -> bool:
    """Whether ``names``, a list, names parties: all of them with a legal form, or none of them and
    a bracket after the list that defines them ("(each a "Party")"). A name without a legal form in
    a list of names with one is a town ("Kronberg Medical AG, Frankfurt and Larchfield Foods
    Limited"), and so may a plain list be ("between Frankfurt, Hamburg and Berlin").
    """
    forms = [name.legal_form for name in names]
    if all(forms):
        return True
    return not any(forms) and _DEFINED_AFTER.match(doc.text, names[-1].end) is not None


def _party_finding(doc: _Document, name: _Name) -> Finding:
    person = name.honorific or _PERSON_PARTY.match(doc.text, name.end) is not None
    return _name_finding(doc, name, PERSON if person else COMPANY)


def _parties_on_line(doc: _Document, start: int, end: int, *, at_start: bool) -> list[Finding]:
    """The parties named on the line (or the rest of the line) from ``start`` to ``end``: after
    each of its markers, and at its start too when ``at_start`` (a party is due there).
    """
    markers = [marker.end() for marker in _PARTY_MARKER.finditer(doc.text, start, end)]
    offsets = [start, *markers] if at_start else markers
    findings: list[Finding] = []
    for offset in offsets:
        name = _party_at(doc, offset, end)
        while name is not None:
            listed = _listed_names(doc, name.end, end)
            if listed and _is_a_list_of_parties(doc, [name, *listed]):
                read = [name, *listed]
                findings.extend(_party_finding(doc, member) for member in read)
            else:
                read = [name]
                if _shows_a_party(doc, name):
                    findings.append(_party_finding(doc, name))
            following = _AND_NEXT_PARTY.match(doc.text, read[-1].end, end)
            name = _party_at(doc, following.end(), end) if following else None
    return findings


def _party_follows(doc: _Document, offset: int, limit: int) -> bool:
    """Whether the next line from ``offset`` on that is not blank starts with a party's number."""
    return _PARTY_NUMBER.match(doc.text[offset:limit].lstrip()) is not None


def _parties(doc: _Document) -> list[Finding]:
    """The parties of every parties clause, read line by line.

    A party's name starts after the clause's first word ("BETWEEN:"), after a marker ("(2)"), at
    the start of a line after one that ends in "and", ";", "," or ":" or is just "AND", and after
    the commas of a list, and it must show that it is a party (see _shows_a_party). The clause ends
    with the line of the last party (one that ends in a full stop with no party's number after it),
    at the first line that names no party and goes on no party's description, or at a heading.
    """
    findings = []
    for start in _PARTIES_START.finditer(doc.text, 0, PARTIES_WITHIN):
        offset, limit = start.end(), min(len(doc.text), start.end() + _PARTIES_LENGTH)
        first_line, party_due, found, previous = True, True, False, ""
        while offset < limit:
            end = doc.text.find("\n", offset, limit)
            end = limit if end < 0 else end
            line = doc.text[offset:end]
            content = line.strip()
            if content.casefold() == "and":
                party_due = True  # "(1) ...\nAND\n(2) ..."
            elif content:
                if not first_line and (_PARTIES_END.match(line) or _is_heading_line(line)):
                    break
                parties = _parties_on_line(doc, offset, end, at_start=party_due)
                goes_on = found and not _ENDS_A_PARTY.search(previous)  # a soft line break
                if not (parties or first_line or goes_on or _PARTY_MARKER.match(line)) and (
                    found or not _ENDS_BEFORE_A_PARTY.search(content)
                ):
                    break  # the clause is over
                findings.extend(parties)
                found = found or bool(parties)
                if parties and content.endswith(".") and not _party_follows(doc, end, limit):
                    break  # the last party
                party_due = _ENDS_BEFORE_A_PARTY.search(content) is not None
                previous = content
            offset, first_line = end + 1, False
    return findings


# --- Signature and notice blocks -----------------------------------------------------------------

# A label at the start of a line or of a table cell, then the name: "Name:", "Printed name:", "By:",
# "Attention:", "Attn.", "FAO:"; or, anywhere, "Signed by" and "For the attention of".
_NAME_LABEL = re.compile(
    r"(?:^|(?<=\t))[ \t]*(?i:(?:(?:full|print|printed)[ \t]+)?name(?:[ \t]+of[ \t]+signatory)?"
    r"[ \t]*:|by[ \t]*:|(?:attention|attn|fao)[ \t]*[:.])"
    r"|\b(?i:signed[ \t]+by|for[ \t]+the[ \t]+attention[ \t]+of)\b[ \t]*:?",
    re.MULTILINE,
)
# What a blank to be filled in looks like: "By: ______".
_BLANK = re.compile(r"[ \t_.\N{EN DASH}\-]*\Z")
# What stands between two names on one line: "Mr John Carter, Head of Sales" or "... and Ms Doe".
_NEXT_NAME = re.compile(r"[ \t]*(?:[,;/&]|\b(?i:and)\b)[ \t]*")
# A label at the start of a line: one to four words and a colon ("Name:", "Registered office:").
# The words must stand apart, so that a long word can be read in one way only (not as four words).
_LABEL_WORD = r"[^\W\d_][\w'\N{RIGHT SINGLE QUOTATION MARK}./-]*"
_LINE_LABEL = re.compile(r"[ \t]*(" + _LABEL_WORD + r"(?:[ \t]+" + _LABEL_WORD + r"){0,3})[ \t]*:")


def _starts_with_a_label(line: str) -> bool:
    """Whether ``line`` starts with a label, as "Name: ..." does; "Büyükdere Caddesi No: 185"
    does not (its colon belongs to the house number).
    """
    label = _LINE_LABEL.match(line)
    return label is not None and label[1].split()[-1].casefold() not in _HOUSE_NUMBER_LABEL


def _value_start(doc: _Document, offset: int) -> tuple[int, bool] | None:
    """The first word after a label ending at ``offset``: on the label's line, or on the next line
    when the label's line holds nothing else (or only a blank) and the next line is no label line
    of its own. True when on the next line.
    """
    rest = doc.rest_of_line(offset)
    if _BLANK.match(rest):
        offset += len(rest) + 1
        i = doc.first_word_from(offset)
        if i >= len(doc) or doc.text[offset : doc.words[i].start].strip(" \t"):
            return None
        if _starts_with_a_label(doc.rest_of_line(offset)):
            return None  # "Address:" then "Name: ..."
        return i, True
    i = doc.first_word_from(offset)
    if i >= len(doc) or doc.text[offset : doc.words[i].start].strip(" \t"):
        return None  # "Name: [Name]"
    return i, False


def _names_after_label(doc: _Document, offset: int) -> list[Finding]:
    start = _value_start(doc, offset)
    if start is None:
        return []
    i, on_next_line = start
    findings = []
    first = True
    while True:
        name = _read_name(doc, i)
        if name is None:
            break
        if on_next_line and doc.rest_of_line(name.end).strip(" \t.,;"):
            break  # a name on the next line must be all of it
        if name.legal_form:
            findings.append(_name_finding(doc, name, COMPANY))
        elif not is_job_title(" ".join(name.words)) and (
            first or name.honorific or len(name.words) >= 2
        ):
            findings.append(_name_finding(doc, name, PERSON))
        first = False
        following = _NEXT_NAME.match(doc.text, name.end)
        if following is None:
            break
        i = doc.first_word_from(following.end())
        if i >= len(doc) or doc.words[i].start != following.end():
            break
    return findings


def _signature_names(doc: _Document) -> list[Finding]:
    return [
        finding
        for label in _NAME_LABEL.finditer(doc.text)
        for finding in _names_after_label(doc, label.end())
    ]


def _titled_names(doc: _Document) -> list[Finding]:
    """Every name after an honorific, wherever it stands: "Mr Bennett", "Ms Lynda Stevens", "Dr.
    Jane Smith". An honorific in capitals needs a name in capitals ("MR JOHN SMITH", not "MS
    Teams").
    """
    findings = []
    i = 0
    while i < len(doc):
        word = doc.word(i)
        name = _read_name(doc, i) if _is_honorific(word) and doc.joined(i + 1) else None
        if name is None or not name.honorific or is_job_title(" ".join(name.words)):
            i += 1
            continue
        if not word.isupper() or all(name_word.isupper() for name_word in name.words):
            findings.append(_name_finding(doc, name, PERSON))
        i = doc.first_word_from(name.end)
    return findings


# --- Addresses -----------------------------------------------------------------------------------

_SP = "[ \N{NO-BREAK SPACE}]"
_HOUSE_NUMBER = r"\d{1,5}[A-Za-z]?(?:" + _SP + r"?[\-\N{EN DASH}/]" + _SP + r"?\d{1,5}[A-Za-z]?)?"
_NAME_WORD_RE = r"[^\W\d_][\w'\N{RIGHT SINGLE QUOTATION MARK}\-]*\.?"

# "10 Downing Street", "12 St John's Road": a house number, one to four words and a street word.
_ENGLISH_STREET_WORDS = (
    "Street|St|Road|Rd|Avenue|Ave|Lane|Drive|Way|Square|Sq|Place|Court|Crescent|Terrace|Close"
    "|Gardens|Grove|Quay|Row|Hill|Parade|Walk|Mews|Boulevard|Wharf|Embankment|Park|Green|Circus"
    "|Yard"
)
_ENGLISH_STREET = re.compile(
    r"(?<![\w.,/])" + _HOUSE_NUMBER + _SP + "+"
    r"(?=(?P<name>(?:" + _NAME_WORD_RE + _SP + "+){1,4})(?:" + _ENGLISH_STREET_WORDS + r")\b)"
)
# "Keizersgracht 123", "Friedrichstraße 12", "Berliner Straße 12", "Hauptstr. 12": a street word
# ends the street's name or follows it, then the house number.
_STREET_SUFFIXES = (
    "straat|weg|laan|plein|gracht|kade|dijk|singel|steeg|markt|stra\N{LATIN SMALL LETTER SHARP S}e"
    "|strasse|str\\.|allee|gasse|platz|damm|ufer"
)
_CONTINENTAL_STREET = re.compile(
    r"(?<![\w\-])[^\W\d_][\w'\N{RIGHT SINGLE QUOTATION MARK}\-]*(?:(?i:" + _STREET_SUFFIXES + ")"
    r"|" + _SP + "(?i:" + _STREET_SUFFIXES + "))" + _SP + "+" + _HOUSE_NUMBER + r"(?!\w)"
)
# "Büyükdere Caddesi No: 185", "Gül Sok. No. 3": the street word, after one to three words.
_TURKISH_STREET_WORD = re.compile(
    r"(?<=" + _SP + r")(?:Caddesi|Cad\.|Cd\.|Sokak|Soka\N{LATIN SMALL LETTER G WITH BREVE}"
    r"\N{LATIN SMALL LETTER DOTLESS I}|Sok\.|Sk\.|Bulvar\N{LATIN SMALL LETTER DOTLESS I}|Blv\.)"
    r"(?=[\s,])"
)
_TURKISH_STREET_NAME_WORDS = 3
# Words before a number that make it a reference into the contract, not a house number.
_REFERENCE_WORDS = _vocabulary(
    """
    clause clauses section sections schedule schedules article articles annex annexes appendix
    exhibit paragraph paragraphs part parts page pages item items rule rules regulation no nr number
    phase stage level tier option
    """
)
# "Unit 5, 12 Mill Lane": what may come before the street.
_UNIT_WORDS = r"(?i:unit|flat|suite|apartment|apt\.?|floor|building|block|room)"
_UNIT = re.compile(_UNIT_WORDS + _SP + r"+\w{1,5}," + _SP + r"*\Z")

# Postcodes. The UK's: "SW1A 2AA". The Netherlands': "1015 CJ" before a town (the letters F, I, O,
# Q, U and Y are not used, nor SA, SD and SS). Germany's, France's and Turkey's: five digits before
# a town. A Dutch or five-digit postcode starts a part of the address (after a comma or a line
# break), so that "2026 EU Member States" and "pay 50000 Euros" are no addresses. After a spaced
# hyphen, or the en dash Word makes of one, a Dutch postcode with its town goes on the address
# before it, as a line of a form may read ("Keizersgracht 123 - 1015 CJ Amsterdam", ruling R97);
# it starts none on its own there ("Page 2 - 1500 KG Steel").
_UK_POSTCODE = re.compile(
    r"(?<![\w-])[A-Z]{1,2}\d[A-Z\d]?" + _SP + r"\d[ABD-HJLNP-UW-Z]{2}(?![\w-])"
)
_NL_POSTCODE = re.compile(
    r"(?<![\w.,-])[1-9]\d{3}" + _SP + r"?(?!SA|SD|SS)[A-EGHJ-NPRTV-XZ]{2}(?![\w-])"
)
_NL_POSTCODE_LETTERS = re.compile(r"[1-9]\d{3} [A-Z]{2}")
_FIVE_DIGIT_POSTCODE = re.compile(r"(?<![\w.,/-])\d{5}(?=" + _SP + ")")
_STARTS_A_PART = re.compile(r"(?:^|[,;:(\t|])[ \N{NO-BREAK SPACE}]*\Z", re.MULTILINE)
_SPACED_DASH = re.compile(_SP + r"+[\-\N{EN DASH}]" + _SP + "+")
# Words after a postcode-like number that are no town.
_NOT_A_TOWN = (
    _FUNCTION_WORDS
    | _ROLE_WORDS
    | _MONTHS_AND_DAYS
    | _vocabulary(
        """
        euro euros eur pound pounds gbp dollar dollars usd franc francs lira liras units unit pieces
        pallets tonnes tons kilograms kilos litres liters boxes cartons items cases
        """
    )
)

# "Address:" and its kin, at the start of a line or of a table cell.
_ADDRESS_LABEL = re.compile(
    r"(?:^|(?<=\t))[ \t]*(?i:registered[ \t]+office(?:[ \t]+address)?|(?:registered|postal|business"
    r"|office|delivery|billing|invoice|invoicing|correspondence|site|home|residential)[ \t]+address"
    r"|address|head[ \t]+office|principal[ \t]+place[ \t]+of[ \t]+business)[ \t]*:[ \t]*",
    re.MULTILINE,
)
# "whose registered office is at", "having its principal place of business at".
_ADDRESS_PHRASE = re.compile(
    r"\b(?i:registered[ \t]+(?:office|address)|principal[ \t]+(?:office|place[ \t]+of[ \t]+"
    r"business)|head[ \t]+office|business[ \t]+address)(?i:[ \t]+address)?(?i:[ \t]+(?:is|being))?"
    r"(?i:[ \t]+(?:situated|located))?(?i:[ \t]+at)?(?:[ \t]*:)?" + _SP + "+"
)
# Lower-case words inside an address: "Frankfurt am Main", "12 rue de la Paix", "c/o".
_ADDRESS_PARTICLES = _vocabulary(
    """
    am an der den dem des de del di da la le les du upon sur van aan op bei im ob ter ten y c/o rue
    avenue boulevard bd chemin quai place allée impasse route via calle
    """
)
# Abbreviations that keep their full stop at the end of an address.
_ADDRESS_ABBREVIATIONS = _vocabulary(
    """
    st rd ave av blvd bd sq pl ct ln dr cres terr cad cd sok sk blv mah no nr str
    """
)
_HOUSE_NUMBER_LABEL = frozenset({"no", "nr"})
# An address has at most this many parts (the words between two commas) and words.
_MAX_ADDRESS_PARTS = 8
# A word of a postcode has at most this many letters and digits ("SW1A", "X285", "10115").
_POSTCODE_WORD_LENGTH = 8
_MAX_ADDRESS_WORDS = 30


def _is_address_word(doc: _Document, k: int, first: bool) -> bool:
    """Whether word ``k`` can be a word of an address; ``first`` when it starts a part of one."""
    word = doc.word(k)
    if word[0].isdecimal():
        return True  # a house number or a postcode
    folded = word.casefold()
    if folded == "the":  # "the Netherlands"
        return first and doc.joined(k + 1) and doc.word(k + 1)[0].isupper()
    if folded in _ADDRESS_PARTICLES:
        return True
    if folded.rstrip(".") in _HOUSE_NUMBER_LABEL:  # "No: 185", "No. 3"
        return k + 1 < len(doc) and doc.word(k + 1)[0].isdecimal()
    if k > 0 and doc.joined(k) and _NL_POSTCODE_LETTERS.fullmatch(f"{doc.word(k - 1)} {word}"):
        return True  # "3044 AS", although "as" is a small word
    if not word[0].isupper() or _core(word).rstrip(".").casefold() in _FUNCTION_WORDS:
        return False
    # A legal form after a name ends a company name, not an address ("1015 CJ" and "3011 AB" are
    # postcodes, "Acme Ltd" is a company).
    return not (
        _legal_form_length(doc, k)
        and doc.joined(k, comma=True)
        and _is_name_word(doc.word(k - 1), _NOT_IN_A_COMPANY)
    )


def _is_address_abbreviation(word: str) -> bool:
    """Whether ``word``, without its full stop, is an address word's abbreviation: "St", "Rd", and
    a German street's name shortened to "str" ("Hauptstr").
    """
    folded = word.casefold()
    return folded in _ADDRESS_ABBREVIATIONS or (folded.endswith("str") and len(folded) > 3)


def _address_joined(doc: _Document, k: int) -> bool:
    """Whether word ``k`` goes on the part of an address that word ``k - 1`` is in."""
    before = doc.word(k - 1)
    gap = doc.gap(k)
    if before.casefold().rstrip(".") in _HOUSE_NUMBER_LABEL and gap.lstrip(" ").startswith(":"):
        gap = gap.replace(":", "", 1) or " "  # "No: 185", "No:185"
    if not (gap and all(character in _SPACES for character in gap)):
        return False
    # A full stop ends the sentence, unless it ends an abbreviation or an initial.
    bare = before.rstrip(".")
    return before == bare or _is_address_abbreviation(bare) or len(_letters(bare)) <= 1


def _address_word_end(doc: _Document, k: int) -> int:
    word = doc.words[k]
    bare = word.text.rstrip(".")
    if _is_address_abbreviation(bare):
        return word.end
    return word.start + len(bare)


def _starts_next_part(doc: _Document, k: int) -> bool:
    """Whether word ``k`` follows a comma and starts the next part of the address, or follows a
    spaced hyphen and starts a Dutch postcode with its town ("Keizersgracht 123 - 1015 CJ
    Amsterdam", ruling R97).
    """
    if not 0 < k < len(doc):
        return False
    gap = doc.gap(k)
    if gap.startswith(",") and all(character in _SPACES for character in gap[1:]):
        return True
    if _SPACED_DASH.fullmatch(gap) is None:
        return False
    postcode = _NL_POSTCODE.match(doc.text, doc.words[k].start)
    return postcode is not None and _town_follows(doc, postcode)


def _is_a_country(doc: _Document, part: list[int]) -> bool:
    """Whether the words ``part`` of an address are its country: "the Netherlands", "Germany",
    "United Kingdom".
    """
    words = [_core(doc.word(k)).rstrip(".").casefold() for k in part]
    return all(word in _COUNTRY_WORDS for word in words) and any(w in _COUNTRIES for w in words)


def _is_a_postcode_part(doc: _Document, k: int) -> bool:
    """Whether the part of an address that starts at word ``k`` is a postcode: one or two short
    words of letters and digits, a digit among them, and no label ("D02 X285", "SW1A 1AA"; not
    "VAT BE0123456789" nor "Attention Finance").
    """
    last = k
    while last - k < 2 and last + 1 < len(doc) and _address_joined(doc, last + 1):
        last += 1
    words = [_core(doc.word(i)) for i in range(k, last + 1)]
    return (
        len(words) <= 2
        and any(character.isdigit() for word in words for character in word)
        and all(word.isalnum() and len(word) <= _POSTCODE_WORD_LENGTH for word in words)
        and not any(word.casefold() in _LABEL_WORDS for word in words)
    )


def _address_end(doc: _Document, k: int) -> int | None:
    """Where the address that starts at word ``k`` ends: after its last part, a part being the
    words up to the next comma. It ends at a bracket, a semicolon, a quote, a tab, a line break, or
    a word that cannot be part of an address ("and", "a company", "VAT number"), after its country
    unless its postcode follows ("..., the Netherlands, Attention Finance"; "..., Ireland, D02
    X285" goes on), and after _MAX_ADDRESS_PARTS parts or _MAX_ADDRESS_WORDS words at most.
    """
    end = None
    limit = min(len(doc), k + _MAX_ADDRESS_WORDS)
    for part_number in range(_MAX_ADDRESS_PARTS):
        j = k
        part: list[int] = []
        complete = True
        while j < limit:
            if j > k and not _address_joined(doc, j):
                break
            if not _is_address_word(doc, j, first=j == k):
                complete = False
                break
            part.append(j)
            j += 1
        while part and doc.word(part[-1]).casefold() in _ADDRESS_PARTICLES:
            part.pop()
            complete = False
        if not part:
            break
        has_digit = any(any(c.isdecimal() for c in doc.word(x)) for x in part)
        if not complete and not (part_number == 0 or has_digit):
            break  # "..., VAT number NL1": not part of the address
        end = _address_word_end(doc, part[-1])
        if not complete or not _starts_next_part(doc, j):
            break
        if _is_a_country(doc, part) and not _is_a_postcode_part(doc, j):
            break  # what follows the country is no part of the address, but its postcode
        k = j
    return end


def _address_value(doc: _Document, offset: int) -> int | None:
    """The first word of the address after a label or phrase that ends at ``offset``, skipping a
    company name before it ("Address: Northwind Trading B.V., Keizersgracht 123, ...").
    """
    start = _value_start(doc, offset)
    if start is None:
        return None
    k = start[0]
    j = k + 1
    while j < len(doc) and doc.joined(j, comma=True):
        length = _legal_form_length(doc, j)
        if length and _is_name_word(doc.word(j - 1), _NOT_IN_A_COMPANY):
            last = _last_legal_form_word(doc, j + length - 1)
            return last + 1 if _starts_next_part(doc, last + 1) else None
        if not doc.joined(j):
            break
        j += 1
    return k


def _is_an_address(doc: _Document, start: int, end: int, terms: frozenset[str]) -> bool:
    """Whether the words after a label or phrase are an address: a number in them, or else none
    of the contract's own words for a place. Those are a word after a small "the" ("Delivery
    Address: the Site"), one of ``terms`` (the defined terms, in lower case), and a word that
    names a party or a part of the contract ("Address: the Supplier's registered office").
    """
    text = doc.text[start:end]
    if any(character.isdecimal() for character in text):
        return True
    if text.startswith("the ") or text.casefold().removeprefix("the ") in terms:
        return False
    words = doc.words[doc.first_word_from(start) : doc.first_word_from(end)]
    return not any(_core(word.text).casefold() in _ROLE_WORDS for word in words)


def _part_start(doc: _Document, k: int) -> int:
    """The first word of the part of an address that word ``k`` is in ("London" in "London SW1A
    2AA"), going back over the words of that part (at most _MAX_ADDRESS_WORDS of them).
    """
    first = max(0, k - _MAX_ADDRESS_WORDS)
    while k > first and _address_joined(doc, k) and _is_address_word(doc, k - 1, first=False):
        k -= 1
    return k


def _with_street_before(doc: _Document, k: int) -> int:
    """Word ``k``, or the first word of the part before it when that part has a house number
    ("Weena 12, 3011 AB Rotterdam", "12 rue de la Paix, 75002 Paris").
    """
    if not _starts_next_part(doc, k):
        return k
    j = k - 1
    if not _is_address_word(doc, j, first=False):
        return k
    j = _part_start(doc, j)
    while doc.word(j).casefold() in _ADDRESS_PARTICLES and j < k - 1:
        j += 1
    has_number = any(any(c.isdecimal() for c in doc.word(x)) for x in range(j, k))
    return j if has_number else k


def _street_anchors(doc: _Document) -> Iterable[int]:
    """The first word of every street with its house number."""
    text = doc.text
    for match in _ENGLISH_STREET.finditer(text):
        before = text[max(0, match.start() - 20) : match.start()].split()
        if not all(word[0].isupper() for word in match["name"].split()):
            continue
        if before and before[-1].casefold().strip(".,:;(") in _REFERENCE_WORDS:
            continue  # "clause 12 High Court"
        unit = _UNIT.search(text, max(0, match.start() - 20), match.start())
        yield doc.first_word_from(unit.start() if unit else match.start())
    for match in _CONTINENTAL_STREET.finditer(text):
        if match.group()[0].isupper():
            yield doc.first_word_from(match.start())
    for match in _TURKISH_STREET_WORD.finditer(text):
        street = doc.first_word_from(match.start())
        k = street
        while (
            street - k < _TURKISH_STREET_NAME_WORDS
            and doc.joined(k)
            and doc.word(k - 1)[0].isupper()
            and _is_address_word(doc, k - 1, first=False)
        ):
            k -= 1
        if k < street:
            yield k


def _town_follows(doc: _Document, postcode: re.Match[str]) -> bool:
    """Whether a town follows ``postcode`` on its line: a capitalised word that is no small word,
    unit, currency or month, nor a code of three capitals at most ("3000 MT", "1500 KG", "2024 UK").
    """
    town = doc.first_word_from(postcode.end())
    if town >= len(doc) or doc.words[town - 1].end != postcode.end() or not doc.joined(town):
        return False
    word = doc.word(town)
    if not word[0].isupper() or _core(word).rstrip(".").casefold() in _NOT_A_TOWN:
        return False
    return not (word.isupper() and len(_letters(word)) <= 3)


def _postcode_anchors(doc: _Document) -> Iterable[int]:
    text = doc.text
    for match in _UK_POSTCODE.finditer(text):
        yield _with_street_before(doc, _part_start(doc, doc.first_word_from(match.start())))
    for pattern in (_NL_POSTCODE, _FIVE_DIGIT_POSTCODE):
        for match in pattern.finditer(text):
            if not _STARTS_A_PART.search(text, max(0, match.start() - 40), match.start()):
                continue
            if _town_follows(doc, match):
                yield _with_street_before(doc, doc.first_word_from(match.start()))


def _addresses(doc: _Document, terms: frozenset[str]) -> list[Finding]:
    """The addresses; ``terms`` are the document's defined terms, in lower case."""
    spans: list[tuple[int, int, float]] = []

    def add(k: int | None, score: float, *, check: bool = False) -> None:
        if k is None or k >= len(doc):
            return
        start = doc.words[k].start
        end = _address_end(doc, k)
        if end is not None and (not check or _is_an_address(doc, start, end, terms)):
            spans.append((start, end, score))

    for label in _ADDRESS_LABEL.finditer(doc.text):
        add(_address_value(doc, label.end()), LABELLED_ADDRESS_SCORE, check=True)
    for phrase in _ADDRESS_PHRASE.finditer(doc.text):
        i = doc.first_word_from(phrase.end())
        if i < len(doc) and doc.words[i].start == phrase.end():
            add(i, LABELLED_ADDRESS_SCORE, check=True)
    for k in _street_anchors(doc):
        add(k, STREET_ADDRESS_SCORE)
    for k in _postcode_anchors(doc):
        add(k, POSTCODE_ADDRESS_SCORE)
    return [_finding(doc, ADDRESS, start, end, score) for start, end, score in _merged(spans)]


def _merged(spans: list[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    """Overlapping spans as one, with the highest of their scores."""
    merged: list[tuple[int, int, float]] = []
    for start, end, score in sorted(spans):
        if merged and start < merged[-1][1]:
            last_start, last_end, last_score = merged[-1]
            merged[-1] = (last_start, max(end, last_end), max(score, last_score))
        else:
            merged.append((start, end, score))
    return merged


# --- Defined terms -------------------------------------------------------------------------------

# A term in quotes: "Supplier", “Supplier”, ‘Supplier’ or 'Supplier'.
_QUOTED = (
    r"(?:\"(?P<q1>[^\"\n]{1,80})\""
    r"|\N{LEFT DOUBLE QUOTATION MARK}(?P<q2>[^\N{RIGHT DOUBLE QUOTATION MARK}\n]{1,80})"
    r"\N{RIGHT DOUBLE QUOTATION MARK}"
    r"|\N{LEFT SINGLE QUOTATION MARK}(?P<q3>[^\N{RIGHT SINGLE QUOTATION MARK}\n]{1,80})"
    r"\N{RIGHT SINGLE QUOTATION MARK}"
    r"|(?<!\w)'(?P<q4>[^'\n]{1,80})'(?!\w))"
)
_QUOTED_TERM = re.compile(_QUOTED)
# A bracket that defines terms: (the "Supplier"), ("Buyer"), (each a "Party" and together the
# "Parties"), (hereinafter referred to as the "Buyer").
_BRACKET = re.compile(r"\(([^()\n]{1,300})\)")
_DEFINING_WORDS = _vocabulary(
    """
    the a an each every together collectively individually jointly severally both and or hereinafter
    hereafter herein below referred to as called also known
    """
)
_HEREINAFTER = re.compile(
    r"\b(?i:hereinafter|hereafter)(?i:[ \t]+(?:referred[ \t]+to[ \t]+as|called|known[ \t]+as))?"
    r"[ \t]*:?[ \t]*(?i:the[ \t]+)?" + _QUOTED
)
# A definitions clause: "Business Day" means ..., 1.1 “Confidential Information” means ..., and a
# definition in the middle of a line: In this Agreement, "Field of Use" means ...
_MEANS = re.compile(
    r"(?:^[ \t]*(?:\(?[0-9a-z]{1,3}(?:\.\d{1,3})*[.)]?[ \t]+)?|(?<=[ \t,;:(]))"
    + _QUOTED
    + r"[ \t]+(?i:means|shall[ \t]+mean|has[ \t]+the[ \t]+meaning|have[ \t]+the[ \t]+meanings?"
    r"|includes|shall[ \t]+include|refers[ \t]+to)\b",
    re.MULTILINE,
)
_LEADING_THE = re.compile(r"(?i:the)[ \t]+")
_MAX_TERM_WORDS = 6


@dataclass(frozen=True)
class _Term:
    text: str
    start: int
    end: int
    # Where the definition begins: its bracket or its "hereinafter". None in a definitions clause
    # ("Business Day" means ...), which never gives a party its short name.
    anchor: int | None


def _quoted_term(match: re.Match[str], anchor: int | None) -> _Term | None:
    group = next(group for group in ("q1", "q2", "q3", "q4") if match[group] is not None)
    start, end = match.span(group)
    text = match.string[start:end]
    the = _LEADING_THE.match(text)
    if the:
        start += the.end()
    text = match.string[start:end].strip()
    start = match.string.index(text, start) if text else start
    if not _letters(text) or len(text.split()) > _MAX_TERM_WORDS:
        return None
    return _Term(text, start, start + len(text), anchor)


def _definitions(doc: _Document) -> list[_Term]:
    """Every term the text defines, where it defines it."""
    text = doc.text
    terms: list[_Term | None] = []
    for bracket in _BRACKET.finditer(text):
        quoted = list(_QUOTED_TERM.finditer(text, bracket.start(1), bracket.end(1)))
        rest = _QUOTED_TERM.sub(" ", bracket[1])
        if quoted and all(w.casefold() in _DEFINING_WORDS for w in re.findall(r"\w+", rest)):
            terms.extend(_quoted_term(match, bracket.start()) for match in quoted)
    terms.extend(_quoted_term(match, match.start()) for match in _HEREINAFTER.finditer(text))
    terms.extend(_quoted_term(match, None) for match in _MEANS.finditer(text))
    unique = {(t.start, t.end): t for t in terms if t is not None}
    return [unique[span] for span in sorted(unique)]


def _initials(words: Iterable[str]) -> str:
    return "".join(word[0] for word in words if word[:1].isalpha()).casefold()


def _short_forms(name: Finding) -> set[str]:
    """The short forms of a name, normalised: Northwind Trading B.V. gives "northwind",
    "northwindtrading" and the initials "nt" and "ntb"; Mr John Carter gives "johncarter", "john"
    and "carter".
    """
    if name.type == PERSON:
        words = [word for word in name.text.split() if not _is_honorific(word)]
        return {normalize(form) for form in (" ".join(words), *words[:1], *words[-1:])}
    words = strip_legal_form(name.text).split()
    forms = {normalize(" ".join(words[:count])) for count in range(1, len(words) + 1)}
    initials = {_initials(words), _initials(name.text.split())}
    return forms | {initial for initial in initials if len(initial) >= 2}


# The end of a party's description: the next party, the first ";" after it, or the first full stop
# that ends a line; at most this many characters after the party's name.
_PARTY_DESCRIPTION_END = re.compile(r";|\.[ \t]*(?:\n|\Z)")
_MAX_DESCRIPTION = 1000
# How far after a name a bracket may stand and still be straight after it.
_STRAIGHT_AFTER = 40


def _descriptions(doc: _Document, parties: list[Finding]) -> list[tuple[Finding, int]]:
    """Each party with the end of its description in the parties clause, which may run on over a
    line break ("(1) Acme Supplies Ltd, a company registered in England,\nwhose registered office
    is at ... ("Acme"); and").
    """
    ordered = sorted(parties, key=lambda party: party.start)
    descriptions = []
    for index, party in enumerate(ordered):
        limit = ordered[index + 1].start if index + 1 < len(ordered) else len(doc.text)
        limit = min(limit, party.end + _MAX_DESCRIPTION)
        end = _PARTY_DESCRIPTION_END.search(doc.text, party.end, limit)
        descriptions.append((party, end.start() if end else limit))
    return descriptions


class _ShortNames:
    """Which defined terms are the short names of the names the rules found.

    A term is a short name of a party when its bracket stands in that party's description ("(1)
    Acme Supplies Ltd, represented by Mr John Carter, its director ("Acme")"), and of any name when
    its bracket stands straight after the name, line breaks included (Acme Supplies Ltd ("Acme"),
    Kestrel Analytics Limited ("KAL")); and it must be one of that name's short forms. Any other
    term is a defined term, even one that shares a word with a name: "Name: Laura Price" and (the
    "Price"), Custom Foods Ltd (the "Customer").
    """

    def __init__(
        self, doc: _Document, names: list[Finding], descriptions: list[tuple[Finding, int]]
    ):
        self.doc = doc
        self.descriptions = descriptions
        self.names = sorted(names, key=lambda name: name.end)
        self.ends = [name.end for name in self.names]

    def type_of(self, term: _Term) -> PlaceholderType | None:
        """The type of the name ``term`` is a short name of, or None when it is a defined term."""
        if term.anchor is None:
            return None
        key = normalize(term.text)
        for owner in self._owners(term.anchor):
            if key in _short_forms(owner):
                return owner.type
        return None

    def _owners(self, anchor: int) -> list[Finding]:
        """The names a definition at ``anchor`` may give a short name to: the party in whose
        description it stands, and the name it stands straight after.
        """
        owners = [party for party, end in self.descriptions if party.end <= anchor < end]
        before = bisect_right(self.ends, anchor) - 1
        if before >= 0:
            name = self.names[before]
            between = self.doc.text[name.end : anchor]
            if len(between) <= _STRAIGHT_AFTER and all(
                word.casefold() in _DEFINING_WORDS for word in re.findall(r"\w+", between)
            ):
                owners.append(name)
        return owners


def _terms_and_short_names(
    doc: _Document,
    names: list[Finding],
    descriptions: list[tuple[Finding, int]],
    definitions: list[_Term],
) -> tuple[set[str], list[Finding]]:
    """The defined terms, and the short names among them as findings of their names' type.
    ``descriptions`` holds the parties with the ends of their descriptions, ``definitions`` the
    terms the text defines.
    """
    index = _ShortNames(doc, names, descriptions)
    terms: set[str] = set()
    short_names: dict[str, list[Finding]] = {}
    for term in definitions:
        kind = index.type_of(term)
        if kind is None:
            terms.add(term.text)
        else:
            short_name = _finding(doc, kind, term.start, term.end, NAME_SCORE)
            short_names.setdefault(term.text, []).append(short_name)
    return terms - short_names.keys(), [f for found in short_names.values() for f in found]


# --- Together -------------------------------------------------------------------------------------


def _in_order(findings: Iterable[Finding]) -> list[Finding]:
    """``findings`` in text order, each span and type once, with the highest score found for it."""
    best: dict[tuple[int, int, PlaceholderType], Finding] = {}
    for finding in findings:
        key = (finding.start, finding.end, finding.type)
        if key not in best or finding.score > best[key].score:
            best[key] = finding
    return [best[key] for key in sorted(best)]


def _names(doc: _Document) -> tuple[list[Finding], list[tuple[Finding, int]]]:
    """The names the rules find, and the parties with the ends of their descriptions."""
    parties = _in_order(_parties(doc))
    names = _in_order(
        [*parties, *_legal_form_companies(doc), *_signature_names(doc), *_titled_names(doc)]
    )
    return names, _descriptions(doc, parties)


def _defined(definitions: list[_Term]) -> frozenset[str]:
    return frozenset(term.text.casefold() for term in definitions)


def find_parties(text: str) -> list[Finding]:
    """The parties named in the parties clause ("BETWEEN: (1) ...; and (2) ..."), which must start
    within the first 4,000 characters. A party with a legal form is a COMPANY (0.95). A name without
    one is a party only when it shows it (its number "(1)" before it, "a company registered in" or
    a defining bracket after it ...): a COMPANY (0.9), or a PERSON with an honorific, "of 12 Mill
    Lane" or "an individual". Months, days, countries, currencies, "the Company" and the town after
    a party ("Kronberg Medical AG, Frankfurt") are no parties.
    """
    return _in_order(_parties(_Document(text)))


def find_legal_form_companies(text: str) -> list[Finding]:
    """Every name of one to six capitalised words that ends in a legal form, as a COMPANY (0.95).

    "Baltic Fasteners GmbH", "Marlowe Print and Packaging Ltd", "Müller & Söhne GmbH & Co. KG".
    The name stops at punctuation, a line break, a small word ("from", "The", "and" before two or
    more words), a role or document word ("Supplier", "Schedule") and a month ("In March Acme Ltd").
    """
    return _in_order(_legal_form_companies(_Document(text)))


def find_signature_blocks(text: str) -> list[Finding]:
    """The names after "Name:", "By:" and "Signed by", and after "Attention:", "Attn:", "FAO:" and
    "For the attention of": a PERSON (0.9), or a COMPANY (0.95) when the name has a legal form.

    A job title is no name ("Attention: Legal Counsel"), and "Title:" lines are not read at all.
    """
    return _in_order(_signature_names(_Document(text)))


def find_addresses(text: str) -> list[Finding]:
    """Postal addresses, as ADDRESS findings.

    An address follows an "Address:" or "Registered office:" label (0.9), a phrase such as "whose
    registered office is at" (0.9), or starts with a street and house number ("10 Downing Street",
    "Keizersgracht 123", "Büyükdere Caddesi No: 185"; 0.85) or a postcode with its town ("1015 CJ
    Amsterdam", "10117 Berlin", "London SW1A 2AA"; 0.8). It runs on over the parts after it, comma
    by comma, to the end of its postcode, town or country, and stops at "(", ";", " and ", a quote
    or a line break. A jurisdiction ("the laws of the Netherlands") is no address, and neither is
    the contract's own word for a place after a label ("Delivery Address: the Site").
    """
    doc = _Document(text)
    return _addresses(doc, _defined(_definitions(doc)))


def find_defined_terms(text: str) -> set[str]:
    """The terms the contract defines: (the "Supplier"), ("Buyer"), (hereinafter "Seller"),
    (each a "Party"), and "Business Day" means ..., in straight or typographic quotes.

    A party's short name, defined after its name, is not a term: Acme Supplies Ltd ("Acme") defines
    no term.
    """
    doc = _Document(text)
    names, descriptions = _names(doc)
    return _terms_and_short_names(doc, names, descriptions, _definitions(doc))[0]


def apply_rules(text: str) -> tuple[list[Finding], set[str]]:
    """All the rules: their findings in text order (each span and type once), and the defined
    terms. Short names of parties are among the findings.
    """
    doc = _Document(text)
    names, descriptions = _names(doc)
    definitions = _definitions(doc)
    terms, short_names = _terms_and_short_names(doc, names, descriptions, definitions)
    addresses = _addresses(doc, _defined(definitions))
    return _in_order([*names, *addresses, *short_names]), terms
