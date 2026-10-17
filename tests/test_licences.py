"""Licence gate: no GPL or AGPL distribution may be installed in the environment.

A distribution is only examined when its metadata mentions GPL, "General Public" or Affero in any
form (LGPL included). It must then offer an acceptable licence:

* ``License-Expression`` (PEP 639), when present, is the whole answer. It is read as an SPDX
  expression: ``OR`` is a choice, ``AND`` needs both sides, ``WITH`` and parentheses work, and a
  broken expression fails closed. Classifiers are ignored.
* Without it, the legacy ``License`` field decides when it names an acceptable licence. When it
  names GPL or AGPL and offers no alternative, the distribution fails whatever the classifiers
  say. When it says nothing useful (empty, "UNKNOWN"), one acceptable classifier is enough, so a
  dual "LGPL" plus "GPL" pair of classifiers passes.
* A name is acceptable when it holds an ACCEPT entry as a whole word ("LGPLv3" and "MIT-CMU"
  match; "permitted" and "example" do not) and does not itself name GPL, AGPL or Affero.

Limits: licence files are not read, a GPL wording that avoids "GPL", "General Public" and
"Affero" (a bare "GNU Public License") is not noticed, and a distribution that declares no
licence at all is invisible to the gate. A dual licence written as prose instead of an SPDX
expression ("Dual licensed under MIT or the GPL") is refused rather than guessed at.
"""

import re
import textwrap
from collections import deque
from collections.abc import Iterable
from importlib.metadata import Distribution, distributions
from pathlib import Path
from typing import NamedTuple

import pytest

ACCEPT = (
    "MIT",
    "BSD",
    "Apache",
    "LGPL",
    "MPL",
    "PSF",
    "Python Software Foundation",
    "ISC",
    "Unlicense",
    "Zlib",
    "HPND",
    "MIT-CMU",
    "CNRI",
    # Artistic-2.0 is OSI-approved; text-unidecode (Artistic OR GPL) is dev-only, via Briefcase.
    "Artistic",
)

# An ACCEPT entry counts only as a whole word: never inside another word ("permitted", "example",
# "disclaimer"). A version may follow it directly (LGPLv3, Apache2) and a dash may continue it
# (LGPL-2.1-only, MIT-CMU).
ACCEPTED_NAME = re.compile(
    "|".join(rf"(?<![a-z]){re.escape(entry.lower())}(?:(?![a-z])|(?=v\d))" for entry in ACCEPT)
)
# A GPL-family name other than the "Lesser" and "Library" ones: GPL, AGPL, General Public, Affero.
COPYLEFT = re.compile(r"(?<!l)gpl|(?<!lesser )(?<!library )general public|affero")
# What makes the gate look at a distribution at all: any GPL-family wording, LGPL included.
TRIGGER = re.compile(r"GPL|GENERAL PUBLIC|AFFERO", re.IGNORECASE)
IDENTIFIER = re.compile(r"[\w.+:-]+")


class Declared(NamedTuple):
    """What a distribution says about its licence. The three sources count differently."""

    expression: str = ""  # License-Expression (PEP 639): an SPDX expression
    licence: str = ""  # legacy License field: a name, or a whole licence text pasted in
    classifiers: tuple[str, ...] = ()  # the last part of each "License ::" classifier


def declared(dist: Distribution) -> Declared:
    md = dist.metadata
    return Declared(
        expression=(md.get("License-Expression") or "").strip(),
        licence=(md.get("License") or "").strip(),
        classifiers=tuple(
            c.split("::")[-1].strip()
            for c in md.get_all("Classifier") or []
            if c.startswith("License ::")
        ),
    )


def squash(text: str) -> str:
    """Lower case, with every run of whitespace (line breaks too) reduced to one space."""
    return " ".join(text.lower().split())


def triggered(d: Declared) -> bool:
    """Does the metadata mention a GPL-family licence at all (LGPL included)?"""
    return bool(TRIGGER.search(squash(" ".join((d.expression, d.licence, *d.classifiers)))))


def name_ok(text: str) -> bool:
    """One licence name, or free text: holds an ACCEPT entry and does not itself name GPL/AGPL."""
    text = squash(text)
    return bool(ACCEPTED_NAME.search(text)) and not COPYLEFT.search(text)


# SPDX expressions: WITH binds tightest, then AND, then OR. A term is a licence name or a group.
def parse_or(tokens: deque[str]) -> bool:
    ok = parse_and(tokens)
    while tokens and tokens[0].upper() == "OR":
        tokens.popleft()
        ok = parse_and(tokens) or ok
    return ok


def parse_and(tokens: deque[str]) -> bool:
    ok = parse_term(tokens)
    while tokens and tokens[0].upper() == "AND":
        tokens.popleft()
        ok = parse_term(tokens) and ok
    return ok


