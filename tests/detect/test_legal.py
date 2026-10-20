"""References to laws, regulations, directives, standards and legal codes are public text: never
hidden, never asked about (D7). A number counts only after a legal-instrument cue; a bare number,
a contract number, a company registration number or an amount stays as it was.
"""

import pytest

from themask.detect.legal import LEGAL_TERMS, is_legal_reference, legal_spans
from themask.detect.lists import CaseLists, UserLists, is_never_hide
from themask.detect.pipeline import CombinedText, analyze

# (sentence, the references in it that must stay visible and unasked)
PUBLIC = [
    ("This complies with Law No. 6698 on the Protection of Personal Data.", ["Law No. 6698"]),
    ("Under Law no. 6698 the Processor shall act.", ["Law no. 6698"]),
    ("It follows Act No. 5237 in full.", ["Act No. 5237"]),
    ("Pursuant to No. 6698 the data is protected.", ["No. 6698"]),
    ("6698 sayılı Kişisel Verilerin Korunması Kanunu hükümleri saklıdır.", ["6698 sayılı"]),
    ("Kanun No. 6098 applies to this Agreement.", ["Kanun No. 6098"]),
    ("Both KVKK and GDPR apply, as does UK GDPR.", ["KVKK", "GDPR", "UK GDPR"]),
    ("It follows Regulation (EU) 2016/679 closely.", ["Regulation (EU) 2016/679"]),
    ("It follows Directive 95/46/EC and Directive (EU) 2016/943.", ["Directive 95/46/EC"]),
    ("It follows Directive (EU) 2016/943 closely.", ["Directive (EU) 2016/943"]),
    ("See 2016/679 for the rules.", ["2016/679"]),
    ("ePrivacy, CCPA, HIPAA, SOX, PSD2 and MiFID II apply.", ["ePrivacy", "CCPA", "HIPAA", "SOX"]),
    ("Certified to ISO 27001 and ISO/IEC 27001:2022.", ["ISO 27001", "ISO/IEC 27001:2022"]),
    ("Certified to TS EN ISO 9001 as well.", ["TS EN ISO 9001"]),
    ("The Standard Contractual Clauses (SCC) apply.", ["Standard Contractual Clauses", "SCC"]),
    ("Liability follows § 823 BGB and BGB § 242.", ["§ 823 BGB", "BGB § 242"]),
    ("Art. 28 GDPR and Article 28(3) and Section 230 govern.", ["Art. 28 GDPR", "Article 28(3)"]),
    (
        "The Turkish Commercial Code and the Turkish Code of Obligations apply.",
        ["Turkish Commercial Code"],
    ),
    (
        "TCK, TBK, TTK and HMK apply, as do 6102 sayılı Kanun and 6098 sayılı Kanun.",
        ["TCK", "TBK", "TTK", "HMK", "6102 sayılı", "6098 sayılı"],
    ),
    (
        "Wet bescherming persoonsgegevens, AVG and Burgerlijk Wetboek.",
        ["Wet bescherming persoonsgegevens", "AVG", "Burgerlijk Wetboek"],
    ),
    (
        "DSGVO, BDSG and HGB gelten; Verordnung (EU) 2016/679, Richtlinie 95/46/EG.",
        ["DSGVO", "BDSG", "HGB", "Verordnung (EU) 2016/679", "Richtlinie 95/46/EG"],
    ),
    ("Yönetmelik No. 30224 and KHK No. 703 apply under Decree No. 703.", ["Decree No. 703"]),
]

# Things that must stay hidden or checked, exactly as before: (sentence, the value)
CONFIDENTIAL = [
    ("Agreement No. 6698 is signed.", "6698"),
    ("Invoice No. 6698 is due.", "6698"),
    ("Order No. 6698 has shipped.", "6698"),
    ("The reference is 6698.", "6698"),
    ("The Supplier is registered under KvK 12345678 in Utrecht.", "12345678"),
    ("Sicil No 123456 applies to the company.", "123456"),
    ("The VKN 1234567890 applies.", "1234567890"),
    ("Please pay EUR 6,698.00 now.", "EUR 6,698.00"),
    ("Please pay to NL91ABNA0417164300 now.", "NL91ABNA0417164300"),
    ("Contract no. 5237 and Purchase Order 6102 apply.", "5237"),
    ("Contract no. 5237 and Purchase Order 6102 apply.", "6102"),
]


