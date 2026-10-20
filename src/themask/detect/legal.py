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
after "sayılı" with a legal title (or a known law number), or after an article word ("Article",
"Section", "Art.", "§"). A bare "No. 6698" is never a reference (it may follow "Invoice:",
"Ref:" ...), nor is a number followed by a currency, a unit or a company form ("Law 1500 EUR",
"Act No. 5237 Holdings Ltd"). A bare "6698", "Agreement No. 6698", "Invoice No. 6698", "KvK
12345678" and an amount are not references and stay as they were.

A name found in the document that holds a legal term ("Data Act Ltd", "HGB Bank") makes that
term a name there, not public: ``public_spans`` leaves such spans out.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from themask.textnorm import normalize


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
    # A number followed by one of these (a currency, a unit, a company form or word) is not the
    # number of a law: "Law 1500 EUR", "Act No. 5237 Holdings Ltd".
    not_after_number: frozenset[str]


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
        İş Kanunu, Borçlar Kanunu, Medeni Kanun, Ticaret Kanunu, Ceza Kanunu, Vergi Usul Kanunu,
        Gelir Vergisi Kanunu, Kurumlar Vergisi Kanunu, Katma Değer Vergisi Kanunu,
        Fikir ve Sanat Eserleri Kanunu, Sınai Mülkiyet Kanunu, Tüketicinin Korunması Hakkında Kanun,
        Elektronik Ticaretin Düzenlenmesi Hakkında Kanun
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
    not_after_number=_set(
        """
        EUR, USD, GBP, TRY, TL, CHF, euro, euros, dollar, dollars, pound, pounds, lira, percent,
        shares, share, units, unit, pieces, pcs, days, day, months, month, years, year, hours,
        hour, weeks, week, kg, tons, tonnes, pallets, licences, licenses, users, employees,
        Ltd, Limited, LLC, LLP, Inc, Corp, plc, AG, SA, SAS, SARL, NV, BV, N.V., B.V., GmbH, KG,
        GmbH & Co, A.Ş., AŞ, A.S., Anonim, Holding, Holdings, Group, Bank, Capital, Partners,
        Industries, Trading, Logistics, Services, Solutions, Technologies, Foods, Insurance,
        Şti, Ltd. Şti., Sp. z o.o., S.r.l., Srl, S.p.A., SpA, Pty, Co., Oy, AB, ApS, Kft., Kft,
        s.r.o., SE, Sdn, Pte, Ventures, Systems, Consulting, Investments, Properties, Enterprises
        """
    ),
)

