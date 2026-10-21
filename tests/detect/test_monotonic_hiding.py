"""Hiding only grows: nothing the version before training round 1 hid is shown now.

Each case is a made-up text, the spans the language model is made to find (``None`` runs the real
engine), and the words of the text, as ``word@n`` for the n-th occurrence, that the version before
the training round (mac-v1) hid. They are recorded here as literals; the test asserts that each is
still hidden. The unhides the owner decided on (IT vocabulary, tax rates, capacity counts, legal
references, headings) are not in these texts. Further cases at the end pin what the review found.
"""

import re

import pytest

from themask.detect.engine import Engine
from themask.detect.lists import UserLists
from themask.detect.pipeline import CombinedText, analyze
from themask.model import Finding, PlaceholderType

P, C = "P", "C"


class _Stub(Engine):
    def __init__(self, model):
        self.model = model

    def _presidio_findings(self, text):
        out = []
        for kind, needle in self.model:
            where = PlaceholderType.PERSON if kind == "P" else PlaceholderType.COMPANY
            score = 0.85 if kind == "P" else 0.6
            start = text.find(needle)
            while start >= 0:
                out.append(Finding(where, start, start + len(needle), needle, score, "model"))
                start = text.find(needle, start + 1)
        return out


_WORD = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)?")


def hidden_words(text, engine):
    a = analyze(CombinedText.join([("x", text)]), engine, UserLists([], []))
    covered = [False] * len(a.text)
    for group in a.groups:
        if group.enabled:
            for f in group.findings:
                for i in range(f.start, f.end):
                    covered[i] = True
    seen: dict[str, int] = {}
    hidden = set()
    for m in _WORD.finditer(a.text):
        n = seen.get(m.group(), 0)
        seen[m.group()] = n + 1
        if all(covered[m.start() : m.end()]):
            hidden.add(f"{m.group()}@{n}")
    return hidden


