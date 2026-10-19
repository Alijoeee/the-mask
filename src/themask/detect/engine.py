"""The detection engine: Presidio's analyzer over spaCy's English model, with our recognizers and
the contract rules.

``Engine.analyze`` turns the analyzer's results into ``Finding`` objects. Presidio's entity names
become placeholder types, each finding says whether a pattern, the language model or a contract rule
found it, and findings scored below ``MIN_SCORE`` are dropped. Dates stay visible: so does a number
that lies within one, such as 01.03.2026 read as an Italian phone number, or that is a numeric
date itself ("2026.03.01"), unless its label says it is a registration or account number. The
label before a number also decides between a phone number and an ID ("registered under number
...", "telephone ...").

The contract rules (``contract_rules``) check the language model: a place it finds is an address
only next to an address the rules found ("the laws of the Netherlands" stays visible), unless it is
a short form of a name in the document, which it then is (ruling R21: the footer's "Greystone" for
Greystone Logistics Ltd); a company it finds with neither a legal form nor a rule behind it is
marked for checking; a job title is no name; and a finding never runs from one line into the next,
nor across a tab into the next field of a form, nor across the separators of a running header
from one party's name to the other's.
Overlapping findings are kept, for the analysis pipeline to decide between, except that a rule's
finding replaces the model's on the same span.

Each call writes one line to the log: the number of characters, the number of findings and the
seconds it took, never a word of the text (logging_setup.py has the rule).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from importlib import resources
from pathlib import Path

import spacy
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.context_aware_enhancers import LemmaContextAwareEnhancer
from presidio_analyzer.nlp_engine import NlpEngine, NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    NhsRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
    UkNinoRecognizer,
)

from themask.detect.contract_rules import apply_rules, is_contract_wording, is_job_title
from themask.detect.lists import is_default_term
from themask.detect.patterns import (
    AccountNumberRecognizer,
    RegistrationNumberRecognizer,
    contract_recognizers,
)
from themask.model import Finding, FindingSource, PlaceholderType
from themask.textnorm import COMMON_WORDS, has_legal_form, normalize, variants_of

_LOG = logging.getLogger(__name__)

# A finding scored below this is too unlikely to show the owner.
MIN_SCORE = 0.3

# A company the language model finds without a legal form and without a contract rule behind it
# keeps at most this score: it is hidden, but marked for the owner to check.
UNCONFIRMED_COMPANY_SCORE = 0.6
# A place the model finds that is a short form of a name in the document (ruling R21) is that name,
# with at most this score: hidden, and not marked for checking (the pipeline marks scores below 0.7).
SHORT_NAME_PLACE_SCORE = 0.7

# The countries whose phone numbers are found in their national form too ("020 123 4567"); a
# number written with its country code ("+31 20 123 4567") is found whatever its country.
PHONE_REGIONS = (
    "GB",
    "NL",
    "DE",
    "FR",
    "BE",
    "IE",
    "TR",
    "US",
    "ES",
    "IT",
    "CH",
    "AT",
    "DK",
    "SE",
    "NO",
    "PL",
)

_ID = PlaceholderType.ID
_PERSON = PlaceholderType.PERSON
_COMPANY = PlaceholderType.COMPANY
_ADDRESS = PlaceholderType.ADDRESS

# Presidio's entities as placeholder types. Our own recognizers report placeholder types already.
# An entity that is in neither is an identifier of some kind, and becomes an ID.
_PRESIDIO_TYPES = {
    "EMAIL_ADDRESS": PlaceholderType.EMAIL,
    "PHONE_NUMBER": PlaceholderType.PHONE,
    "IBAN_CODE": PlaceholderType.IBAN,
    "CREDIT_CARD": _ID,
    "URL": PlaceholderType.URL,
    "PERSON": PlaceholderType.PERSON,
    "ORGANIZATION": PlaceholderType.COMPANY,
    "LOCATION": PlaceholderType.ADDRESS,
    "US_SSN": _ID,
    "US_PASSPORT": _ID,
    "UK_NHS": _ID,
    "UK_NINO": _ID,
    "US_BANK_NUMBER": _ID,
    "US_DRIVER_LICENSE": _ID,
    "US_ITIN": _ID,
    "CRYPTO": _ID,
    "IP_ADDRESS": _ID,
    "MEDICAL_LICENSE": _ID,
}
_ENTITY_TYPES = {t.value: t for t in PlaceholderType} | _PRESIDIO_TYPES

# Dates and nationalities stay visible.
_DATE = "DATE_TIME"
_DROPPED_ENTITIES = frozenset({_DATE, "NRP"})

# The types a numeric date can pass for: "01.03.2026" is a valid phone number in Italy and
# "2026-03-01" one in Denmark. A finding of one of these types that lies within a date found by
# Presidio's DateRecognizer is dropped, so that the date stays visible, and so is one that is a
# numeric date in a form that recognizer does not know ("2026.03.01", "01-03-26", "01 03 2026").
_DATE_SHAPED_TYPES = frozenset(
    {PlaceholderType.PHONE, _ID, PlaceholderType.AMOUNT, PlaceholderType.QUANTITY}
)
_NUMERIC_DATE = re.compile(
    r"(?P<a>\d{1,2})(?P<sep>[./\- ])(?P<b>\d{1,2})(?P=sep)(?P<year>\d{4}|\d{2})"
    r"|(?P<long_year>\d{4})(?P<sep2>[./\- ])(?P<month>\d{1,2})(?P=sep2)(?P<day>\d{1,2})"
)

# Presidio's recognizers that ours replace: the e-mail and URL recognizers (patterns.py says why)
# and the phone recognizer, which is set up again for PHONE_REGIONS.
_REPLACED_RECOGNIZERS = ("EmailRecognizer", "UrlRecognizer", "PhoneRecognizer")

# Presidio's recognizers the engine does without (ruling R12), each for the reason given. Their
# entities keep their place in _PRESIDIO_TYPES, should one of them come back.
_DROPPED_RECOGNIZERS = (
    "IpRecognizer",  # reads four-level clause numbers (12.3.4.1) as IP addresses
    "UsLicenseRecognizer",  # flags product codes such as A1234 at exactly the 0.3 threshold
    "UsBankRecognizer",  # any 8 to 17 digits near "bank" or "account"; ours finds labelled ones
    "MedicalLicenseRecognizer",  # US DEA numbers, which these contracts do not hold
)

# The recognizer that reports the language model's names, companies and places; every other
# recognizer works with patterns.
_MODEL_RECOGNIZER = SpacyRecognizer.__name__

# What the label before a number calls it beats what else its digits could be. Our recognizers of a
# number after its label ("registered under number", "Account number:") beat a phone reading of the
# same digits: Presidio's phone recognizer takes "number" for its own context word. What they find
# is kept even in the shape of a date ("Company No. 12/2024"). A telephone label beats Presidio's
# NHS reading, which takes the 3-3-4 shape of many national phone numbers ("telephone 013 625
# 5086") for an NHS number.
_LABELLED_NUMBER_RECOGNIZERS = frozenset(
    {RegistrationNumberRecognizer.__name__, AccountNumberRecognizer.__name__}
)
_NHS_RECOGNIZER = NhsRecognizer.__name__
_TELEPHONE_LABEL = re.compile(
    r"\b(?i:telephone|tel|phone|mobile|mob|fax|cell)\b\.?[ \t]*"
    r"(?:(?i:number|no)\b\.?[ \t]*)?[:#]?[ \t]*\Z"
)
# How far before a number its telephone label may begin.
_LABEL_WINDOW = 30

# What may end a pattern's match without being part of the value: the end of a sentence, a quote,
# or a bracket that closes one opened before the value ("(see https://acme.example/terms)").
_TRAILING_PUNCTUATION = frozenset(
    ".,;:!?'\"\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
)
_CLOSING_BRACKETS = {")": "(", "]": "[", "}": "{"}
_OPENING_BRACKETS = {opening: closing for closing, opening in _CLOSING_BRACKETS.items()}

# A place the model finds counts as part of an address the rules found when it overlaps it or is
# at most this many characters away ("Keizersgracht 123" in "Keizersgracht 123, 1015 CJ ...").
_PLACE_GAP = 2
# A part of a model finding that stands on a line of its own needs this many visible characters.
_MIN_PART_CHARACTERS = 2
# What a model finding is cut at: a line break; a tab, which parts the fields of a form; and a
# slash, dash, dot or bar with spaces round it, which parts the names and the title of a running
# header ("Northwind / Thamesgate \N{EM DASH} Supply Agreement", "Confidential \N{MIDDLE DOT}
# Northwind / Thamesgate").
_PART_BREAK = re.compile(
    "[\n\t]|[ \N{NO-BREAK SPACE}]+[/|\N{EM DASH}\N{EN DASH}\N{MIDDLE DOT}\N{BULLET}-]"
    "[ \N{NO-BREAK SPACE}]+"
)
# A name's first word is one of its short forms when it has this many letters and is not one of
# COMMON_WORDS ("Greystone" of Greystone Logistics Ltd, not "General" of General Supplies Ltd).
_MIN_SHORT_FORM_LETTERS = 4
_COMMON_WORDS_FOLDED = frozenset(word.casefold() for word in COMMON_WORDS)
_LEADING_THE = re.compile(r"\A(?i:the)\s+")
# A colon straight after a word: the word labels its line ("Country: Netherlands").
_LABELS_ITS_LINE = re.compile(r"[ \t]*:")
# Up to three words and a colon at the start of a model finding, before its value: "Country:
# Netherlands", "SUPPLIER: Northwind Trading B.V.".
_LEADING_LABEL = re.compile(r"(?:[^\W\d_][\w\-]*[ \t]+){0,2}[^\W\d_][\w\-]*[ \t]*:[ \t]*(?=\S)")
# A salutation before a name: "Dear Smith".
_SALUTATION = re.compile(r"(?i:dear)[ \t]+(?=\S)")
# A label and its value in one part: "BIC: DEUTDEBB".
_LABEL_AND_VALUE = re.compile(r"[^\W\d_][\w\-]*[ \t]*:[ \t]*(?P<value>\S.*)")
# What comes before the place of a law or a court: "the laws of", "the courts of", "court in".
_JURISDICTION_BEFORE = re.compile(
    r"\b(?i:laws?|courts?|tribunals?|jurisdiction|arbitration|seat)[ \t]+(?i:of|in)[ \t]+"
    r"(?i:the[ \t]+)?\Z"
)


class Engine:
    """Finds the confidential values in a text: patterns, checksums and an English language model.

    Loading the language model takes a few seconds, so make one engine and use it for every text.
    """

    def __init__(self, model_name: str = "en_core_web_md") -> None:
        nlp_engine = _nlp_engine(model_name)
        registry = RecognizerRegistry(supported_languages=["en"])
        registry.load_predefined_recognizers(languages=["en"], nlp_engine=nlp_engine)
        for name in _REPLACED_RECOGNIZERS + _DROPPED_RECOGNIZERS:
            registry.remove_recognizer(name)
        registry.add_recognizer(PhoneRecognizer(supported_regions=PHONE_REGIONS))
        # Presidio leaves the UK National Insurance number off by default.
        registry.add_recognizer(UkNinoRecognizer())
        for recognizer in contract_recognizers():
            registry.add_recognizer(recognizer)
        self._analyzer = AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=["en"],
            # A context word counts as a whole word only: Presidio's default also finds it inside
            # another word ("sum" in "assume", "charge" in "discharge", "cc" in "account").
            context_aware_enhancer=LemmaContextAwareEnhancer(context_matching_mode="whole_word"),
        )

    def analyze(self, text: str) -> list[Finding]:
        """Every value in ``text`` that may be confidential, in text order.

        The analyzer's findings and the contract rules' are merged as the module docstring says.
        Overlapping findings are kept, for the analysis pipeline to decide between. The log gets
        one line: the characters, the findings and the seconds, never the text or a value.
        """
        started = time.perf_counter()
        rules, terms = apply_rules(text)
        findings = rules + _checked_by_rules(text, self._presidio_findings(text), rules, terms)
        kept = sorted(
            (f for f in findings if f.score >= MIN_SCORE), key=lambda f: (f.start, f.end, f.type)
        )
        _LOG.info(
            "analyze characters=%d findings=%d seconds=%.2f",
            len(text),
            len(kept),
            time.perf_counter() - started,
        )
        return kept

    def _presidio_findings(self, text: str) -> list[Finding]:
        """What Presidio's analyzer finds, as findings; a value found twice is kept once, and a
        reading of a number that its label contradicts goes (``_read_as_labelled``).
        """
        results = self._analyzer.analyze(text=text, language="en")
        dates = [(r.start, r.end) for r in results if r.entity_type == _DATE]
        best: dict[tuple[PlaceholderType, int, int], tuple[Finding, str]] = {}
        for result in results:
            finding = self._finding(text, result)
            recognizer = str(result.recognition_metadata.get(RecognizerResult.RECOGNIZER_NAME_KEY))
            if finding is None:
                continue
            # A number after its label is what the label says, even in the shape of a date
            # ("Company No. 12/2024").
            labelled = recognizer in _LABELLED_NUMBER_RECOGNIZERS
            if not labelled and _is_a_date(finding, dates):
                continue
            key = (finding.type, finding.start, finding.end)
            if key not in best or finding.score > best[key][0].score:
                best[key] = (finding, recognizer)
        return _read_as_labelled(text, list(best.values()))

    def _finding(self, text: str, result: RecognizerResult) -> Finding | None:
        """``result`` as a finding, or None when its entity stays visible."""
        if result.entity_type in _DROPPED_ENTITIES:
            return None
        placeholder_type = _ENTITY_TYPES.get(result.entity_type, _ID)
        recognizer = result.recognition_metadata.get(RecognizerResult.RECOGNIZER_NAME_KEY)
        source: FindingSource = "model" if recognizer == _MODEL_RECOGNIZER else "pattern"
        start, end = result.start, result.end
        if source == "pattern":
            # The model's spans are whole words; a legal form such as "B.V." keeps its full stop.
            start, end = _trimmed(text, start, end)
            if start == end:
                return None
        return Finding(placeholder_type, start, end, text[start:end], result.score, source)


def _nlp_engine(model_name: str) -> NlpEngine:
    """spaCy's model ``model_name``, set up as nlp_config.yaml says (whatever model it names)."""
    # Presidio downloads a model that is not installed. The MASK never goes online, so it stops here.
    if not (spacy.util.is_package(model_name) or Path(model_name).exists()):
        raise OSError(f"The language model {model_name} is not installed.")
    config = resources.files("themask.detect").joinpath("nlp_config.yaml")
    with resources.as_file(config) as path:
        provider = NlpEngineProvider(conf_file=path)
    provider.nlp_configuration["models"] = [{"lang_code": "en", "model_name": model_name}]
    return provider.create_engine()


