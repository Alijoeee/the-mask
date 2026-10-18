"""The detection engine: Presidio's analyzer over spaCy's English model, with our recognizers and
the contract rules.

``Engine.analyze`` turns the analyzer's results into ``Finding`` objects. Presidio's entity names
become placeholder types, each finding says whether a pattern, the language model or a contract rule
found it, and findings scored below ``MIN_SCORE`` are dropped. Dates stay visible: so does a number
that lies within one, such as 01.03.2026 read as an Italian phone number.

The contract rules (``contract_rules``) check the language model: a place it finds is an address
only next to an address the rules found ("the laws of the Netherlands" stays visible), unless it is
a short form of a name in the document, which it then is (ruling R21: the footer's "Greystone" for
Greystone Logistics Ltd); a company it finds with neither a legal form nor a rule behind it is
marked for checking; a job title is no name; and a finding never runs from one line into the next.
Overlapping findings are kept, for the analysis pipeline to decide between, except that a rule's
finding replaces the model's on the same span.
"""

from __future__ import annotations

import re
from dataclasses import replace
from importlib import resources
from pathlib import Path

import spacy
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngine, NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    PhoneRecognizer,
    SpacyRecognizer,
    UkNinoRecognizer,
)

from themask.detect.contract_rules import apply_rules, is_contract_wording, is_job_title
from themask.detect.patterns import contract_recognizers
from themask.model import Finding, FindingSource, PlaceholderType
from themask.textnorm import COMMON_WORDS, has_legal_form, normalize, variants_of

# A finding scored below this is too unlikely to show the owner.
MIN_SCORE = 0.3

# A company the language model finds without a legal form and without a contract rule behind it
# keeps at most this score: it is hidden, but marked for the owner to check.
UNCONFIRMED_COMPANY_SCORE = 0.6
# A place the model finds that is a short form of a name in the document (ruling R21) is that name,
# with at most this score: hidden, and marked for checking.
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
# Presidio's DateRecognizer is dropped, so that the date stays visible.
_DATE_SHAPED_TYPES = frozenset(
    {PlaceholderType.PHONE, _ID, PlaceholderType.AMOUNT, PlaceholderType.QUANTITY}
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

# What may end a pattern's match without being part of the value: the end of a sentence, a quote,
# or a bracket that closes one opened before the value ("(see https://acme.example/terms)").
_TRAILING_PUNCTUATION = frozenset(
    ".,;:!?'\"\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
)
_CLOSING_BRACKETS = {")": "(", "]": "[", "}": "{"}

# A place the model finds counts as part of an address the rules found when it overlaps it or is
# at most this many characters away ("Keizersgracht 123" in "Keizersgracht 123, 1015 CJ ...").
_PLACE_GAP = 2
# A part of a model finding that stands on a line of its own needs this many visible characters.
_MIN_PART_CHARACTERS = 2
# A name's first word is one of its short forms when it has this many letters and is not one of
# COMMON_WORDS ("Greystone" of Greystone Logistics Ltd, not "General" of General Supplies Ltd).
_MIN_SHORT_FORM_LETTERS = 4
_COMMON_WORDS_FOLDED = frozenset(word.casefold() for word in COMMON_WORDS)
_LEADING_THE = re.compile(r"\A(?i:the)\s+")


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
            registry=registry, nlp_engine=nlp_engine, supported_languages=["en"]
        )

    def analyze(self, text: str) -> list[Finding]:
        """Every value in ``text`` that may be confidential, in text order.

        The analyzer's findings and the contract rules' are merged as the module docstring says.
        Overlapping findings are kept, for the analysis pipeline to decide between.
        """
        rules, terms = apply_rules(text)
        findings = rules + _checked_by_rules(text, self._presidio_findings(text), rules, terms)
        return sorted(
            (f for f in findings if f.score >= MIN_SCORE), key=lambda f: (f.start, f.end, f.type)
        )

    def _presidio_findings(self, text: str) -> list[Finding]:
        """What Presidio's analyzer finds, as findings; a value found twice is kept once."""
        results = self._analyzer.analyze(text=text, language="en")
        dates = [(r.start, r.end) for r in results if r.entity_type == _DATE]
        best: dict[tuple[PlaceholderType, int, int], Finding] = {}
        for result in results:
            finding = self._finding(text, result)
            if finding is None or _within_a_date(finding, dates):
                continue
            key = (finding.type, finding.start, finding.end)
            if key not in best or finding.score > best[key].score:
                best[key] = finding
        return list(best.values())

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
            if kind is not None:  # the footer's "Greystone" for Greystone Logistics Ltd
                checked.append(
                    replace(part, type=kind, score=min(part.score, SHORT_NAME_PLACE_SCORE))
                )
            continue  # "the laws of the Netherlands", "the courts of Amsterdam"
        checked.append(_marked_if_unconfirmed(part, rules))
    return checked


def _lines_of(text: str, finding: Finding) -> list[Finding]:
    """A model finding cut at its line breaks, keeping each part with at least two visible
    characters that names somebody: the model can swallow the heading on the next line
    ("Northwind Trading B.V.\\nCUSTOMER"), the label of the next line ("...\\nAttention:") or the
    start of a job title ("JANE SMITH\\nManaging").
    """
    if finding.source != "model" or "\n" not in finding.text:
        return [finding]
    parts = []
    offset = finding.start
    for line in finding.text.split("\n"):
        stripped = line.strip()
        start = offset + line.find(stripped)
        end = start + len(stripped)
        offset += len(line) + 1
        visible = sum(not character.isspace() for character in stripped)
        if visible >= _MIN_PART_CHARACTERS and not _names_nobody(text, start, end):
            parts.append(replace(finding, start=start, end=end, text=stripped))
    return parts


def _names_nobody(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]``, a part of a model finding, names nobody: it is made of the
    contract's own words ("CUSTOMER", "Attention", "TERMINATION"), or is a job title, or is part of
    the job title its line holds ("Managing" of "Managing Director"). A name in capitals on a line
    of its own, as a signatory's name stands ("JOHN CARTER"), is a name.
    """
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start : len(text) if line_end < 0 else line_end].strip()
    part = text[start:end]
    return is_contract_wording(part) or is_job_title(part) or is_job_title(line)


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


def _within_a_date(finding: Finding, dates: list[tuple[int, int]]) -> bool:
    """Whether ``finding`` is a number that lies within one of the ``dates`` (start, end)."""
    return finding.type in _DATE_SHAPED_TYPES and any(
        start <= finding.start and finding.end <= end for start, end in dates
    )


def _trimmed(text: str, start: int, end: int) -> tuple[int, int]:
    """The span ``start``-``end`` without white space around it and without trailing punctuation."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and _ends_outside_the_value(text, start, end):
        end -= 1
    return start, end


def _ends_outside_the_value(text: str, start: int, end: int) -> bool:
    """Whether the last character of the span belongs to the sentence rather than to the value."""
    last = text[end - 1]
    if last.isspace() or last in _TRAILING_PUNCTUATION:
        return True
    opening = _CLOSING_BRACKETS.get(last)
    return opening is not None and text.count(opening, start, end) < text.count(last, start, end)