def parse_term(tokens: deque[str]) -> bool:
    token = tokens.popleft() if tokens else ""
    if token == "(":
        ok = parse_or(tokens)
        if (tokens.popleft() if tokens else "") != ")":
            raise ValueError("unbalanced parenthesis")
    elif IDENTIFIER.fullmatch(token) and token.upper() not in ("AND", "OR", "WITH"):
        ok = name_ok(token)
    else:
        raise ValueError(f"unexpected {token!r}")
    if tokens and tokens[0].upper() == "WITH":  # an exception never changes which licence it is
        tokens.popleft()
        if not (tokens and IDENTIFIER.fullmatch(tokens.popleft())):
            raise ValueError("WITH needs an exception")
    return ok


def evaluate(expression: str) -> bool | None:
    """True or False for a valid SPDX expression; None when the text is not one."""
    tokens = deque(re.findall(r"[()]|[^\s()]+", expression))
    try:
        ok = parse_or(tokens)
    except ValueError:
        return None
    return None if tokens else ok


def statement_ok(text: str) -> bool:
    """A License-Expression or License value: an expression if it is one, else a name or text."""
    verdict = evaluate(text)
    return name_ok(text) if verdict is None else verdict


def acceptable(d: Declared) -> bool:
    """Does the distribution offer a licence we accept? The rules are in the module docstring."""
    if d.expression:
        return statement_ok(d.expression)
    if d.licence:
        if statement_ok(d.licence):
            return True
        if COPYLEFT.search(squash(d.licence)):
            return False
    return any(name_ok(classifier) for classifier in d.classifiers)


def find_violations(dists: Iterable[Distribution]) -> list[str]:
    """One line per GPL/AGPL distribution: its name and what its metadata says."""
    found = []
    for dist in dists:
        d = declared(dist)
        if triggered(d) and not acceptable(d):
            says = "; ".join(part for part in (d.expression, d.licence, *d.classifiers) if part)
            found.append(f"{dist.metadata['Name']}: {textwrap.shorten(says, width=160)}")
    return found


GPL_PREAMBLE = """\
                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007

 Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
 Everyone is permitted to copy and distribute verbatim copies
 of this license document, but changing it is not allowed.

                            Preamble

  The GNU General Public License is a free, copyleft license for
software and other kinds of works.

  For example, if you distribute copies of such a program, whether
gratis or for a fee, you must pass on to the recipients the same
freedoms that you received.
"""

AGPL_TEXT = """\
                    GNU AFFERO GENERAL PUBLIC LICENSE
                       Version 3, 19 November 2007

 Everyone is permitted to copy and distribute verbatim copies
 of this license document, but changing it is not allowed.

  The GNU Affero General Public License is a free, copyleft license for
software and other kinds of works, specifically designed to ensure
cooperation with the community in the case of network server software.
"""

REFUSED = [
    pytest.param(Declared(expression="GPL-3.0-only"), id="plain GPL"),
    pytest.param(Declared(expression="AGPL-3.0-only"), id="plain AGPL"),
    pytest.param(Declared(expression="MIT AND GPL-3.0-only"), id="AND needs both sides"),
    pytest.param(
        Declared(licence=GPL_PREAMBLE, classifiers=("GNU General Public License v3 (GPLv3)",)),
        id="pasted GPL preamble with its classifier",
    ),
    pytest.param(Declared(licence=AGPL_TEXT), id="pasted AGPL text without the abbreviation"),
    pytest.param(
        Declared(classifiers=("GNU Affero General Public License v3",)),
        id="classifier-only Affero",
    ),
    pytest.param(Declared(licence="GPL-3.0-only (see example below)"), id="example is not MPL"),
    pytest.param(
        Declared(expression="GPL-3.0-or-later", classifiers=("MIT License",)),
        id="expression outranks an MIT classifier",
    ),
    pytest.param(
        Declared(licence="GPL-3.0-or-later", classifiers=("MIT License",)),
        id="GPL licence field outranks an MIT classifier",
    ),
    pytest.param(
        Declared(expression="(MIT OR GPL-3.0-only) AND GPL-2.0-only"),
        id="AND after a parenthesised choice",
    ),
    pytest.param(
        Declared(expression="GPL-2.0-only WITH Classpath-exception-2.0"),
        id="GPL with an exception is still GPL",
    ),
    pytest.param(Declared(expression="MIT OR (GPL-3.0-only"), id="broken expression fails closed"),
    pytest.param(
        Declared(licence="agpl-3.0 with an lgpl linking exception"),
        id="AGPL is refused whatever the case",
    ),
    pytest.param(
        Declared(
            classifiers=(
                "GNU General Public License v3 (GPLv3)",
                "GNU Affero General Public License v3 or later (AGPLv3+)",
            )
        ),
        id="only GPL classifiers",
    ),
    pytest.param(
        Declared(licence="GNU General\n   Public License v3"), id="line break in the name"
    ),
    pytest.param(Declared(licence="Affero license (MIT-compatible)"), id="Affero by name alone"),
    pytest.param(
        Declared(
            licence="Proprietary: redistribution permitted only with written consent",
            classifiers=("GNU General Public License v3 (GPLv3)",),
        ),
        id="permitted is not MIT",
    ),
    pytest.param(Declared(expression="GPL-3.0-only OR LicenseRef-Sample"), id="sample is not MPL"),
    pytest.param(
        Declared(classifiers=("GNU Affero General Public License v3 with MIT-style linking",)),
        id="an AGPL classifier never counts",
    ),
    pytest.param(
        Declared(licence="Dual licensed under the MIT license or the GPL, at your option"),
        id="dual licence as prose is refused, not guessed at",
    ),
]