def _checked_by_rules(
    text: str, findings: list[Finding], rules: list[Finding], terms: set[str]
) -> list[Finding]:
    """The analyzer's ``findings`` that stand next to the contract ``rules``' findings; ``terms``
    are the document's defined terms.

    A model finding is cut into its lines, and a part that names nobody goes. Then a model finding
    on the same span as a rule's goes (the rule's stands), and so does a job title found as a name.
    A place the model finds counts only as part of an address the rules found, or as the name it is
    a short form of (ruling R21), never as a defined term; any other place goes. A company with
    neither a legal form nor a rule's finding over it is marked for checking.
    """
    rule_spans = {(rule.start, rule.end) for rule in rules}
    addresses = [rule for rule in rules if rule.type == _ADDRESS]
    parts = [
        part
        for finding in findings
        for part in _lines_of(text, finding)
        if not (
            part.source == "model"
            and ((part.start, part.end) in rule_spans or _is_job_title_name(part))
        )
    ]
    defined = {normalize(term) for term in terms}
    short_names = _types_of_short_forms([*rules, *parts], defined)
    checked = []
    for part in parts:
        if part.source == "model" and part.type == _ADDRESS and not _at(part, addresses):
            kind = short_names.get(normalize(_LEADING_THE.sub("", part.text)))
            if kind is not None and not _is_a_jurisdiction(text, part):
                # the footer's "Greystone" for Greystone Logistics Ltd
                checked.append(
                    replace(part, type=kind, score=min(part.score, SHORT_NAME_PLACE_SCORE))
                )
            continue  # "the laws of the Netherlands", "the courts of Amsterdam"
        checked.append(_marked_if_unconfirmed(part, rules))
    return checked


