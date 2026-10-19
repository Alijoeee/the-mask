"""Packaging: the icon script, and the Briefcase configuration that builds The MASK.app.

The build itself is ``packaging/build_mac.sh``; it takes minutes and downloads Briefcase's Python,
so no test runs it. These tests pin what it reads: the configuration in ``pyproject.toml``, read
by Briefcase's own parser (the one ``briefcase create`` uses), and the icon the configuration
names. Briefcase passes over a missing icon with a notice and uses its own, so a misspelt icon
path would otherwise go unseen.
"""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
import sys
import tomllib
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from briefcase.config import parse_config
from PIL import Image

from themask.about import APP_NAME, VERSION
from tools.check_bundle_lock import EXPORT_ARGUMENTS

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
MAKE_ICON = ROOT / "packaging" / "make_icon.py"
BUILD_SCRIPT = ROOT / "packaging" / "build_mac.sh"
APP = "themask"  # the app's name in [tool.briefcase.app.themask], and its Python package

# The names iconutil gives the files of an .iconset, and the size in pixels of each.
ICONSET = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def read_briefcase_config() -> tuple[dict[str, Any], MagicMock]:
    """The macOS app as Briefcase reads it from pyproject.toml, and the console it reported to."""
    console = MagicMock()
    _, apps = parse_config(PYPROJECT, platform="macOS", output_format="app", console=console)
    return apps[APP], console


