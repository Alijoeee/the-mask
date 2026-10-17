"""Licence gate: no GPL or AGPL distribution may be installed in the environment.

LGPL used as a library is allowed, and so is a dual licence that offers an accepted
alternative (PySide6 is "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only").
"""

from importlib.metadata import Distribution, distributions

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


def licence_of(dist: Distribution) -> str:
    md = dist.metadata
    expr = md.get("License-Expression") or md.get("License") or ""
    cls = "; ".join(
        c.split("::")[-1].strip()
        for c in md.get_all("Classifier") or []
        if c.startswith("License ::")
    )
    return f"{expr}; {cls}"


def acceptable(text: str) -> bool:
    alternatives = [a.strip() for a in text.replace(";", " OR ").split(" OR ")]
    return any(
        any(ok.lower() in a.lower() for ok in ACCEPT) and "AGPL" not in a for a in alternatives
    )


def test_no_gpl_or_agpl_in_environment() -> None:
    bad = [
        f"{d.metadata['Name']}: {licence_of(d)}"
        for d in distributions()
        if ("GPL" in licence_of(d).upper() and not acceptable(licence_of(d)))
    ]
    assert bad == []