def _lines_of(text: str, finding: Finding) -> list[Finding]:
    """A model finding cut at its line breaks, its tabs and the separators of a running header
    (``_PART_BREAK``), each part without a label it starts with (``_label_end``), keeping each
    part with at least two visible characters that names somebody: the model can swallow the
    heading on the next line ("Northwind Trading B.V.\\nCUSTOMER"), the label of the next line
    ("...\\nAttention:"), the start of a job title ("JANE SMITH\\nManaging"), across a tab the
    next field of a form ("Smith\\tTitle:", ruling R58), a running header whole: both parties
    and the title ("Northwind / Thamesgate - Supply Agreement", with an em dash), a label with its
    value ("Country: Netherlands") and a salutation with the name ("Dear Smith").
    """
    if finding.source != "model":
        return [finding]
    if _PART_BREAK.search(finding.text) is None and not _label_end(finding.text):
        return [finding]
    parts = []
    piece_start = 0
    for piece_end, next_start in [
        *((b.start(), b.end()) for b in _PART_BREAK.finditer(finding.text)),
        (len(finding.text), len(finding.text)),
    ]:
        line = finding.text[piece_start:piece_end]
        stripped = line.strip()
        label = _label_end(stripped)
        start = finding.start + piece_start + line.find(stripped) + label
        stripped = stripped[label:]
        end = start + len(stripped)
        piece_start = next_start
        if label and _is_a_code(stripped):
            continue  # a label with its code: "BIC: DEUTDEBB"
        visible = sum(not character.isspace() for character in stripped)
        if visible >= _MIN_PART_CHARACTERS and not _names_nobody(text, start, end):
            parts.append(replace(finding, start=start, end=end, text=stripped))
    return parts


