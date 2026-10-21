"""Training round 1: Turkish legal forms, IT/service vocabulary, licence counts, public tax rates.

Every sentence is made up. The ``ModelStub`` engine runs the real contract rules and patterns but
puts the language model's findings in by hand, so the tests pin how the pipeline treats them.
"""

import pytest

from themask.detect.contract_rules import find_legal_form_companies
from themask.detect.engine import Engine
from themask.detect.pipeline import CombinedText, analyze
from themask.model import Finding, PlaceholderType
from themask.textnorm import has_legal_form, strip_legal_form

P, C = PlaceholderType.PERSON, PlaceholderType.COMPANY


class ModelStub(Engine):
    """The real rules and patterns; the language model finds exactly ``model`` (type, text)."""

    def __init__(self, *model):
        self.model = model

    def _presidio_findings(self, text):
        found = []
        for kind, needle in self.model:
            start = text.find(needle)
            while start >= 0:
                score = 0.85 if kind is P else 0.6
                found.append(Finding(kind, start, start + len(needle), needle, score, "model"))
                start = text.find(needle, start + 1)
        return found


def groups_of(text, engine, lists):
    a = analyze(CombinedText.join([("x", text)]), engine, lists)
    return [(g.type, sorted({f.text for f in g.findings}), g.enabled) for g in a.groups]


# --- 1. Turkish company forms -------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Acmevolt Teknoloji Anonim Şirketi",
        "ACMEVOLT TEKNOLOJİ ANONİM ŞİRKETİ",
        "ACMEVOLT TEKNOLOJI ANONIM SIRKETI",
        "Acmevolt Teknoloji Anonim Sirketi",
        "Acmevolt Teknoloji A.Ş.",
        "Acmevolt Teknoloji AŞ",
        "Acmevolt Teknoloji A.S.",
        "Acmevolt Gıda Limited Şirketi",
        "Acmevolt Gıda Limited Sirketi",
        "Acmevolt Gıda Ltd. Şti.",
        "Acmevolt Gıda Ltd.Şti.",
        "Acmevolt Gıda Şti.",
        "Acmevolt Kollektif Şirket",
        "Acmevolt Komandit Şirket",
        "Acmevolt Sanayi ve Ticaret A.Ş.",
        "ACMEVOLT SANAYİ VE TİCARET A.Ş.",
        "Acmevolt San. ve Tic. A.Ş.",
        "Acmevolt San. ve Tic. Ltd. Şti.",
    ],
)
def test_turkish_forms_are_legal_forms(name):
    assert has_legal_form(name)
    (found,) = [f for f in find_legal_form_companies(f"Agreement with {name} today.")]
    assert found.text == name


def test_turkish_form_stripped_leaves_the_stem():
    assert strip_legal_form("Acmevolt Teknoloji Anonim Şirketi") == "Acmevolt Teknoloji"
    assert strip_legal_form("ACMEVOLT TEKNOLOJİ ANONİM ŞİRKETİ") == "ACMEVOLT TEKNOLOJİ"


def test_turkish_prose_is_not_a_company():
    assert find_legal_form_companies("Bu bir anonim şirketi değildir.") == []


def test_ve_joins_only_trade_words():
    found = find_legal_form_companies("Acme ve Beta A.Ş. imzaladı.")
    assert [f.text for f in found] == ["Beta A.Ş."]


SPLIT_MODEL = (
    (P, "ACMEVOLT"),
    (P, "ACMEVOLT TEKNOLOJİ ANONİM"),
    (P, "ŞİRKETİ"),
    (C, "ACMEVOLT"),
)
ANNEX = (
    "This Annex is made between ACMEVOLT TEKNOLOJİ ANONİM ŞİRKETİ and ZETAFLOW GLOBAL B.V.\n"
    "Since ACMEVOLT provides the monitoring, the fees are fixed.\n"
    "ACMEVOLT TEKNOLOJİ ANONİM ŞİRKETİ signs below. ZETAFLOW signs too.\n"
)


def test_a_turkish_party_is_one_company_group_even_if_the_model_splits_it(lists):
    result = groups_of(ANNEX, ModelStub(*SPLIT_MODEL), lists)
    assert [g[0] for g in result] == [C, C]  # no PERSON anywhere
    first = result[0]
    assert "ACMEVOLT TEKNOLOJİ ANONİM ŞİRKETİ" in first[1] and "ACMEVOLT" in first[1]
    assert not any("ŞİRKETİ" in t for g in result[1:] for t in g[1])


def test_a_turkish_party_with_the_real_engine(engine, lists):
    result = groups_of(ANNEX, engine, lists)
    assert [g[0] for g in result] == [C, C]


def test_a_short_form_of_a_turkish_name_joins_the_group(lists):
    t = "Acmevolt Teknoloji Anonim Şirketi (the Provider) agrees. Acmevolt Teknoloji will invoice."
    (g,) = groups_of(t, ModelStub(), lists)
    assert g[0] is C and "Acmevolt Teknoloji" in g[1]


def test_turkish_trade_name_mid_sentence_is_one_company(lists):
    t = "Bu sözleşme Borusan Yazılım Sanayi ve Ticaret A.Ş. ile Delta Gıda Ltd. Şti. arasındadır."
    model = ((P, "Borusan Yazılım Sanayi"), (P, "Ticaret A.Ş. ile"))
    result = groups_of(t, ModelStub(*model), lists)
    assert [(g[0], g[1]) for g in result] == [
        (C, ["Borusan Yazılım Sanayi ve Ticaret A.Ş."]),
        (C, ["Delta Gıda Ltd. Şti."]),
    ]
