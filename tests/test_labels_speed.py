"""The clash test of the names (R127) is fast and gives the answers of the straightforward one.

``reference_clashes`` is the test as it was before the speed-up (every form looked at from
scratch for every name); the optimised ``clashes_with_values``, ``ClashProbe`` and the review's
``label_problems`` must agree with it on made-up names and values, and on the leak-critical
cases. The timing test has a generous bound (about three times what was measured).
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterable

import pytest

from themask.detect.lists import CaseLists, UserLists
from themask.labels import (
    _GERMAN,
    _STOP,
    ClashProbe,
    FormSet,
    _digits_clash,
    _identifying,
    _short_word_clash,
    _spellings,
    _umlautless,
    clashes_with_values,
    words,
)
from themask.model import Finding, Group, PlaceholderType
from themask.review import ReviewState


def reference_clashes(label: str, forms: Iterable[str]) -> bool:
    """Whether ``label`` could carry a hidden value, or part of one, into a masked file.

    A name is known text, so the test is strict, in three ways. A word of the name that tells
    values apart (``_identifying``) may not be a word of any of the ``forms``. Any word of a
    form with at least three letters that is not a stop word may not stand *inside* the name
    written without separators ("IBMSide", "AhmetTaraf", "Northwinds"). And the whole name,
    folded, may not be part of a form when it is three or more characters long. Case, accents
    and the German umlaut spellings are ignored throughout.
    """
    name_words, _ = _spellings(label)
    identifying = {w for w in name_words if _identifying(w)}
    plain = "".join(words(label))
    translit = "".join(words(label.translate(_GERMAN)))
    joined = {plain, translit, _umlautless(plain), _umlautless(translit)}
    name_texts = {" ".join(words(label)), " ".join(words(label.translate(_GERMAN)))}
    forms = list(forms)
    if _digits_clash(label, forms):
        return True
    for form in forms:
        form_words, form_text = _spellings(form)
        if identifying & form_words or _short_word_clash(label, joined, form_words):
            return True
        if any(
            sum(c.isalpha() for c in w) >= 3 and w not in _STOP and any(w in j for j in joined)
            for w in form_words
        ):
            return True
        if any(len(t.replace(" ", "")) >= 3 and t in form_text for t in name_texts):
            return True
    return False


SYLLABLES = ["ka", "lor", "vin", "tex", "mar", "dal", "pon", "ren", "sul", "bix", "tro", "han"]
NAMES = [
    "Provider", "Customer", "Landlord", "Tenant", "Seller", "Buyer", "IBMSide", "BPSide", "SideHP",
    "Tel12345678", "Acct 37040044", "Fee1250000", "MüllerSeite", "Kiraci", "The Buyer",
    "Northwinds", "AhmetTaraf", "Data-Provider", "3MCo", "Vin",
]  # fmt: skip
VALUES = [
    "BP plc", "HP Inc", "3M Company", "+49 30 12345678", "DE89 3704 0044 0532 0130 00",
    "EUR 1,250,000", "IBM Corp", "Northwind Trading B.V.", "Ahmet Taraf", "Müller GmbH",
    "Kiracı A.S.", "The Coca-Cola Company", "Vin Tex 77",
]  # fmt: skip


def made_up_values(rnd: random.Random, n: int) -> list[str]:
    out = list(VALUES)
    for _ in range(n):
        out.append(
            "".join(rnd.choice(SYLLABLES) for _ in range(rnd.randint(2, 3))).capitalize()
            + f" {rnd.choice(SYLLABLES).capitalize()}{rnd.randint(0, 99999)}"
        )
    return out


def test_the_fast_test_agrees_with_the_straightforward_one_on_made_up_names_and_values() -> None:
    rnd = random.Random(7)
    values = made_up_values(rnd, 300)
    names = [
        *NAMES,
        *(rnd.choice(SYLLABLES).capitalize() + rnd.choice(SYLLABLES) for _ in range(40)),
    ]
    clashing = 0
    for name in names:
        probe = ClashProbe(name)
        for k in range(0, len(values), 4):
            forms = values[k : k + 4]
            expected = reference_clashes(name, forms)
            clashing += expected
            assert clashes_with_values(name, forms) is expected, (name, forms)
            assert probe.clashes(forms) is expected, (name, forms)
            if expected:  # the cheap test never says "no clash" for one that is
                assert probe.may_clash(FormSet(forms)), (name, forms)
    assert clashing > 10  # the sample does have clashes in it


@pytest.mark.parametrize(
    ("name", "value"),
    [("BPSide", "BP plc"), ("HPTeam", "HP Inc"), ("3MCo", "3M Company"), ("SideBP", "BP plc"),
     ("Tel12345678", "+49 30 12345678"), ("Acct 37040044", "DE89 3704 0044 0532 0130 00"),
     ("Fee1250000", "EUR 1250000"), ("IBMSide", "IBM Corp"), ("AhmetTaraf", "Ahmet Taraf"),
     ("Northwinds", "Northwind Trading B.V."), ("MuellerSeite", "Müller GmbH")],
)  # fmt: skip
def test_the_leak_critical_clashes_are_still_found(name: str, value: str) -> None:
    assert clashes_with_values(name, [value])
    assert ClashProbe(name).may_clash(FormSet([value]))


def review_of_many(n: int, labelled: int, seed: int = 1) -> ReviewState:
    rnd = random.Random(seed)
    groups: list[Group] = []
    text = ""
    for i in range(n):
        name = (
            "".join(rnd.choice(SYLLABLES) for _ in range(3)).capitalize()
            + f" {rnd.choice(SYLLABLES).capitalize()}{i}"
        )
        found = []
        for form in (name, name.split()[0]):
            start = len(text)
            text += form + " . "
            found.append(
                Finding(PlaceholderType.COMPANY, start, start + len(form), form, 1.0, "model")
            )
        groups.append(
            Group(f"g{i}", PlaceholderType.COMPANY, name, {name}, found, f"[COMPANY_{i + 1}]")
        )
    for k in range(labelled):
        groups[k * 7].label = NAMES[k % 6]
    return ReviewState(text, groups, [], UserLists([], []), CaseLists([], [], set()))


def straightforward_pairs(review: ReviewState) -> list[tuple[str, str]]:
    from themask.labels import clash_message

    masked = [g for g in review.groups if g.active_findings()]
    out = []
    for g in masked:
        if g.label is None:
            continue
        for other in masked:
            forms = [other.canonical, *other.variants, *(f.text for f in other.findings)]
            if reference_clashes(g.label, forms):
                stored = g.placeholder in review.reserved_labels
                out.append((g.id, clash_message(g.label, g.placeholder, other.placeholder, stored)))
    return out


def test_the_review_finds_the_same_problems_as_the_straightforward_loop() -> None:
    review = review_of_many(400, 6)
    # a name that does clash: a word of a value that is being masked
    review.groups[3].label = "Kalor"
    review.groups[9].label = review.groups[11].canonical.split()[0]
    expected = straightforward_pairs(review)
    assert expected  # there are clashes in this review
    assert review.label_problem_pairs() == expected
    assert review.label_problems() == [m for _, m in expected]


def test_the_answer_follows_a_change_of_name_switch_place_or_value() -> None:
    review = review_of_many(200, 3)
    review.groups[3].label = review.groups[5].canonical.split()[0]
    first = review.label_problem_pairs()
    assert first and review.label_problem_pairs() == first  # kept
    review.groups[5].enabled = False
    assert review.label_problem_pairs() == straightforward_pairs(review) != first
    review.groups[5].enabled = True
    review.groups[5].disabled = {0, 1}  # every place off: nothing of it is masked
    assert review.label_problem_pairs() == straightforward_pairs(review)
    review.groups[5].disabled = set()
    review.groups[5].variants = {"Zzyzx Quux"}
    assert review.label_problem_pairs() == straightforward_pairs(review)
    review.groups[3].label = None
    assert review.label_problem_pairs() == [] == review.label_problems()


def test_three_thousand_groups_with_ten_names_take_a_fraction_of_a_second() -> None:
    review = review_of_many(3000, 10)
    start = time.perf_counter()
    review.label_problems()
    cold = time.perf_counter() - start
    start = time.perf_counter()
    review.label_problems()
    again = time.perf_counter() - start
    review.groups[100].enabled = False  # one toggle, the way the screen asks after it
    start = time.perf_counter()
    review.label_problems()
    toggle = time.perf_counter() - start
    # Measured: about 0.07 s, 0.003 s and 0.03 s (1.2 s for the first before the speed-up).
    assert cold < 0.5 and again < 0.1 and toggle < 0.3, (cold, again, toggle)
