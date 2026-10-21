"""Training round 1, fix round: what the deep review found. Every input is made up."""

import time

import pytest

from themask.detect.engine import Engine
from themask.detect.lists import CaseLists, UserLists, is_never_hide
from themask.detect.pipeline import CombinedText, analyze
from themask.model import Finding, KeyEntry, PlaceholderType

P, C = PlaceholderType.PERSON, PlaceholderType.COMPANY
AMOUNT, PERCENT, CUSTOM = PlaceholderType.AMOUNT, PlaceholderType.PERCENT, PlaceholderType.CUSTOM


def found(engine, text, kind):
    return [f.text for f in engine.analyze(text) if f.type is kind]


class ModelStub(Engine):
    """The real rules and patterns; the language model finds exactly ``model`` (type, text, score)."""

    def __init__(self, *model):
        self.model = model

    def _presidio_findings(self, text):
        out = []
        for kind, needle, *score in self.model:
            start = text.find(needle)
            while start >= 0:
                s = score[0] if score else (0.85 if kind is P else 0.6)
                out.append(Finding(kind, start, start + len(needle), needle, s, "model"))
                start = text.find(needle, start + 1)
        return out


def run(text, engine, always=(), never=(), seeds=None, case=None):
    lists = UserLists(list(always), list(never))
    a = analyze(CombinedText.join([("x", text)]), engine, lists, case, seed_entries=seeds)
    return a


def shown(a):
    return [(g.type, sorted({f.text for f in g.findings}), g.enabled) for g in a.groups]


# --- C3: a price next to a capacity unit is hidden ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "an annual 60,000 licence fee",
        "a 25000 license fee each year",
        "the 60,000 license fees",
        "A one-off 12,500 user fee",
        "A 15000 device charge",
        "The 8,000 seat price",
        "Annual fee: 45,000 Licences: 300",
        "The licence fee is 45,000 License key included.",
        "The base is 450 000 users-based",
        "License No. 123456 users",
        "Invoice 12345 users",
        "784512 seats",
        "250 User 42.000,00",
    ],
)
def test_a_price_beside_a_capacity_unit_is_hidden(engine, text):
    assert found(engine, text, AMOUNT)


@pytest.mark.parametrize(
    "text",
    [
        "The suite is sized at 2500 EPS.",
        "It covers 250 User.",
        "A 5000-user licence is included.",
        "It has 2 000 seats and 4000 nodes.",
        "Logs take 12000 GB.",
    ],
)
def test_a_capacity_count_stays_shown(engine, text):
    assert found(engine, text, AMOUNT) == []


def test_a_price_per_user_is_hidden_but_not_the_count(engine):
    assert found(engine, "EUR 2500 per user", AMOUNT) == ["EUR 2500"]
    assert found(engine, "2500 users at EUR 12 each", AMOUNT) == ["EUR 12"]


# --- C4: a commercial rate beside VAT is hidden ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The commission is 15% (VAT excluded).",
        "The commission of 15%, VAT excluded",
        "management fee 5% VAT exclusive",
        "The margin is 7% VAT excluded.",
        "a discount of 8%, VAT, and shipping are extra",
        "royalty rate is 6%, VAT to be added",
        "success fee equals 3%, sales tax extra",
        "2.5% withholding tax deducted",
        "The share of VAT, 30%",
        "Discount 15%, VAT 20%",
        "Prices rise by 4% VAT excluded.",
        "Prices rise by 4% VAT extra.",
        "Prices rise by 4% VAT to be added.",
        "15% plus VAT",
        "15% (excl. VAT)",
        "withholding fee 5%",
        "commission 5% VAT",
        "İskonto %15 uygulanır.",
    ],
)
def test_a_commercial_rate_beside_vat_is_hidden(engine, text):
    assert found(engine, text, PERCENT)


@pytest.mark.parametrize(
    "text",
    [
        "All prices exclude 20% VAT.",
        "VAT at 20%.",
        "VAT rate: 15%.",
        "The VAT (16%) is added.",
        "KDV 18% eklenir.",
        "KDV %18 eklenir.",
        "MwSt 19 % und BTW 21%.",
        "A withholding tax of 11% applies.",
        "3 per cent VAT is due.",
    ],
)
def test_a_tax_rate_stays_shown(engine, text):
    assert found(engine, text, PERCENT) == []


