"""References to laws, regulations, directives, standards and legal codes: public text.

A contract cites "Law No. 6698", "GDPR", "6698 sayılı Kanun", "Regulation (EU) 2016/679",
"ISO 27001", "§ 823 BGB". These are never hidden and never asked about, whatever the language
model or the bare-number recogniser takes them for (task D7). ``legal_spans`` finds them in a text;
``is_legal_reference`` tells whether a whole text is one. The pipeline drops a finding of the model
or of a pattern that lies inside such a span; the owner's own always-hide entries still win.

Everything the owner may want to extend is in ``LEGAL_TERMS`` below: add a name, an abbreviation,
a cue word or a law number there and nothing else changes.

A number is part of a reference only after a legal-instrument cue (``cues``: "Law", "Act",
"Kanun", "Regulation", "Directive", "Verordnung", "Richtlinie", "Decree", "Yönetmelik", "KHK" ...),
after "sayılı" with a legal title (or a known law number), after an article word ("Article",
"Section", "Art.", "§"), or as "No. 6698" for a known law number when nothing but a preposition
comes before. A bare "6698", "Agreement No. 6698", "Invoice No. 6698", "KvK 12345678" and an
amount are not references and stay as they were.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class LegalTerms:
    """What counts as a legal reference. Add to these sets to teach the app more."""

    # Names and long abbreviations: matched whatever their case ("gdpr", "Kvkk"), as whole words.
    names: frozenset[str]
    # Short abbreviations that are also ordinary words or other acronyms: matched only as written.
    abbreviations: frozenset[str]
    # Words that make the number after them part of the reference ("Law No. 6698").
    cues: frozenset[str]
    # Words for an article of a law: the number after them is part of the reference.
    article_words: frozenset[str]
    # Law numbers that may stand after a bare "No." or before "sayılı" without a cue.
    known_numbers: frozenset[str]
    # The title that may follow a law number: "Law No. 6698 on the Protection of Personal Data".
    titles: frozenset[str]


def _set(text: str) -> frozenset[str]:
    return frozenset(part.strip() for part in text.split(",") if part.strip())


LEGAL_TERMS = LegalTerms(
    names=_set(
        """
        KVKK, GDPR, UK GDPR, EU GDPR, DSGVO, BDSG, ePrivacy, ePrivacy Directive, CCPA, CPRA,
        HIPAA, PSD2, PSD3, MiFID II, MiFID, MiFIR, NIS2, GLBA, FERPA, COPPA, LGPD, PIPEDA,
        General Data Protection Regulation, Datenschutz-Grundverordnung, Datenschutzgrundverordnung,
        Bundesdatenschutzgesetz, Algemene verordening gegevensbescherming,
        Wet bescherming persoonsgegevens, Uitvoeringswet AVG, Burgerlijk Wetboek,
        Wetboek van Strafrecht, Wetboek van Koophandel, Bürgerliches Gesetzbuch, Handelsgesetzbuch,
        Strafgesetzbuch, Turkish Commercial Code, Turkish Code of Obligations, Turkish Criminal Code,
        Turkish Civil Code, Turkish Code of Civil Procedure, Türk Ticaret Kanunu,
        Türk Borçlar Kanunu, Türk Ceza Kanunu, Türk Medeni Kanunu, Hukuk Muhakemeleri Kanunu,
        Kişisel Verilerin Korunması Kanunu, California Consumer Privacy Act,
        Health Insurance Portability and Accountability Act, Sarbanes-Oxley Act, Sarbanes-Oxley,
        Digital Services Act, Digital Markets Act, Data Act, AI Act,
        Standard Contractual Clauses, Standard Contractual Clause, Model Clauses,
        2016/679, 95/46/EC, 95/46/EG, 2016/943, 2002/58/EC, 2022/2065, 2023/2854, 2024/1689
        """
    ),
    abbreviations=_set(
        "SOX, SCC, SCCs, AVG, TCK, TBK, TTK, HMK, TMK, HGB, BGB, StGB, DORA, UAVG, KHK"
    ),
    cues=_set(
        """
        Law, Act, Kanun, Kanunu, Regulation, Directive, Verordnung, Richtlinie, Decree,
        Decree-Law, Yönetmelik, Yönetmeliği, Tüzük, Tüzüğü, KHK, Kararname, Kararnamesi,
        Tebliğ, Tebliği, Wet, Besluit, Gesetz, Statute, Ordinance
        """
    ),
    article_words=_set(
        "Article, Articles, Art, Section, Sections, Sec, Paragraph, Para, Madde, Md, Artikel, Art."
    ),
    known_numbers=_set(
        "6698, 5237, 6098, 6102, 6100, 5809, 6502, 4857, 5510, 213, 5651, 6563, 3194, 2004, 5549"
    ),
    titles=_set(
        "Protection of Personal Data, Personal Data Protection, Protection of Personal Data Law"
    ),
)

_EU = r"(?:\((?:EU|EC|EEC|EG|EWG|EU/EEA)\)[ \t]*)?"
_NO = r"(?:(?i:no|nr|n°|number|numara)\.?[ \t]*)?"
_NUMBER = r"\d{1,5}(?:/\d{1,4})?(?:/[A-Z]{2,3})?(?![\d]|[.,]\d)"


def _alternation(terms: frozenset[str]) -> str:
    return "|".join(re.escape(t) for t in sorted(terms, key=lambda t: (-len(t), t)))


def _capitalised(terms: frozenset[str]) -> str:
    """The cue words as a contract writes them: capitalised, or in capitals."""
    forms = {t[0].upper() + t[1:] for t in terms} | {t.upper() for t in terms}
    return _alternation(frozenset(forms))


def _compile(terms: LegalTerms) -> re.Pattern[str]:
    title = _alternation(terms.titles)
    law_title = rf"(?:[ \t]+(?:(?i:on|concerning|regarding)[ \t]+)?(?i:the[ \t]+)?(?i:{title}))?"
    cue = _capitalised(terms.cues)
    # "Law No. 6698", "Act no 5237", "Regulation (EU) 2016/679", "Directive 95/46/EC", "Kanun 6098"
    cue_number = (
        rf"(?:(?:{cue})|(?i:{_alternation(terms.cues)})(?=\.?[ \t]*(?i:no|nr|n°)\b))"
        rf"\.?[ \t]*{_EU}{_NO}{_NUMBER}{law_title}"
    )
    # "6698 sayılı Kişisel Verilerin Korunması Kanunu": the number and, when it has one, its title
    end = r"(?i:kanun\w*|khk|yönetmeli\w*|tüzü\w*|kararname\w*|tebliğ\w*)"
    sayili = (
        rf"\d{{2,5}}[ \t]+sayılı(?=[ \t]+(?:[A-ZÇĞİÖŞÜ]\w*[ \t]+){{0,6}}?{end}\b)"
        rf"(?:[ \t]+(?:[A-ZÇĞİÖŞÜ]\w*[ \t]+){{0,6}}?{end})?"
    )
    article = _capitalised(terms.article_words)
    names = _alternation(terms.names)
    abbreviations = _alternation(terms.abbreviations)
    abbreviation = rf"(?-i:{abbreviations})"
    article_number = (
        rf"(?:{abbreviation}[ \t]+)?(?:(?:{article})\.?|§§?)[ \t]*\d+[a-z]?(?:\.\d+)*(?:[ \t]*\([A-Za-z0-9]{{1,3}}\))*"
        rf"(?:[ \t]+(?:{abbreviation}|(?i:{names})))?"
    )
    standard = (
        r"(?:(?:TS|BS|DIN|NEN|NF|UNE)[ \t]+)?(?:EN[ \t]+)?"
        r"(?:ISO|IEC|EN|DIN|BS|NEN|ASTM|ANSI|IEEE)(?:[/ ](?:IEC|EN|ISO|TS|TR|PAS))*"
        r"[ \t ]?\d{1,6}(?:[\-:]\d{1,4}|\.\d{1,4}(?!\d))*"
    )
    named = rf"(?i:{names})|{abbreviation}"
    body = f"{article_number}|{cue_number}|{sayili}|{standard}|{named}"
    return re.compile(rf"(?<![\w§])(?:{body})(?![\w])")


_PATTERN = _compile(LEGAL_TERMS)
_BARE_NO = re.compile(r"(?<![\w])No\.?[ \t]*(?P<n>\d{3,5})(?![\w]|[.,]\d)")
_PREPOSITIONS = frozenset(
    ("under", "pursuant", "to", "per", "by", "of", "with", "and", "or", "the", "in", "see")
    + ("within", "according", "as", "for", "from", "on")
)
_KNOWN_SAYILI = re.compile(r"(?P<n>\d{2,5})[ \t]+sayılı(?![\w])")


def _bare_no_spans(text: str) -> list[tuple[int, int]]:
    """ "No. 6698" for a known law number, when only a preposition (or nothing) stands before it:
    "Agreement No. 6698" is a contract number and is not one.
    """
    spans = []
    for match in _BARE_NO.finditer(text):
        if match["n"] not in LEGAL_TERMS.known_numbers:
            continue
        before = text[: match.start()].rstrip()
        last = re.split(r"\s+", before)[-1].lower() if before else ""
        if not before or last in _PREPOSITIONS or last[-1:] in ",;:(.":
            spans.append(match.span())
    return spans


def _known_sayili_spans(text: str) -> list[tuple[int, int]]:
    """ "6098 sayılı" with a known law number, even without a title after it, unless an ordinary
    lowercase word follows ("6698 sayılı sözleşme" is a contract numbered 6698).
    """
    spans = []
    for match in _KNOWN_SAYILI.finditer(text):
        if match["n"] in LEGAL_TERMS.known_numbers and not re.match(
            r"[ \t]+[a-zçğıöşü]", text[match.end() :]
        ):
            spans.append(match.span())
    return spans


def legal_spans(text: str) -> list[tuple[int, int]]:
    """The stretches of ``text`` that are references to laws, standards and codes, in order."""
    spans = [m.span() for m in _PATTERN.finditer(text)]
    spans += _bare_no_spans(text) + _known_sayili_spans(text)
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


@lru_cache(maxsize=4096)
def is_legal_reference(text: str) -> bool:
    """Whether the whole of ``text`` is one legal reference ("GDPR", "Law No. 6698")."""
    stripped = text.strip().strip(",;:.")
    if not stripped:
        return False
    return legal_spans(stripped) == [(0, len(stripped))]