def _label_end(text: str) -> int:
    """Where the label or salutation that ``text`` starts with ends, with the spaces after it, or
    0 when it starts with none. A label ends in a colon and is made of the contract's own words or
    is a never-hide term ("Country:", "Name:", "SUPPLIER:"); "John Smith: Director" starts with a
    name. A salutation is "Dear" ("Dear Smith").
    """
    salutation = _SALUTATION.match(text)
    if salutation is not None:
        return salutation.end()
    label = _LEADING_LABEL.match(text)
    if label is None:
        return 0
    words = label.group().strip().rstrip(":").strip()
    return label.end() if is_contract_wording(words) or is_default_term(words) else 0


def _names_nobody(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]``, a part of a model finding, names nobody: it is made of the
    contract's own words ("CUSTOMER", "Attention", "SCHEDULE 1"), or is a job title, or part of the
    job title its line holds ("Managing" of "Managing Director"); it is one word that labels its
    line ("Country:", "Bank:"); it is a label with its code ("BIC: DEUTDEBB"); or it is a number or
    a code ("7.5", "DE63100700006745119824"). A name in capitals on a line of its own, as a
    signatory's name stands ("JOHN CARTER"), is a name.
    """
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    part = text[start:end]
    if " " not in part and (_LABELS_ITS_LINE.match(text, end, line_end) or _is_a_number(part)):
        return True
    label = _LABEL_AND_VALUE.fullmatch(part)
    if label is not None and _is_a_code(label["value"]):
        return True
    line = text[line_start:line_end].strip()
    return is_contract_wording(part) or is_job_title(part) or is_job_title(line)


def _is_a_number(text: str) -> bool:
    """Whether ``text`` is a number or a code with digits, no name: no letter at all, or digits
    and no lower-case letter ("7.5", "DE63100700006745119824", "NL91 ABNA 0417 1643 00").
    """
    if not any(character.isalpha() for character in text):
        return True
    has_digit = any(character.isdigit() for character in text)
    return has_digit and not any(character.islower() for character in text)


def _is_a_code(text: str) -> bool:
    """Whether ``text``, the value after a label, is a code: a number, or one word in capitals
    ("BIC: DEUTDEBB"). On a line of its own, a word in capitals may be a name ("ACME").
    """
    return _is_a_number(text) or (" " not in text.strip() and text.isupper())


def _is_a_jurisdiction(text: str, place: Finding) -> bool:
    """Whether ``place`` is the place of a law or a court ("the courts of Frankfurt"), which stays
    visible whatever company shares its name.
    """
    return _JURISDICTION_BEFORE.search(text, max(0, place.start - 40), place.start) is not None


def _types_of_short_forms(findings: list[Finding], defined: set[str]) -> dict[str, PlaceholderType]:
    """The short forms of the people and companies among ``findings``, normalised, with the type
    of the first one that has them: each one's variants ("Greystone" of Greystone Logistics Ltd,
    "H. Field" of Hannah Field), and its first word when that has at least four letters and is not
    one of COMMON_WORDS. The ``defined`` terms (normalised) are no names, nor short forms of one.
    """
    types: dict[str, PlaceholderType] = {}
    for finding in findings:
        if finding.type not in {_PERSON, _COMPANY}:
            continue
        if normalize(_LEADING_THE.sub("", finding.text)) in defined:
            continue  # the model took "the Delivery Point" for a company
        forms = set(variants_of(finding.text, finding.type))
        first = finding.text.split()[0] if finding.text.split() else ""
        letters = sum(character.isalpha() for character in first)
        if letters >= _MIN_SHORT_FORM_LETTERS and first.casefold() not in _COMMON_WORDS_FOLDED:
            forms.add(first)
        for form in forms:
            key = normalize(form)
            if key and key not in defined:
                types.setdefault(key, finding.type)
    return types


def _is_job_title_name(finding: Finding) -> bool:
    """Whether the model took a job title for a name: "Managing Director", "Legal Counsel"."""
    return (
        finding.source == "model"
        and finding.type in {_PERSON, _COMPANY}
        and is_job_title(finding.text)
    )


def _at(place: Finding, addresses: list[Finding]) -> bool:
    """Whether ``place`` overlaps one of the ``addresses`` or is at most _PLACE_GAP away."""
    return any(
        place.start - address.end <= _PLACE_GAP and address.start - place.end <= _PLACE_GAP
        for address in addresses
    )


def _marked_if_unconfirmed(finding: Finding, rules: list[Finding]) -> Finding:
    """``finding``, its score capped when it is a model company that nothing confirms: no legal
    form in it and no rule's finding over it.
    """
    if finding.source != "model" or finding.type != _COMPANY or has_legal_form(finding.text):
        return finding
    if any(rule.start < finding.end and finding.start < rule.end for rule in rules):
        return finding
    return replace(finding, score=min(finding.score, UNCONFIRMED_COMPANY_SCORE))


def _read_as_labelled(text: str, found: list[tuple[Finding, str]]) -> list[Finding]:
    """The findings of ``found`` (each with the name of its recognizer) but the readings of a
    number that the label before it contradicts: a phone number where one of our recognizers read
    the same digits after their label as a registration or account number, and an NHS number
    where a telephone label stands before digits that are a phone number too. The value stays
    hidden either way; only the type it is hidden as changes.
    """
    labelled = {(f.start, f.end) for f, name in found if name in _LABELLED_NUMBER_RECOGNIZERS}
    phones = {(f.start, f.end) for f, _ in found if f.type is PlaceholderType.PHONE}
    kept = []
    for finding, recognizer in found:
        span = (finding.start, finding.end)
        if finding.type is PlaceholderType.PHONE and span in labelled:
            continue
        if (
            recognizer == _NHS_RECOGNIZER
            and span in phones
            and _TELEPHONE_LABEL.search(text, max(0, finding.start - _LABEL_WINDOW), finding.start)
        ):
            continue
        kept.append(finding)
    return kept


def _is_a_date(finding: Finding, dates: list[tuple[int, int]]) -> bool:
    """Whether ``finding`` is a number that is a date: one that lies within one of the ``dates``
    (start, end), or that is a numeric date itself (``_is_a_numeric_date``).
    """
    if finding.type not in _DATE_SHAPED_TYPES:
        return False
    within = any(start <= finding.start and finding.end <= end for start, end in dates)
    return within or _is_a_numeric_date(finding.text)


def _is_a_numeric_date(text: str) -> bool:
    """Whether ``text`` is a date in figures: day and month in either order and then the year, or
    the year first ("01.03.2026", "03/31/26", "2026.03.01"), each part a day, month and year that
    can be. A two-figure year may be any; a four-figure one is from 1900 to 2099.
    """
    parts = _NUMERIC_DATE.fullmatch(text)
    if parts is None:
        return False
    if parts["a"] is not None:
        a, b, year = int(parts["a"]), int(parts["b"]), parts["year"]
        day_and_month = (1 <= a <= 31 and 1 <= b <= 12) or (1 <= a <= 12 and 1 <= b <= 31)
    else:
        month, day, year = int(parts["month"]), int(parts["day"]), parts["long_year"]
        day_and_month = 1 <= month <= 12 and 1 <= day <= 31
    return day_and_month and (len(year) == 2 or 1900 <= int(year) <= 2099)


def _trimmed(text: str, start: int, end: int) -> tuple[int, int]:
    """The span ``start``-``end`` without white space around it, without trailing punctuation,
    and without an opening bracket at its start that it does not close ("(01.03.2026").
    """
    while start < end and (text[start].isspace() or _opens_outside_the_value(text, start, end)):
        start += 1
    while end > start and _ends_outside_the_value(text, start, end):
        end -= 1
    return start, end


def _opens_outside_the_value(text: str, start: int, end: int) -> bool:
    """Whether the first character of the span opens a bracket that the span does not close."""
    closing = _OPENING_BRACKETS.get(text[start])
    return closing is not None and text.count(closing, start, end) < text.count(
        text[start], start, end
    )


def _ends_outside_the_value(text: str, start: int, end: int) -> bool:
    """Whether the last character of the span belongs to the sentence rather than to the value."""
    last = text[end - 1]
    if last.isspace() or last in _TRAILING_PUNCTUATION:
        return True
    opening = _CLOSING_BRACKETS.get(last)
    return opening is not None and text.count(opening, start, end) < text.count(last, start, end)