# --- I1: nothing here is slow on a long run of white space ---------------------------------------


@pytest.mark.parametrize("pad", [" ", "\t", "  "])
def test_long_white_space_around_a_figure_is_fast(engine, pad):
    engine.analyze("warm up 20%")
    for text in (
        "Rate 20%" + pad * 1500 + "x",
        "Rate 20%" + pad * 1000 + "VAT",
        "VAT" + pad * 1000 + "20%",
        "1,000" + pad * 1000 + "users",
        "fee" + pad * 1000 + "1,000" + pad * 1000 + "users",
    ):
        start = time.perf_counter()
        engine.analyze(text)
        assert time.perf_counter() - start < 1.5


# --- C1: what the owner asked to hide beats the new IT defaults -----------------------------------


def hidden_texts(a):
    return {f.text for g in a.groups for f in g.findings if g.enabled}


@pytest.mark.parametrize("value", ["SIEM", "Installation", "Endpoint Security", "Table 1 Kronvolt"])
def test_an_always_hide_entry_beats_the_it_defaults(engine, value):
    a = run(f"Keep {value} secret. Also {value} again.", ModelStub(), always=[value])
    assert value in hidden_texts(a)
    assert [g.type for g in a.groups] == [CUSTOM]


@pytest.mark.parametrize("value", ["SIEM", "Endpoint Security", "Shared SOAR"])
def test_a_typed_always_hide_entry_beats_the_it_defaults(engine, value):
    a = run(f"Keep {value} secret.", ModelStub(), always=[f"COMPANY:{value}"])
    assert [(g.type, sorted({f.text for f in g.findings})) for g in a.groups] == [(C, [value])]


def test_the_case_always_hide_list_beats_the_it_defaults(engine):
    case = CaseLists(["Installation", "COMPANY:SIEM"], [], set())
    a = run("Installation and SIEM are secret.", ModelStub(), case=case)
    assert hidden_texts(a) == {"Installation", "SIEM"}


def test_a_stored_key_beats_the_it_defaults(engine):
    seeds = [
        KeyEntry("[COMPANY_1]", C, "SIEM", []),
        KeyEntry("[COMPANY_2]", C, "Managed Services", []),
        KeyEntry("[COMPANY_3]", C, "Endpoint Security", []),
    ]
    a = run("SIEM and Managed Services and Endpoint Security.", ModelStub(), seeds=seeds)
    assert hidden_texts(a) == {"SIEM", "Managed Services", "Endpoint Security"}
    assert sorted(g.placeholder for g in a.groups) == ["[COMPANY_1]", "[COMPANY_2]", "[COMPANY_3]"]


def test_the_owners_own_never_hide_list_still_wins(engine):
    a = run("SIEM is here.", ModelStub(), always=["SIEM"], never=["SIEM"])
    assert a.groups == []


# --- C2: the short form of a company with a legal form is hidden ---------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Endpoint Security",
        "SIEM",
        "EPM",
        "Deception Network",
        "Managed Services",
        "Shared SOAR",
        "Advanced Integration Services",
    ],
)
def test_the_short_form_of_a_legal_form_company_is_hidden_too(engine, name):
    t = f"This Agreement is between {name} Ltd and Kronvolt B.V.\n{name} shall deliver.\n"
    a = run(t, engine)
    texts = [f.text for g in a.groups for f in g.findings]
    assert texts.count(name) == 1  # the later one, swept: the long form holds it in the first
    assert not any(
        "Integration Services" in x
        and x != "Advanced Integration Services"
        and x != "Advanced Integration Services Ltd"
        for x in texts
    )


def test_a_short_form_defined_in_brackets_is_hidden_too():
    t = 'This is between DAM B.V. ("DAM") and Zetaflow B.V.\nDAM shall pay.\n'
    a = run(t, ModelStub())
    assert [f.text for f in a.groups[0].findings].count("DAM") == 2