@functools.cache
def vtool_works() -> bool:
    """Whether ``vtool`` is there and runs. Without Xcode's command line tools, /usr/bin/vtool is
    only a stub that asks to install them, so ``vtool -h`` is tried once: it prints its usage.
    """
    if shutil.which("vtool") is None:
        return False
    try:
        probe = subprocess.run(
            ["vtool", "-h"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "-show-build" in probe.stdout + probe.stderr


def padded(version: tuple[int, ...]) -> tuple[int, int, int]:
    """A version as exactly three numbers, so that 26, 26.0 and 26.0.0 are the same version."""
    major, minor, patch = (*version, 0, 0, 0)[:3]
    return major, minor, patch


def macos_needed_by(module: Path) -> tuple[int, ...]:
    """The macOS version the arm64 slice of the Mach-O file ``module`` says it needs (its minos)."""
    shown = subprocess.run(
        ["vtool", "-arch", "arm64", "-show-build", str(module)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    match = re.search(r"minos (\d+(?:\.\d+)*)", shown)
    assert match, f"{module.name} names no minimum macOS version"
    return tuple(int(part) for part in match.group(1).split("."))


def package_dir(package: str) -> Path:
    """The folder of an installed package."""
    spec = find_spec(package)
    assert spec is not None and spec.submodule_search_locations, f"{package} is not installed"
    return Path(next(iter(spec.submodule_search_locations)))


def python_modules_of(package: str) -> list[Path]:
    """The compiled Python modules (``*.abi3.so``) that sit directly in an installed package."""
    return sorted(package_dir(package).glob("*.abi3.so"))


def test_briefcase_installs_exactly_the_runtime_dependencies() -> None:
    # Briefcase adds [project].dependencies to the app's requirements by itself, so the app
    # section lists none of its own: a copy would be installed twice and could drift.
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    config, _ = read_briefcase_config()
    assert config["requires"] == project["dependencies"]


def test_briefcase_reads_the_configuration_without_a_warning() -> None:
    _, console = read_briefcase_config()
    console.warning_banner.assert_not_called()
    console.warning.assert_not_called()


def test_the_bundle_carries_the_name_and_version_the_app_reports() -> None:
    # The name of The MASK.app, and of its data folder (paths.py), both come from APP_NAME.
    config, _ = read_briefcase_config()
    assert config["formal_name"] == APP_NAME
    assert config["version"] == VERSION


def test_the_sources_icon_and_architecture_are_those_of_the_plan() -> None:
    config, _ = read_briefcase_config()
    assert config["sources"] == ["src/themask"]
    assert (ROOT / "src" / "themask" / "__main__.py").is_file()  # what the stub binary runs
    assert (ROOT / f"{config['icon']}.icns").is_file()
    assert config["universal_build"] is False  # one slice (arm64), as the plan says


def test_the_bundle_asks_for_a_macos_new_enough_for_pyside6() -> None:
    # Ruling R92: Info.plist declares what the wheels support, not the lowest macOS that pip
    # would accept. The PySide6 wheels are tagged 14.0, but their Python modules are marked 26.0.
    if not vtool_works():
        pytest.skip("vtool is not available: it comes with Xcode's command line tools")
    modules = python_modules_of("PySide6") + python_modules_of("shiboken6")
    assert modules
    needed = max(padded(macos_needed_by(module)) for module in modules)
    config, _ = read_briefcase_config()
    declared = padded(tuple(int(part) for part in config["min_os_version"].split(".")))
    assert declared >= needed


def test_briefcase_installs_the_versions_uv_locks() -> None:
    # Ruling R93. pip would take the newest version of every package nothing pins (certifi and
    # filelock were newer than uv.lock in the first build). Briefcase gives pip the file that
    # build_mac.sh makes from uv.lock; "./" is the one form of path Briefcase resolves against the
    # project folder, and a file that is not there stops pip instead of being passed over.
    config, _ = read_briefcase_config()
    assert config["requirement_installer_args"] == ["--constraint", "./build/constraints.txt"]
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    # The script writes that file, from the same list of packages the check of the bundle reads.
    assert f"uv {' '.join(EXPORT_ARGUMENTS)} -o build/constraints.txt" in script
    assert "tools.check_bundle_lock" in script


def test_the_cleanup_paths_drop_what_the_app_never_runs() -> None:
    # Ruling R94. Briefcase removes these globs from the bundle, and passes over one that matches
    # nothing in silence, so a misspelt path would go on shipping what it was meant to drop.
    config, _ = read_briefcase_config()
    cleanup = config["cleanup_paths"]
    assert all(path.startswith("**/") for path in cleanup)
    inside = [path.removeprefix("**/") for path in cleanup]
    assert {
        "app_packages/bin",  # the console scripts pip wrote: each starts with the build's path
        "PySide6/Designer.app",
        "PySide6/Assistant.app",
        "PySide6/Linguist.app",
        "PySide6/Qt/qml",
        "PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.dylib",
    } <= set(inside)
    assert not any(".framework" in path for path in inside)  # Qt's frameworks stay
    # These globs name what the macOS wheel holds (Designer.app, Qt/qml): only the Mac checks them.
    if sys.platform != "darwin":
        return
    pyside6 = package_dir("PySide6")
    for path in inside:
        if path.startswith("PySide6/"):
            assert list(pyside6.glob(path.removeprefix("PySide6/"))), f"{path} is not in PySide6"


def test_the_build_script_is_valid_bash() -> None:
    done = subprocess.run(
        ["bash", "-n", str(BUILD_SCRIPT)], capture_output=True, text=True, timeout=60, check=False
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(shutil.which("iconutil") is None, reason="iconutil is part of macOS")
def test_make_icon_builds_the_png_and_an_icns_with_every_size(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(MAKE_ICON), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    with Image.open(tmp_path / "themask-1024.png") as master:
        assert master.size == (1024, 1024)
        assert master.mode == "RGBA"
        assert master.getpixel((0, 0))[3] == 0  # the corner is transparent: a rounded square

    icns = tmp_path / "themask.icns"
    data = icns.read_bytes()
    assert data[:4] == b"icns"
    assert int.from_bytes(data[4:8], "big") == len(data)  # the length in the header is the file's

    # iconutil takes the file apart again: the ten sizes of an app icon are all inside.
    iconset = tmp_path / "check.iconset"
    subprocess.run(
        ["iconutil", "--convert", "iconset", "--output", str(iconset), str(icns)],
        capture_output=True,
        timeout=120,
        check=True,
    )
    sizes = {}
    for path in iconset.glob("*.png"):
        with Image.open(path) as image:
            sizes[path.name] = image.width
            assert image.size == (image.width, image.width)
    assert sizes == ICONSET