CASES = [
    (
        "Mavi Teknoloji A.Ş. Genel Müdürü Ahmet Yılmaz imzalar.",
        ((P, "A.Ş. Genel Müdürü Ahmet"),),
        ("A@0", "Ş@0", "Genel@0", "Müdürü@0", "Ahmet@0"),
    ),
    (
        "Acme Ltd and Mary O'Hara sign.",
        ((P, "Acme Ltd and Mary O'Hara"),),
        ("Acme@0", "Ltd@0", "and@0", "Mary@0", "O'Hara@0"),
    ),
    ("Ltd Mary O'Hara signs.", ((P, "Ltd Mary O'Hara"),), ("Ltd@0", "Mary@0", "O'Hara@0")),
    (
        "Mavi Teknoloji A.Ş. ile Ahmet Yılmaz sign.",
        ((P, "Mavi Teknoloji A.Ş. ile Ahmet Yılmaz"),),
        ("Mavi@0", "Teknoloji@0", "A@0", "Ş@0", "ile@0", "Ahmet@0", "Yılmaz@0"),
    ),
    (
        "Mavi Teknoloji A.Ş. Genel Müdürü Ahmet Yılmaz",
        ((P, "A.Ş. Genel Müdürü Ahmet Yılmaz"),),
        ("A@0", "Ş@0", "Genel@0", "Müdürü@0", "Ahmet@0", "Yılmaz@0"),
    ),
    (
        "Supplies Ltd Zetaflow Analytics sign.",
        ((C, "Supplies Ltd Zetaflow Analytics"),),
        ("Supplies@0", "Ltd@0"),
    ),
    (
        "Bright Ltd Bright Star Division signs.",
        ((C, "Ltd Bright Star Division"),),
        ("Ltd@0", "Bright@1", "Star@0", "Division@0"),
    ),
    (
        "Acme B.V. en Jan de Vries tekenen.",
        ((C, "Acme B.V. en Jan de Vries"),),
        ("Acme@0", "B@0", "V@0"),
    ),
    (
        "Acme Ltd John Carter Beta Ltd sign.",
        ((P, "Acme Ltd John Carter Beta Ltd"),),
        ("Acme@0", "Ltd@0", "John@0", "Carter@0", "Beta@0", "Ltd@1"),
    ),
    ("Acme Ltd van der Berg signs here.", None, ("Acme@0", "Ltd@0", "van@0", "der@0", "Berg@0")),
    ("Acme Ltd de Groot signs here.", None, ("Acme@0", "Ltd@0", "de@0", "Groot@0")),
    (
        "Acme Ltd von Bülow signs here.",
        ((P, "Acme Ltd von Bülow"),),
        ("Acme@0", "Ltd@0", "von@0", "Bülow@0"),
    ),
    (
        "Acme Ltd ibn Saud signs here.",
        ((P, "Acme Ltd ibn Saud"),),
        ("Acme@0", "Ltd@0", "ibn@0", "Saud@0"),
    ),
    (
        "Acme Ltd a/s Nordic signs here.",
        ((P, "Acme Ltd a/s Nordic"),),
        ("Acme@0", "Ltd@0", "a@0", "s@0", "Nordic@0"),
    ),
    ("Bank of Ireland plc shall pay.", None, ("Bank@0", "of@0", "Ireland@0", "plc@0")),
    (
        "Bank of Scotland plc and Bank of America Corp shall pay.",
        None,
        ("Bank@0", "of@0", "Scotland@0", "plc@0", "Bank@1", "of@1", "America@0", "Corp@0"),
    ),
    (
        "Royal Bank of Scotland plc shall pay.",
        None,
        ("Royal@0", "Bank@0", "of@0", "Scotland@0", "plc@0"),
    ),
    (
        "Acme Ltd jane carter signs.",
        ((P, "Acme Ltd jane carter"),),
        ("Acme@0", "Ltd@0", "jane@0", "carter@0"),
    ),
    (
        "Acme B.V., vertegenwoordigd door Jan van der Berg, tekent.",
        None,
        ("Acme@0", "B@0", "V@0", "Berg@0"),
    ),
    (
        "Write to Acme Ltd jane@acme.com today.",
        None,
        ("Acme@0", "Ltd@0", "jane@0", "acme@0", "com@0"),
    ),
    (
        "Bu sözleşme GLOBAL Teknoloji A.Ş. ile GLOBAL Gıda A.Ş. arasında imzalanmıştır. GLOBAL Teknoloji öder. GLOBAL Gıda alır.",
        ((P, "Teknoloji A.Ş. ile GLOBAL Gıda A.Ş. arasında imzalanmıştır"),),
        (
            "Teknoloji@0",
            "A@0",
            "Ş@0",
            "ile@0",
            "GLOBAL@1",
            "Gıda@0",
            "A@1",
            "Ş@1",
            "arasında@0",
            "imzalanmıştır@0",
        ),
    ),
    (
        "Bu sözleşme GLOBAL Teknoloji A.Ş. ile GLOBAL Gıda A.Ş. arasında imzalanmıştır. GLOBAL Teknoloji öder. GLOBAL Gıda alır.",
        None,
        (
            "Teknoloji@0",
            "A@0",
            "Ş@0",
            "ile@0",
            "GLOBAL@1",
            "Gıda@0",
            "A@1",
            "Ş@1",
            "arasında@0",
            "imzalanmıştır@0",
            "Teknoloji@1",
            "Gıda@1",
        ),
    ),
    (
        "Mfa Trading A.Ş. ile imzalanmıştır. Mfa Trading öder.",
        ((P, "Mfa Trading A.Ş. ile"),),
        ("Mfa@0", "Trading@0", "A@0", "Ş@0", "ile@0"),
    ),
    (
        "Mavi Dağ Teknoloji Anonim Şirketi ile imzalanmıştır. Teknoloji öder.",
        ((P, "Mavi Dağ Teknoloji Anonim Şirketi ile"),),
        ("Mavi@0", "Dağ@0", "Teknoloji@0", "Anonim@0", "Şirketi@0", "ile@0"),
    ),
    (
        "Acme ve Beta A.Ş. imzaladı.",
        ((P, "Acme ve Beta A.Ş."),),
        ("Acme@0", "ve@0", "Beta@0", "A@0", "Ş@0"),
    ),
    (
        "MAVI DAG TEKNOLOJI ANONIM SIRKETI ile imzalanmistir.",
        ((P, "MAVI DAG TEKNOLOJI ANONIM SIRKETI"),),
        ("MAVI@0", "DAG@0", "TEKNOLOJI@0", "ANONIM@0", "SIRKETI@0"),
    ),
    (
        "Smith & Jones Ltd shall pay Smith & Jones Ltd.",
        None,
        ("Smith@0", "Jones@0", "Ltd@0", "Smith@1", "Jones@1", "Ltd@1"),
    ),
    ("Deutsche Bank AG Frankfurt branch pays.", None, ("Deutsche@0", "Bank@0", "AG@0")),
    ("Acme Ltd. John Carter signs.", None, ("Acme@0", "Ltd@0", "John@0", "Carter@0")),
    (
        "Mavi Teknoloji A.Ş. Genel Müdürü Ahmet Yılmaz imzalar. Ahmet Yılmaz tarih atar.",
        None,
        (
            "Mavi@0",
            "Teknoloji@0",
            "A@0",
            "Ş@0",
            "Genel@0",
            "Müdürü@0",
            "Ahmet@0",
            "Ahmet@1",
            "Yılmaz@1",
        ),
    ),
    (
        "Name: Jane Doe, for Acme Supplies Ltd. Passport number: 534412786.",
        None,
        ("Jane@0", "Doe@0", "Acme@0", "Supplies@0", "Ltd@0", "534412786@0"),
    ),
    (
        "Signed by Jane Doe Smith for Acme Supplies Ltd. Passport checked.",
        ((P, "Jane Doe Smith"), (C, "Acme Supplies Ltd. Passport")),
        ("Jane@0", "Doe@0", "Smith@0", "Acme@0", "Supplies@0", "Ltd@0"),
    ),
    ("Supplier Logistics Ltd is the Supplier.", None, ("Supplier@0", "Logistics@0", "Ltd@0")),
    (
        "Acme Supplies Ltd and Northwind Trading B.V. appoint John Smith.",
        None,
        (
            "Acme@0",
            "Supplies@0",
            "Ltd@0",
            "Northwind@0",
            "Trading@0",
            "B@0",
            "V@0",
            "John@0",
            "Smith@0",
        ),
    ),
    (
        "The contract is with Greystone Logistics Ltd, whose director Mary Quinn signs.",
        None,
        ("Greystone@0", "Logistics@0", "Ltd@0", "Mary@0", "Quinn@0"),
    ),
    ("Kron Holding B.V. signs.", None, ("Kron@0", "Holding@0", "B@0", "V@0")),
    (
        "Beta GmbH und Hans Müller unterschreiben.",
        ((P, "Beta GmbH und Hans Müller"),),
        ("Beta@0", "GmbH@0", "und@0", "Hans@0", "Müller@0"),
    ),
    (
        "Nordic Parts A/S and Jens Hansen sign. Nordic Parts pays.",
        None,
        ("Nordic@0", "Parts@0", "A@0", "S@0", "Jens@0", "Hansen@0", "Nordic@1", "Parts@1"),
    ),
    (
        "Delta Gıda Ltd. Şti. ile Ali Veli arasında. Delta Gıda öder. Ali Veli imzalar.",
        None,
        (
            "Delta@0",
            "Gıda@0",
            "Ltd@0",
            "Şti@0",
            "ile@0",
            "Ali@0",
            "Veli@0",
            "Delta@1",
            "Gıda@1",
            "Ali@1",
            "Veli@1",
        ),
    ),
    (
        "Borusan Yazılım Sanayi ve Ticaret A.Ş. ile Mavi Dağ San. ve Tic. Ltd. Şti. taraftır.",
        ((P, "Borusan Yazılım Sanayi"), (P, "Ticaret A.Ş. ile")),
        (
            "Borusan@0",
            "Yazılım@0",
            "Sanayi@0",
            "Ticaret@0",
            "A@0",
            "Ş@0",
            "ile@0",
            "Tic@0",
            "Ltd@0",
            "Şti@0",
        ),
    ),
    (
        "Kuzey Kollektif Şirket ve Orta Komandit Şirket imzalar.",
        ((C, "Kuzey Kollektif Şirket ve"),),
        ("Kuzey@0", "Kollektif@0", "Şirket@0", "ve@0"),
    ),
    (
        "Acme Corporation Tax is due. Acme Corporation warranty claims apply.",
        None,
        ("Acme@0", "Corporation@0", "Tax@0", "Acme@1", "Corporation@1"),
    ),
    (
        "Marlowe Print and Packaging Ltd and Smith and Co. deliver.",
        None,
        ("Marlowe@0", "Print@0", "and@0", "Packaging@0", "Ltd@0", "Smith@0", "and@2", "Co@0"),
    ),
    (
        "John Smith, CEO of Acme Ltd, and Mary Jones, CFO of Beta Ltd, sign.",
        None,
        (
            "John@0",
            "Smith@0",
            "Acme@0",
            "Ltd@0",
            "Mary@0",
            "Jones@0",
            "CFO@0",
            "of@1",
            "Beta@0",
            "Ltd@1",
        ),
    ),
    (
        "Please pay EUR 12,500.00 to Acme Ltd, IBAN NL91ABNA0417164300, by 1 March 2026.",
        None,
        ("EUR@0", "12@0", "500@0", "00@0", "Acme@0", "Ltd@0", "IBAN@0", "NL91ABNA0417164300@0"),
    ),
    (
        "Contact Jane Doe (jane.doe@acme.example, +31 20 123 4567) at Acme Ltd.",
        None,
        (
            "Jane@0",
            "Doe@0",
            "jane@0",
            "doe@0",
            "acme@0",
            "example@0",
            "31@0",
            "20@0",
            "123@0",
            "4567@0",
            "Acme@0",
            "Ltd@0",
        ),
    ),
    (
        "Acme Ltd. and Beta Ltd. agree. Acme Ltd. pays.",
        ((C, "Acme Ltd. and Beta Ltd."),),
        ("Acme@0", "Ltd@0", "Beta@0", "Ltd@1", "Acme@1", "Ltd@2"),
    ),
    ("Ltd Acme Corp Ltd signs.", ((C, "Ltd Acme Corp"),), ("Acme@0", "Corp@0", "Ltd@1")),
    (
        "Müller GmbH & Co. KG and Jan de Vries sign.",
        ((P, "Co. KG and Jan de Vries"),),
        ("Co@0", "KG@0", "and@0", "Jan@0", "de@0", "Vries@0"),
    ),
    ("Acme Ltd\nJohn Carter\nsigns here.", ((P, "Acme Ltd"),), ("Acme@0", "Ltd@0")),
    (
        "The Buyer, Acme Ltd, and the Seller, Beta Ltd, sign. Acme pays Beta.",
        None,
        ("Acme@0", "Ltd@0", "Beta@0", "Ltd@1", "Acme@1", "Beta@1"),
    ),
    (
        'Kestrel Foods Ltd ("Kestrel") and Oak Ventures Ltd ("Oak"). Kestrel pays Oak.',
        None,
        (
            "Kestrel@0",
            "Foods@0",
            "Ltd@0",
            "Kestrel@1",
            "Oak@0",
            "Ventures@0",
            "Ltd@1",
            "Oak@1",
            "Kestrel@2",
            "Oak@2",
        ),
    ),
    (
        "Acme Ltd Ahmet Yılmaz Genel Müdürü imzalar. Ahmet Yılmaz öder.",
        ((P, "Ltd Ahmet"),),
        ("Ltd@0", "Ahmet@0"),
    ),
    (
        "Mavi A.Ş. Ahmet Yılmaz ve Ayşe Kaya imzalar.",
        ((P, "A.Ş. Ahmet"), (P, "Ayşe Kaya")),
        ("A@0", "Ş@0", "Ahmet@0", "Ayşe@0", "Kaya@0"),
    ),
]


