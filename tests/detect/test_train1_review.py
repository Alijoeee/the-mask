"""Training round 1, fix round: what the deep review found. Every input is made up."""

import time

import pytest

from themask.detect.engine import Engine
from themask.detect.lists import CaseLists, UserLists
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
        "Rate 20%" + pad * 1000 + "VAT",
        "VAT" + pad * 1000 + "20%",
        "1,000" + pad * 1000 + "users",
        "fee" + pad * 1000 + "1,000" + pad * 1000 + "users",
    ):
        start = time.perf_counter()
        engine.analyze(text)
        assert time.perf_counter() - start < 1.5