def run(engine, sentence):
    a = analyze(
        CombinedText.join([("x", sentence)]), engine, UserLists([], []), CaseLists([], [], set())
    )
    return a, [(f.start, f.end) for g in a.groups for f in g.findings]


@pytest.mark.parametrize(("sentence", "references"), PUBLIC)
def test_a_legal_reference_is_neither_hidden_nor_asked_about(engine, sentence, references):
    _, spans = run(engine, sentence)
    for reference in references:
        start = sentence.index(reference)
        end = start + len(reference)
        assert not [s for s in spans if s[0] < end and start < s[1]], (reference, spans)


@pytest.mark.parametrize(("sentence", "value"), CONFIDENTIAL)
def test_a_confidential_number_with_no_legal_cue_is_still_found(engine, sentence, value):
    _, spans = run(engine, sentence)
    start = sentence.index(value)
    assert any(s[0] <= start and start + len(value) <= s[1] for s in spans), spans


def test_a_confidential_number_beside_a_law_is_still_found(engine):
    text = "Under Law No. 6698 the fee is due to Agreement No. 6698."
    _, spans = run(engine, text)
    law, agreement = text.index("6698"), text.rindex("6698")
    assert not any(s[0] <= law < s[1] for s in spans)
    assert any(s[0] <= agreement < s[1] for s in spans)


def test_the_owners_always_hide_beats_a_legal_reference(engine):
    text = "Under Law No. 6698 it is set."
    a = analyze(
        CombinedText.join([("x", text)]), engine, UserLists(["6698"], []), CaseLists([], [], set())
    )
    assert any(f.text == "6698" for g in a.groups for f in g.findings)


def test_spans_need_a_legal_cue():
    assert legal_spans("The code is 6698.") == []
    assert legal_spans("Invoice No. 6698") == []
    assert legal_spans("Agreement No. 6698") == []
    assert legal_spans("6698 sayılı sözleşme") == []
    text = "Law No. 6698 and GDPR"
    assert [text[a:b] for a, b in legal_spans(text)] == ["Law No. 6698", "GDPR"]


def test_short_abbreviations_are_case_sensitive():
    assert legal_spans("the avg price and tck") == []
    assert legal_spans("the sox rule") == []
    assert [s for s in legal_spans("the gdpr and Kvkk")]  # long ones ignore case


def test_whole_text_check_and_never_hide_list():
    for term in ("GDPR", "KVKK", "Law No. 6698", "ISO/IEC 27001:2022", "Article 28(3)", "HIPAA"):
        assert is_legal_reference(term), term
        assert is_never_hide(term, UserLists([], []), CaseLists([], [], set())), term
    for text in ("6698", "Agreement No. 6698", "Acme GDPR Consulting Ltd", "EUR 6,698.00"):
        assert not is_legal_reference(text), text


def test_the_terms_are_one_data_structure():
    assert "GDPR" in LEGAL_TERMS.names
    assert "SOX" in LEGAL_TERMS.abbreviations
    assert "Law" in LEGAL_TERMS.cues


class _Engine:
    def __init__(self, *found):
        self.found = found

    def analyze(self, text):
        from themask.model import Finding

        return [
            Finding(k, text.index(t), text.index(t) + len(t), t, s, src)
            for k, t, s, src in self.found
        ]


def test_a_finding_larger_than_a_reference_is_kept():
    from themask.model import PlaceholderType

    company = PlaceholderType.COMPANY
    text = "Acme GDPR Consulting Ltd advises under GDPR."
    engine = _Engine((company, "Acme GDPR Consulting Ltd", 0.9, "model"))
    a = analyze(
        CombinedText.join([("x", text)]), engine, UserLists([], []), CaseLists([], [], set())
    )
    assert [f.text for g in a.groups for f in g.findings] == ["Acme GDPR Consulting Ltd"]


def test_a_rule_finding_inside_a_reference_is_kept():
    from themask.model import PlaceholderType

    text = "Under Law No. 6698 it is set."
    engine = _Engine((PlaceholderType.ID, "6698", 0.9, "rule"))
    a = analyze(
        CombinedText.join([("x", text)]), engine, UserLists([], []), CaseLists([], [], set())
    )
    assert [f.text for g in a.groups for f in g.findings] == ["6698"]
