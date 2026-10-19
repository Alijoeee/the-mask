"""Checks that The MASK.app holds the packages uv.lock locks, at the locked versions.

    uv run python -m tools.check_bundle_lock [path/to/The MASK.app]

The default app is the one ``packaging/build_mac.sh`` builds. Briefcase installs the app's packages
with pip, which takes the newest version of every package that nothing pins, while the tests and
the development environment run on the versions in ``uv.lock``: the first build had certifi and
filelock newer than the lock. The build script now hands pip the locked versions, and this check is
the proof that pip took them.

It reads the packages in the app (the dist-info folders in its ``app_packages``), asks ``uv export``
for the packages the lock holds for this Mac and Python (the markers of the lock decide which apply
here: colorama is for Windows, jeepney for Linux), and lists every difference: a package at another
version, a package in the app that the lock does not hold, a locked package missing from the app.
The exit status is 0 when there is none, 1 when there is any and 2 when the check could not be made.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from importlib.metadata import distributions
from pathlib import Path

from packaging.markers import Marker
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APP = ROOT / "build" / "themask" / "macos" / "app" / "The MASK.app"

# What uv is asked for: every package the app runs on, none of the development ones, and not the
# project itself (the app has that in its own folder). packaging/build_mac.sh gives uv the same
# arguments to write the file that pip is told to keep to (a test sees to it that they agree).
EXPORT_ARGUMENTS = (
    "export",
    "--locked",
    "--no-dev",
    "--no-hashes",
    "--no-emit-project",
    "--no-annotate",
    "--format",
    "requirements-txt",
)

# A line of the export: "certifi==2026.7.22", or "model @ <url of a wheel>", then perhaps
# " ; <marker>" for the systems it is meant for.
_REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*"
    r"(?:==\s*(?P<version>\S+?)|@\s*(?P<url>\S+?))\s*"
    r"(?:;\s*(?P<marker>.+))?"
)


def locked_packages(
    export: str, environment: Mapping[str, str] | None = None
) -> dict[str, Version | None]:
    """The packages of ``uv export``'s text that apply to this system, by their canonical names.

    ``environment`` replaces parts of what the markers are read against (the running system);
    it is for tests. A package locked by the URL of a wheel has that wheel's version, and None
    when the URL is not a wheel's.
    """
    here = {"extra": "", **(environment or {})}
    locked: dict[str, Version | None] = {}
    for line in export.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):  # a comment, or an option such as --index-url
            continue
        found = _REQUIREMENT.fullmatch(line)
        if found is None:
            raise ValueError(f"cannot read this line of uv's export: {line!r}")
        if found["marker"] and not Marker(found["marker"]).evaluate(here):
            continue
        locked[canonicalize_name(found["name"])] = (
            Version(found["version"]) if found["version"] else _version_of_wheel(found["url"])
        )
    return locked


def _version_of_wheel(url: str) -> Version | None:
    try:
        return parse_wheel_filename(url.rsplit("/", 1)[-1])[1]
    except InvalidWheelFilename:
        return None


def bundled_packages(app_packages: Path) -> dict[str, Version]:
    """The packages installed in ``app_packages``, by their canonical names."""
    return {
        canonicalize_name(dist.metadata["Name"]): Version(dist.version)
        for dist in distributions(path=[str(app_packages)])
    }


def differences(bundle: Mapping[str, Version], locked: Mapping[str, Version | None]) -> list[str]:
    """One line for each difference between the packages in the app and the locked ones.

    A package the lock holds without a version only has to be in the app.
    """
    found = []
    for name in sorted(bundle.keys() | locked.keys()):
        if name not in locked:
            found.append(
                f"{name} {bundle[name]} is in the app, but uv.lock does not lock it for this Mac"
            )
        elif name not in bundle:
            wanted = f"{name} {locked[name]}" if locked[name] else name
            found.append(f"{wanted} is locked for this Mac, but is not in the app")
        elif locked[name] is not None and bundle[name] != locked[name]:
            found.append(f"{name} is {bundle[name]} in the app, {locked[name]} in uv.lock")
    return found


def main(arguments: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else list(arguments)
    if len(arguments) > 1:
        print(__doc__, file=sys.stderr)
        return 2
    app = Path(arguments[0]) if arguments else DEFAULT_APP
    app_packages = app / "Contents" / "Resources" / "app_packages"
    if not app_packages.is_dir():
        print(f"There is no app at {app}: build the app first.", file=sys.stderr)
        return 2
    uv = shutil.which("uv")
    if uv is None:
        print("uv was not found: it reads uv.lock.", file=sys.stderr)
        return 2
    export = subprocess.run(
        [uv, *EXPORT_ARGUMENTS], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if export.returncode != 0:
        print(export.stderr, file=sys.stderr)
        return 2
    bundle = bundled_packages(app_packages)
    locked = locked_packages(export.stdout)
    problems = differences(bundle, locked)
    if problems:
        print(f"The app does not match uv.lock ({len(problems)} differences):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(
        f"The app's {len(bundle)} packages are the {len(locked)} that uv.lock locks for this Mac,"
        " at the locked versions."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
