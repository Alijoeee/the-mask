"""A generated guard: every secret a template puts in a text is hidden, whatever the model found.

The templates put made-up people and companies next to each other, with connectors, job titles and
a defined short name between them, and the language model is made to find spans that overlap
them badly (a company's last word with a connector and a person's first name; a title with half
a name). The oracle is the template's own list of secrets: every letter of every name it inserted
must be inside a hidden finding. Connectors and titles are not secrets and are not required.
Fixed seed, three list configurations (none; an always-hide code name; a never-hide list of
ordinary words).
"""

import random
import re

import pytest

from themask.detect.engine import Engine
from themask.detect.lists import UserLists
from themask.detect.pipeline import CombinedText, analyze
from themask.model import Finding, PlaceholderType

P, C = PlaceholderType.PERSON, PlaceholderType.COMPANY

FIRST = ["Pieter", "Ayşe", "Liam", "Hans", "Jan", "Mehmet", "Katrin", "Olga", "Tariq", "Ingrid"]
LAST = [
    "de Vries",
    "van der Berg",
    "O'Brien",
    "Demir",
    "McAllister",
    "bin Salleh",
    "ibn Rashid",
    "de Souza",
    "Karaca",
    "Heidenstein",
    "Gruber",
    "Van Dijk",
]
STEMS = [
    "Harborpoint Systems",
    "Zetaflow",
    "Quorvale",
    "Acmevolt Teknoloji",
    "Ege Yazılım",
    "Mavi Dağ",
    "Brightwell Analytics",
    "Norvik",
    "Tessaro Gıda",
    "Delmar Logistics",
]
FORMS = ["Ltd", "B.V.", "GmbH", "A.Ş.", "Anonim Şirketi", "Ltd. Şti.", "LLC", "AŞ", "S.A."]
CONNECTORS = ["&", "and", "ve", "ile", "en", "und", ",", "of", "-"]
TITLES = ["Genel Müdürü", "Managing Director", "Hukuk Müşaviri", "CEO", "Director"]
VERBS = ["shall pay", "imzalar", "tekent", "signs here", "will deliver"]
CODE_NAME = "Zephyrion"
ORDINARY = ["Delivery", "Payment", "Schedule"]


def _make_cases(seed=20261021, count=480):
    rng = random.Random(seed)
    cases = []
    for number in range(count):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        person = f"{first} {last}"
        s1, s2 = rng.choice(STEMS), rng.choice(STEMS)
        if s1 == s2:
            s2 = "Kestrelon"
        c1, c2 = f"{s1} {rng.choice(FORMS)}", f"{s2} {rng.choice(FORMS)}"
        conn, title, verb = rng.choice(CONNECTORS), rng.choice(TITLES), rng.choice(VERBS)
        shape = number % 8
        secrets: list[str] = []
        model: list[tuple[PlaceholderType, str]] = []
        if shape == 0:
            text = f"{c1} {conn} {person} {verb}."
            secrets = [s1, person]
            model = [(P, f"{c1.split()[-1]} {conn} {first}"), (P, person)]
        elif shape == 1:
            text = f"{c1} {title} {person} {verb}."
            secrets = [s1, person]
            model = [(P, f"{title} {first}"), (P, f"{c1.split()[-1]} {title} {first}"), (P, person)]
        elif shape == 2:
            text = f"{person}, {c1} {verb}."
            secrets = [person, s1]
            model = [(P, f"{last.split()[-1]}, {c1.split()[0]}"), (P, person)]
        elif shape == 3:
            short = c1.split()[0]
            text = f'{c1} ("{short}") {verb}. {short} pays {person}.'
            secrets = [s1, person]
            model = [(C, f'{c1} ("{short}'), (P, person)]
        elif shape == 4:
            text = f"{c1} {conn} {c2} {verb}."
            secrets = [s1, s2]
            model = [
                (P, f"{c1.split()[-1]} {conn} {c2.split()[0]}"),
                (C, f"{c1} {conn} {c2.split()[0]}"),
            ]
        elif shape == 5:
            text = f"Signed by {person} for {c1}. {person} pays {c1}. {title} {person}."
            secrets = [person, s1]
            model = [(P, f"{person} for"), (P, f"{title} {first}"), (P, person)]
        elif shape == 6:
            text = f"{c1} {title} {person}'s signature, {c2}."
            secrets = [s1, person, s2]
            model = [(P, f"{title} {first}"), (C, f"{c1} {title}"), (P, person)]
        else:
            text = f"Between {c1} {conn} {person}: {CODE_NAME} {verb} to {c2}."
            secrets = [s1, person, s2, CODE_NAME]
            model = [(P, f"{conn} {first}"), (C, f"{c2.split()[0]} {CODE_NAME}"), (P, person)]
        config = number % 3  # 0: no lists, 1: an always-hide code name, 2: ordinary never-hide
        cases.append((text, tuple(model), tuple(secrets), config))
    return cases


CASES = _make_cases()


class _Stub(Engine):
    def __init__(self, model):
        self.model = model

    def _presidio_findings(self, text):
        out = []
        for kind, needle in self.model:
            start = text.find(needle)
            while start >= 0:
                score = 0.85 if kind is P else 0.6
                out.append(Finding(kind, start, start + len(needle), needle, score, "model"))
                start = text.find(needle, start + 1)
        return out


_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")


def leaks(text, model, secrets, config):
    """The words of the secrets that are shown in the analysed ``text``."""
    always = [CODE_NAME] if config == 1 else []
    never = ORDINARY if config == 2 else []
    a = analyze(CombinedText.join([("x", text)]), _Stub(model), UserLists(always, never))
    covered = [False] * len(a.text)
    for group in a.groups:
        if group.enabled:
            for f in group.findings:
                for i in range(f.start, f.end):
                    covered[i] = True
    required = {word.casefold() for secret in secrets for word in _WORD.findall(secret)}
    if CODE_NAME in secrets and config != 1:
        required.discard(CODE_NAME.casefold())  # only the always-hide list knows it
    shown = []
    for m in _WORD.finditer(a.text):
        if m.group().casefold() in required and not all(covered[m.start() : m.end()]):
            shown.append((m.group(), m.start()))
    return shown


def test_the_generator_is_deterministic_and_big_enough():
    assert len(CASES) >= 300 and _make_cases() == CASES
    assert {c[3] for c in CASES} == {0, 1, 2}


@pytest.mark.parametrize("case", CASES, ids=[str(i) for i in range(len(CASES))])
def test_every_secret_of_a_template_is_hidden(case):
    text, model, secrets, config = case
    assert leaks(text, model, secrets, config) == [], text