_EU = r"(?:\((?:EU|EC|EEC|EG|EWG|EU/EEA)\)[ \t]*)?"
_NO = r"(?:(?i:no|nr|n°|number|numara)\.?[ \t]*)?"
_NUMBER = r"\d{1,5}(?:/\d{1,4})?(?:/[A-Z]{2,3})?(?![\d]|[.,]\d)"
# Bare, with no cue: a number with a slash and an EU suffix ("95/46/EC"), or after "(EU)".
_EU_NUMBER = r"\d{2,4}/\d{1,4}/(?:EC|EU|EEC|EG|EWG)"
_EU_BRACKET = r"\((?:EU|EC|EEC|EG|EWG)\)[ \t]*" + _NO + r"\d{1,4}/\d{1,4}"


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
    other = _alternation(terms.not_after_number)
    # A number followed by a currency, a unit or a company form is not a law's.
    not_a_law = rf"(?![ \t]*[%€$£]|[ \t]+(?i:{other})(?!\w))"
    # "Law No. 6698", "Act no 5237", "Regulation (EU) 2016/679", "Directive 95/46/EC", "Kanun 6098"
    cue_number = (
        rf"(?:(?:{cue})|(?i:{_alternation(terms.cues)})(?=\.?[ \t]*(?i:no|nr|n°)\b))"
        rf"\.?[ \t]*{_EU}{_NO}{_NUMBER}{not_a_law}{law_title}"
    )
    # "6698 sayılı Kanun", "6098 sayılı Türk Borçlar Kanunu": the number before "sayılı" and a law
    # word or a known title after it; a known law number may also end a sentence. Nothing else is
    # taken for the title, so a name after "sayılı" is never swallowed.
    law_word = r"(?i:kanun\w*|khk|yönetmeli\w*|tüzü\w*|kararname\w*|tebliğ\w*)"
    known = _alternation(terms.known_numbers)
    names = _alternation(terms.names)
    sayili = (
        rf"(?:\d{{2,5}}[ \t]+sayılı(?=[ \t]+(?:{law_word}\b|(?i:{names})(?!\w)))"
        rf"(?:[ \t]+{law_word}\b)?"
        rf"|(?:{known})[ \t]+sayılı(?=[ \t]*(?:[.,;:)]|\Z)))"
    )
    article = _capitalised(terms.article_words)
    abbreviations = _alternation(terms.abbreviations)
    abbreviation = rf"(?-i:{abbreviations})"
    article_number = (
        rf"(?:{abbreviation}[ \t]+)?(?:(?:{article})\.?|§§?)[ \t]*\d{{1,3}}[a-z]?(?:\.\d+)*"
        rf"(?![\d]){not_a_law}(?:[ \t]*\([A-Za-z0-9]{{1,3}}\))*"
        rf"(?:[ \t]+(?:{abbreviation}|(?i:{names})))?"
    )
    standard = (
        r"(?:(?:TS|BS|DIN|NEN|NF|UNE)[ \t]+)?(?:EN[ \t]+)?"
        r"(?:ISO|IEC|EN|DIN|BS|NEN|ASTM|ANSI|IEEE)(?:[/ ](?:IEC|EN|ISO|TS|TR|PAS))*"
        r"[ \t\u00a0]?\d{1,6}(?:[\-:]\d{1,4}|\.\d{1,4}(?!\d))*"
    )
    named = rf"(?i:{names})|{abbreviation}"
    body = f"{article_number}|{cue_number}|{sayili}|{_EU_BRACKET}|{_EU_NUMBER}|{standard}|{named}"
    return re.compile(rf"(?<![\w§])(?:{body})(?![\w])")


_PATTERN = _compile(LEGAL_TERMS)


def legal_spans(text: str) -> list[tuple[int, int]]:
    """The stretches of ``text`` that are references to laws, standards and codes, in order.
    Stretches that touch, or have only blanks between them, are one.
    """
    merged: list[tuple[int, int]] = []
    for match in _PATTERN.finditer(text):
        start, end = match.span()
        if merged and not text[merged[-1][1] : start].strip(" \t\u00a0"):
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def public_spans(text: str, names: Iterable[str] = ()) -> list[tuple[int, int]]:
    """``legal_spans`` without the stretches that are, or are part of, a name found in the
    document (``names``: people and companies, in any form): "Data Act" of "Data Act Ltd (the
    "Data Act")" and "HGB" of "HGB Bank" are the party's, not the law's.
    """
    keys = [_key(name) for name in names]
    spans = legal_spans(text)
    if not keys:
        return spans
    return [(a, b) for a, b in spans if not _is_part_of(_key(text[a:b]), keys)]


def _key(text: str) -> list[str]:
    return [w for w in (normalize(word) for word in re.split(r"[\s/\-]+", text)) if w]


def _is_part_of(short: list[str], names: list[list[str]]) -> bool:
    n = len(short)
    return n > 0 and any(
        name[i : i + n] == short for name in names for i in range(len(name) - n + 1)
    )


@lru_cache(maxsize=4096)
def is_legal_reference(text: str) -> bool:
    """Whether the whole of ``text`` is one legal reference ("GDPR", "Law No. 6698")."""
    stripped = text.strip().strip(",;:.")
    if not stripped:
        return False
    return legal_spans(stripped) == [(0, len(stripped))]