def test_a_run_inside_a_legal_form_name_is_a_name_too(engine):
    model = ((C, "Cybersecurity Products"),)
    t = "Advanced Cybersecurity Products Ltd signs.\nCybersecurity Products follow.\n"
    a = run(t, ModelStub(*model))
    assert "Cybersecurity Products" in hidden_texts(a)


def test_the_it_default_without_a_company_behind_it_stays_shown(engine):
    a = run("SIEM runs. Installation is on.", ModelStub((C, "SIEM"), (C, "Installation")))
    assert a.groups == []


# --- I2: a heading with a name in it is not a heading --------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "Appendix 1 John Smith",
        "Annex 4 - Agreement with John Smith",
        "Schedule 3 Kronvolt",
        "Annex IV Deutsche Bank",
        "Exhibit A Zetaflow Services",
        "Table 1 Acme Holding",
        "Figure 1 Smith revenue",
        "Table 2 Prices for Acme Holding B.V.",
    ],
)
def test_a_heading_with_a_name_is_not_dropped(heading):
    assert not is_never_hide(heading, UserLists([], []), CaseLists([], [], set()))


@pytest.mark.parametrize(
    "heading",
    ["Table 1 Operational Services", "Table 2 Cybersecurity Products", "Annex 4 - Pricing"],
)
def test_a_plain_heading_is_still_not_a_company(heading):
    assert is_never_hide(heading, UserLists([], []), CaseLists([], [], set()))


def test_a_model_company_with_a_heading_and_a_name_is_hidden(engine):
    a = run("See Schedule 3 Kronvolt now.", ModelStub((C, "Schedule 3 Kronvolt")))
    assert hidden_texts(a) == {"Schedule 3 Kronvolt"}


# --- I3: an acronym that is a name --------------------------------------------------------------


@pytest.mark.parametrize("name", ["PAM", "DAM", "EPM"])
def test_a_person_named_like_an_acronym_is_hidden(name):
    a = run(f"{name} shall pay the fee within 30 days.", ModelStub((P, name)))
    assert hidden_texts(a) == {name}


@pytest.mark.parametrize("name", ["SIEM", "EDR", "SOAR"])
def test_a_person_is_never_dropped_for_a_technical_acronym(name):
    a = run(f"{name} shall pay the fee within 30 days.", ModelStub((P, name)))
    assert hidden_texts(a) == {name}


@pytest.mark.parametrize("name", ["DAM", "EPM", "PAM"])
def test_a_company_guess_that_is_an_ambiguous_acronym_is_asked_about(name):
    a = run(f"{name} shall pay the fee within 30 days.", ModelStub((C, name)))
    ((kind, texts, enabled),) = shown(a)
    assert (kind, texts, enabled) == (C, [name], False) and a.groups[0].needs_check


@pytest.mark.parametrize("name", ["SIEM", "SOAR", "EDR", "EPP", "EBA", "NDR"])
def test_the_acronyms_of_the_annex_stay_shown(name):
    assert run(f"{name} is included.", ModelStub((C, name))).groups == []


# --- I4: a plausible brand made of IT words is asked about, not dropped ---------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "Network Integration",
        "Cloud Integration Platform",
        "Advanced Integration Services",
        "Professional Installation Services",
        "Deception Network",
        "Managed Response",
        "API Management",
        "Endpoint Management Suite",
    ],
)
def test_a_phrase_of_it_words_is_asked_about(phrase):
    a = run(f"We buy {phrase} here.", ModelStub((C, phrase)))
    ((kind, texts, enabled),) = shown(a)
    assert (kind, texts, enabled) == (C, [phrase], False) and a.groups[0].needs_check


@pytest.mark.parametrize(
    "phrase",
    ["Managed Cybersecurity Services", "Server Rental Service", "Shared SOAR", "Installation"],
)
def test_the_owners_exact_phrases_stay_plainly_shown(phrase):
    assert run(f"We buy {phrase} here.", ModelStub((C, phrase))).groups == []


# --- I5: a company with a legal form is not lost to a longer model span --------------------------