PERMITTED = [
    pytest.param(Declared(expression="LGPL-2.1-only"), id="LGPL expression"),
    pytest.param(Declared(licence="LGPL"), id="LGPL licence field"),
    pytest.param(
        Declared(expression="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"),
        id="PySide6: LGPL or GPL",
    ),
    pytest.param(
        Declared(
            licence="Artistic License",
            classifiers=(
                "Artistic License",
                "GNU General Public License (GPL)",
                "GNU General Public License v2 or later (GPLv2+)",
            ),
        ),
        id="text-unidecode: Artistic or GPL",
    ),
    pytest.param(
        Declared(licence="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"),
        id="PySide6 as published: the License field holds the expression",
    ),
    pytest.param(Declared(expression="MIT-CMU"), id="MIT-CMU"),
    pytest.param(Declared(expression="MPL-2.0"), id="MPL-2.0"),
    pytest.param(
        Declared(
            licence="UNKNOWN",
            classifiers=("GNU Lesser General Public License v3 (LGPLv3)",),
        ),
        id="UNKNOWN licence field, LGPL classifier",
    ),
    pytest.param(
        Declared(
            classifiers=(
                "GNU Lesser General Public License v3 (LGPLv3)",
                "GNU General Public License v3 (GPLv3)",
            )
        ),
        id="LGPLv3 and GPLv3 classifiers",
    ),
    pytest.param(
        Declared(expression="MIT AND (LGPL-3.0-only OR GPL-3.0-only)"), id="choice inside an AND"
    ),
    pytest.param(
        Declared(expression="LGPL-3.0-or-later WITH LGPL-3.0-linking-exception"),
        id="LGPL with an exception",
    ),
    pytest.param(
        Declared(licence="GNU Lesser General Public License v3 or later (LGPLv3+)"),
        id="LGPL spelled out",
    ),
    pytest.param(
        Declared(expression="MIT", classifiers=("GNU General Public License v3 (GPLv3)",)),
        id="expression outranks a GPL classifier",
    ),
    pytest.param(
        Declared(expression="GPL-2.0-only WITH Classpath-exception-2.0 OR MIT"),
        id="GPL with an exception, or MIT",
    ),
    pytest.param(Declared(expression="GPL-3.0-only OR 0BSD"), id="0BSD alternative"),
    pytest.param(Declared(licence="LGPLv3+"), id="LGPLv3+ as a bare name"),
]

UNRELATED = [
    pytest.param(Declared(expression="MIT-CMU"), id="MIT-CMU"),
    pytest.param(Declared(expression="Apache-2.0 OR BSD-3-Clause"), id="Apache or BSD"),
    pytest.param(
        Declared(
            licence="Everyone is permitted to copy this, for example in a simple sample.",
            classifiers=("MIT License",),
        ),
        id="prose with permitted, example, simple",
    ),
    pytest.param(Declared(), id="nothing declared"),
]


@pytest.mark.parametrize("declared_licence", REFUSED)
def test_copyleft_is_noticed_and_refused(declared_licence: Declared) -> None:
    assert triggered(declared_licence)
    assert not acceptable(declared_licence)


@pytest.mark.parametrize("declared_licence", PERMITTED)
def test_permitted_licences_pass(declared_licence: Declared) -> None:
    assert acceptable(declared_licence)


@pytest.mark.parametrize("declared_licence", UNRELATED)
def test_gate_ignores_licences_without_gpl_wording(declared_licence: Declared) -> None:
    assert not triggered(declared_licence)


class FakeDistribution(Distribution):
    """An installed distribution whose METADATA is exactly the given header lines."""

    def __init__(self, name: str, *headers: str) -> None:
        lines = ["Metadata-Version: 2.4", f"Name: {name}", "Version: 1.0", *headers]
        self._metadata = "\n".join(lines) + "\n"

    def read_text(self, filename: str) -> str | None:
        return self._metadata if filename == "METADATA" else None

    def locate_file(self, path: str | Path) -> Path:
        return Path(path)


def test_scan_names_each_gpl_distribution_it_finds() -> None:
    dists = [
        FakeDistribution("fine", "License-Expression: MIT"),
        FakeDistribution("dual", "License-Expression: LGPL-3.0-only OR GPL-3.0-only"),
        FakeDistribution("gpl", "License-Expression: GPL-3.0-only"),
        FakeDistribution(
            "pasted",
            "License: GNU GENERAL PUBLIC LICENSE",
            "        Version 3, 29 June 2007",
            "        Everyone is permitted to copy and distribute verbatim copies",
        ),
        FakeDistribution(
            "affero",
            "Classifier: License :: OSI Approved :: GNU Affero General Public License v3",
        ),
    ]
    assert [line.split(":")[0] for line in find_violations(dists)] == ["gpl", "pasted", "affero"]


def test_no_gpl_or_agpl_in_environment() -> None:
    assert find_violations(distributions()) == []