@pytest.mark.parametrize("text,model,must_hide", CASES, ids=[str(i) for i in range(len(CASES))])
def test_what_was_hidden_before_is_still_hidden(engine, text, model, must_hide):
    hidden = hidden_words(text, engine if model is None else _Stub(model))
    assert set(must_hide) <= hidden, sorted(set(must_hide) - hidden)


# The review's own findings: these names are hidden everywhere, whatever the model cut.
TURKISH_TWO = (
    "Bu sözleşme GLOBAL Teknoloji A.Ş. ile GLOBAL Gıda A.Ş. arasında imzalanmıştır. "
    "GLOBAL Teknoloji öder. GLOBAL Gıda alır."
)
MANAGER = "Mavi Teknoloji A.Ş. Genel Müdürü Ahmet Yılmaz imzalar. Ahmet Yılmaz tarih atar."
EVERYWHERE = [
    (
        TURKISH_TWO,
        (P, "Teknoloji A.Ş. ile GLOBAL Gıda A.Ş. arasında imzalanmıştır"),
        ["GLOBAL", "Teknoloji", "Gıda"],
    ),
    (
        TURKISH_TWO,
        None,
        ["GLOBAL", "Gıda"],
    ),
    ("Mfa Trading A.Ş. ile imzalanmıştır. Mfa Trading öder.", (P, "Mfa Trading A.Ş. ile"), ["Mfa"]),
    (
        "Mavi Dağ Teknoloji Anonim Şirketi ile imzalanmıştır.",
        (P, "Mavi Dağ Teknoloji Anonim Şirketi ile"),
        ["Mavi", "Dağ", "Teknoloji", "Anonim"],
    ),
    ("Acme ve Beta A.Ş. imzaladı.", (P, "Acme ve Beta A.Ş."), ["Acme", "Beta"]),
    (
        "MAVI DAG TEKNOLOJI ANONIM SIRKETI ile imzalanmistir.",
        (P, "MAVI DAG TEKNOLOJI ANONIM SIRKETI"),
        ["MAVI", "DAG", "SIRKETI"],
    ),
    (
        "Borusan Yazılım Sanayi ve Ticaret A.Ş. ile Delta Gıda Ltd. Şti. arasındadır.",
        (P, "Ticaret A.Ş. ile"),
        ["Borusan", "Yazılım", "Ticaret", "Delta"],
    ),
    (
        MANAGER,
        None,
        ["Mavi", "Ahmet", "Yılmaz"],
    ),
    ("Acme Ltd van der Berg signs here.", None, ["van", "der", "Berg"]),
    ("Acme Ltd de Groot signs here.", None, ["Groot"]),
    ("Bank of Ireland plc shall pay.", None, ["Bank", "Ireland"]),
    ("Acme Ltd jane carter signs.", (P, "Acme Ltd jane carter"), ["jane", "carter"]),
    ("Write to Acme Ltd jane@acme.com today.", None, ["jane", "com"]),
]


@pytest.mark.parametrize(
    "text,model,words", EVERYWHERE, ids=[str(i) for i in range(len(EVERYWHERE))]
)
def test_these_words_are_hidden_everywhere(engine, text, model, words):
    a = analyze(
        CombinedText.join([("x", text)]),
        engine if model is None else _Stub([model]),
        UserLists([], []),
    )
    covered = [False] * len(a.text)
    for group in a.groups:
        if group.enabled:
            for f in group.findings:
                for i in range(f.start, f.end):
                    covered[i] = True
    for m in _WORD.finditer(a.text):
        if m.group() in words:
            assert all(covered[m.start() : m.end()]), (m.group(), m.start())