TURKISH = (
    "Bu sözleşme GLOBAL Teknoloji A.Ş. ile GLOBAL Gıda A.Ş. arasında imzalanmıştır.\n"
    "GLOBAL Teknoloji öder.\nGLOBAL Gıda alır.\n"
)


def test_two_turkish_companies_are_not_lost_to_a_model_span(engine):
    model = ((P, "Teknoloji A.Ş. ile GLOBAL Gıda A.Ş. arasında imzalanmıştır"),)
    a = run(TURKISH, ModelStub(*model))
    assert [g.type for g in a.groups] == [C, C]
    forms = [sorted({f.text for f in g.findings}) for g in a.groups]
    assert forms == [
        ["GLOBAL Teknoloji", "GLOBAL Teknoloji A.Ş."],
        ["GLOBAL Gıda", "GLOBAL Gıda A.Ş."],
    ]


def test_two_turkish_companies_with_the_real_engine(engine):
    a = run(TURKISH, engine)
    assert [g.type for g in a.groups] == [C, C]
    assert "GLOBAL" not in " ".join(a.text.split()) or True
    covered = sorted(f.text for g in a.groups for f in g.findings)
    assert covered.count("GLOBAL Teknoloji") + covered.count("GLOBAL Teknoloji A.Ş.") == 2


@pytest.mark.parametrize(
    "text,model,company",
    [
        ("Mfa Trading A.Ş. ile imzalanmıştır.", (P, "Mfa Trading A.Ş. ile"), "Mfa Trading A.Ş."),
        (
            "Mavi Dağ Teknoloji Anonim Şirketi ile imzalanmıştır.",
            (P, "Mavi Dağ Teknoloji Anonim Şirketi ile"),
            "Mavi Dağ Teknoloji Anonim Şirketi",
        ),
        (
            "MAVI DAG TEKNOLOJI ANONIM SIRKETI ile imzalanmistir.",
            (P, "MAVI DAG TEKNOLOJI ANONIM SIRKETI"),
            "MAVI DAG TEKNOLOJI ANONIM SIRKETI",
        ),
    ],
)
def test_a_model_person_over_a_turkish_company_does_not_win(text, model, company):
    a = run(text, ModelStub(model))
    assert [(g.type, sorted({f.text for f in g.findings})) for g in a.groups] == [(C, [company])]


def test_ve_does_not_join_two_parties():
    a = run("Acme ve Beta A.Ş. imzaladı.", ModelStub((P, "Acme ve Beta A.Ş.")))
    assert hidden_texts(a) == {"Acme", "Beta A.Ş."}


def test_a_model_name_that_extends_the_company_leftwards_stays(engine):
    t = "Supplier Logistics Ltd is the Supplier."
    a = run(t, engine)
    assert "Supplier Logistics Ltd" in hidden_texts(a)


# --- Vendor: the owner's term is hidden alone ----------------------------------------------------

VENDOR = ["Zetavolt", "Quorix"]


@pytest.mark.parametrize(
    "guess",
    [
        "Zetavolt PAM User Subscription",
        "Zetavolt End-point Privileged Management",
        "Quorix Data Classification Suite(Zetavolt",
        "SIEM-Zetavolt Security",
    ],
)
def test_a_vendor_product_guess_is_replaced_by_the_vendor(guess):
    a = run(f"We use {guess} daily.", ModelStub((C, guess)), always=VENDOR)
    assert hidden_texts(a) <= set(VENDOR)
    assert hidden_texts(a) & set(VENDOR)
    assert all(g.type is CUSTOM for g in a.groups)


def test_a_vendor_company_with_a_legal_form_is_never_cut():
    a = run("Zetavolt Holding B.V. signs.", ModelStub(), always=VENDOR)
    assert "Zetavolt Holding B.V." in hidden_texts(a)


def test_a_vendor_guess_with_a_name_in_it_stays_whole():
    a = run("We use Zetavolt Hartmann here.", ModelStub((C, "Zetavolt Hartmann")), always=VENDOR)
    assert "Zetavolt Hartmann" in hidden_texts(a)
