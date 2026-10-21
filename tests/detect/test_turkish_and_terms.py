"""Training round 1: Turkish legal forms, IT/service vocabulary, licence counts, public tax rates.

Every sentence is made up. The ``ModelStub`` engine runs the real contract rules and patterns but
puts the language model's findings in by hand, so the tests pin how the pipeline treats them.
"""

import pytest

from themask.detect.contract_rules import find_legal_form_companies
from themask.detect.engine import Engine
from themask.detect.lists import CaseLists, UserLists, is_default_term, is_never_hide
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


# --- 2. Generic IT and service terms are not companies ------------------------------------------

GENERIC = [
    "Managed",
    "Managed Cybersecurity Service",
    "Managed Cybersecurity Services",
    "the Managed Cybersecurity Services",
    "Table 1 Operational Services",
    "Table 2 Cybersecurity Products",
    "Installation",
    "SIEM",
    "Shared SOAR",
    "Server Rental Service",
    "EPP",
    "EDR",
    "EBA",
    "NDR",
    "XDR",
    "On-site Support",
    "Integration",
    "Annex 4 - Pricing",
    "Figure 3 Network Overview",
]


@pytest.mark.parametrize("term", GENERIC)
def test_generic_terms_are_never_hide(term):
    assert is_never_hide(term, UserLists([], []), CaseLists([], [], set()))


@pytest.mark.parametrize(
    "name",
    [
        "Managed Services Ltd",
        "Endpoint Security B.V.",
        "Pam",
        "Dam",
        "Annex 3 Holdings Ltd",
        "Kronvolt",
        "Royal Mail",
        "Global Services",
        "Zetaflow Security",
    ],
)
def test_names_and_acronym_lookalikes_are_not_never_hide(name):
    assert not is_never_hide(name, UserLists([], []), CaseLists([], [], set()))
    assert not is_default_term(name)


def test_a_model_guess_of_a_generic_term_is_not_hidden(lists):
    t = (
        "Table 1 Operational Services\nInstallation, SIEM and Shared SOAR are included.\n"
        "Table 2 Cybersecurity Products\nEPP, EDR, EBA, NDR; Server Rental Service.\n"
        "The Managed Cybersecurity Services run all year."
    )
    model = tuple(
        (C, w)
        for w in (
            "Table 1 Operational Services",
            "Installation",
            "SIEM",
            "Shared SOAR",
            "Table 2 Cybersecurity Products",
            "EPP",
            "EDR",
            "EBA",
            "NDR",
            "Server Rental Service",
            "Managed Cybersecurity Services",
            "The Managed Cybersecurity Services",
        )
    )
    assert groups_of(t, ModelStub(*model), lists) == []


def test_a_real_engine_shows_generic_terms_and_hides_the_parties(engine, lists):
    t = (
        "Annex between ACMEVOLT TEKNOLOJİ ANONİM ŞİRKETİ and ZETAFLOW GLOBAL B.V.\n"
        "Table 1 Operational Services\nInstallation\nSIEM\nShared SOAR\nServer Rental Service\n"
        "Table 2 Cybersecurity Products\nEPP\nEDR\nEBA\nNDR\n"
        "The Managed Cybersecurity Services are provided by ACMEVOLT."
    )
    result = groups_of(t, engine, lists)
    assert [g[0] for g in result] == [C, C]
    texts = {x for g in result for x in g[1]}
    assert not texts & {"SIEM", "EPP", "EDR", "Installation", "Shared SOAR", "Managed"}


def test_a_company_with_a_legal_form_of_generic_words_stays_hidden(engine, lists):
    t = "The Customer buys from Managed Services Ltd and Endpoint Security B.V. in March."
    result = groups_of(t, engine, lists)
    assert [(g[0], g[1]) for g in result] == [
        (C, ["Managed Services Ltd"]),
        (C, ["Endpoint Security B.V."]),
    ]


def test_a_common_word_company_still_hidden(lists):
    t = "Royal Mail and Global Services collect the parcels."
    model = ((C, "Royal Mail"), (C, "Global Services"))
    assert [g[1] for g in groups_of(t, ModelStub(*model), lists)] == [
        ["Royal Mail"],
        ["Global Services"],
    ]


# --- 3. Licence and capacity counts are not amounts ---------------------------------------------


def types_and_texts(text, engine, lists):
    return [(t, texts) for t, texts, _ in groups_of(text, engine, lists)]


@pytest.mark.parametrize(
    "line",
    [
        "The suite is sized at 2500 EPS.",
        "SIEM-Foobar Security Suite 2500 EPS is included.",
        "It covers 2,500 users.",
        "It covers 1.500 devices.",
        "It covers 3000 endpoints.",
        "It has 2 000 seats and 4000 nodes.",
        "It has 1200 licences and 1500 licenses.",
        "Logs take 12000 GB.",
        "Logs take 2 TB and 10000 Mbps.",
        "A 5000-user licence is included.",
        "Sized at 3000 FPM.",
    ],
)
def test_a_licence_or_capacity_count_is_shown(line, engine, lists):
    found = [g for g in groups_of(line, engine, lists) if g[0] is PlaceholderType.AMOUNT]
    assert found == []


def test_prices_and_quantities_of_goods_stay_hidden(engine, lists):
    t = (
        "The price is $ 42.000,00 and 60,000.00 $ in total.\n"
        "The buyer orders 10,000 units, 1,200 pallets and 4,500 tonnes.\n"
        "Total price 12000 for the setup.\n"
    )
    result = {x for g in groups_of(t, engine, lists) for x in g[1]}
    assert {"$ 42.000,00", "60,000.00 $", "10,000 units", "1,200 pallets", "4,500 tonnes"} <= result
    assert "12000" in result


# --- 4. Public tax rates are not percentages to hide --------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "All prices exclude 20% VAT.",
        "VAT of 20% VAT applies.",
        "VAT at 14% is added.",
        "VAT rate: 15%.",
        "The VAT (16%) is added.",
        "KDV 18% eklenir.",
        "MwSt 19 % und BTW 21% und TVA 22 % and IVA 23%.",
        "A withholding tax of 11% applies; sales tax at 8% too; 9% withholding.",
        "3 per cent VAT is due.",
    ],
)
def test_a_tax_rate_is_shown(line, engine, lists):
    found = [g for g in groups_of(line, engine, lists) if g[0] is PlaceholderType.PERCENT]
    assert found == []


@pytest.mark.parametrize(
    "line,value",
    [
        ("A 20% discount is given.", "20%"),
        ("Interest of 5% applies, plus VAT.", "5%"),
        ("The commission is 3%.", "3%"),
        ("The VAT-exclusive price carries a 12% fee.", "12%"),
        ("Five (5) per cent discount applies.", "Five (5) per cent"),
    ],
)
def test_other_percentages_stay_hidden(line, value, engine, lists):
    found = [
        x for g in groups_of(line, engine, lists) if g[0] is PlaceholderType.PERCENT for x in g[1]
    ]
    assert found == [value]
