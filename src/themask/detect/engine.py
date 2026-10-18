"""The detection engine: Presidio's analyzer over spaCy's English model, with our recognizers.

``Engine.analyze`` turns the analyzer's results into ``Finding`` objects. Presidio's entity names
become placeholder types, each finding says whether a pattern or the language model found it, and
findings scored below ``MIN_SCORE`` are dropped. Dates stay visible: so does a number that lies
within one, such as 01.03.2026 read as an Italian phone number. Overlapping findings are all kept:
the analysis pipeline decides between them.
"""

from __future__ import annotations

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

from themask.detect.patterns import contract_recognizers
from themask.model import Finding, FindingSource, PlaceholderType

# A finding scored below this is too unlikely to show the owner.
MIN_SCORE = 0.3

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

        Overlapping findings are all kept, for the analysis pipeline to decide between.
        """
        findings = self._presidio_findings(text)
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
