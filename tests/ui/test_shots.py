"""The pictures of the windows (tools/make_shots.py): one of each screen in the light and the dark
appearance, in the colours of the theme, at the size asked for, with nothing of the owner's own
data in them and nothing left changed afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from themask.ui import home_screen, main_window, theme
from tools import make_shots

if TYPE_CHECKING:
    from pathlib import Path

SCREENS = ["home", "restore", "cases", "settings"]
NAMES = sorted(
    f"{screen}-{appearance}.png" for screen in SCREENS for appearance in theme.APPEARANCES
)


@pytest.fixture
def untouched_look(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[QApplication]:
    """The application's palette, style sheet and font as they were: the pictures apply a look."""
    monkeypatch.delenv(theme.APPEARANCE_VARIABLE, raising=False)
    palette, sheet, font = qapp.palette(), qapp.styleSheet(), qapp.font()
    yield qapp
    for follower in qapp.findChildren(theme.AppearanceFollower):
        follower.setParent(None)
        follower.deleteLater()
    qapp.setPalette(palette)
    qapp.setStyleSheet(sheet)
    qapp.setFont(font)


@pytest.fixture
def shots(untouched_look: QApplication, tmp_path: Path) -> dict[str, QImage]:
    """The pictures of one run, by file name."""
    written = make_shots.take(tmp_path / "shots")
    assert sorted(path.name for path in written) == NAMES
    return {path.name: QImage(str(path)) for path in written}


def test_there_is_a_picture_of_every_screen_in_both_appearances(shots: dict[str, QImage]) -> None:
    assert sorted(shots) == NAMES
    assert all(not image.isNull() for image in shots.values())


def test_the_screens_are_as_large_as_the_brief_says_and_the_settings_window_is_its_own_size(
    shots: dict[str, QImage],
) -> None:
    for name, image in shots.items():
        if name.startswith("settings"):
            assert (image.width(), image.height()) == (680, 640), name
        else:
            assert (image.width(), image.height()) == (1180, 760), name


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_the_home_picture_is_in_the_colours_of_its_appearance(
    shots: dict[str, QImage], appearance: str
) -> None:
    t = theme.tokens(appearance)
    image = shots[f"home-{appearance}.png"]
    assert image.pixelColor(600, 4) == QColor(t.chrome)  # the tool bar
    assert image.pixelColor(5, 400) == QColor(t.chrome)  # the sidebar
    assert image.pixelColor(300, 400) == QColor(t.ground)  # the screen
    assert image.pixelColor(700, 340) == QColor(t.panel)  # the card
    assert image.pixelColor(150, 80) == QColor(t.accent)  # the chosen section
    assert image.pixelColor(1170, 25) == QColor(t.border)  # the primary action: off at first


def test_the_two_appearances_differ_on_every_screen(shots: dict[str, QImage]) -> None:
    for screen in SCREENS:
        assert shots[f"{screen}-light.png"] != shots[f"{screen}-dark.png"], screen


def test_the_pictures_are_the_screens_they_are_named_for(shots: dict[str, QImage]) -> None:
    # The tool bar's primary action is the screen's own: Review (off), Restore (off), New case.
    t = theme.tokens("light")
    assert shots["home-light.png"].pixelColor(1170, 25) == QColor(t.border)  # "Review" is off
    assert shots["restore-light.png"].pixelColor(1170, 25) == QColor(t.border)  # no file yet
    assert shots["cases-light.png"].pixelColor(1170, 25) == QColor(t.accent)  # "New case" is on
    # The chosen section follows: Mask, Restore, Cases.
    for screen, y in (("home", 80), ("restore", 116), ("cases", 152)):
        assert shots[f"{screen}-light.png"].pixelColor(150, y) == QColor(t.accent), screen


def test_the_pictures_show_the_captions_of_the_mockups(
    untouched_look: QApplication, tmp_path: Path
) -> None:
    assert make_shots.NOW.hour == 15 and make_shots.NOW.minute == 30
    ctx = make_shots.made_up_context(tmp_path, None)
    first, second = ctx.case_store.list()
    assert home_screen.describe_case(first, make_shots.NOW) == (
        "Exported today at 14:02 · 14 values hidden · expires in 30 days"
    )
    assert home_screen.describe_case(second, make_shots.NOW) == (
        "Exported yesterday · 2 files · 21 values hidden · expires in 29 days"
    )


def test_nothing_the_pictures_change_stays_changed(
    untouched_look: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "dark")
    clock, animations = home_screen.current_time, main_window.ANIMATIONS
    make_shots.take(tmp_path)
    assert os.environ[theme.APPEARANCE_VARIABLE] == "dark"
    assert home_screen.current_time is clock and main_window.ANIMATIONS is animations


def test_the_environment_is_left_without_an_appearance_when_it_had_none(
    untouched_look: QApplication, tmp_path: Path
) -> None:
    make_shots.take(tmp_path)
    assert theme.APPEARANCE_VARIABLE not in os.environ


def test_a_size_can_be_asked_for(untouched_look: QApplication, tmp_path: Path) -> None:
    written = make_shots.take(tmp_path, size=(900, 600))
    image = QImage(str(next(path for path in written if path.name == "home-light.png")))
    assert (image.width(), image.height()) == (900, 600)


def test_the_picture_tool_takes_a_folder_and_a_size(
    untouched_look: QApplication, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert make_shots.main([str(tmp_path / "out"), "--size", "1000x700"]) == 0
    printed = capsys.readouterr().out.split()
    assert sorted(path.rsplit("/", 1)[-1] for path in printed) == NAMES
    assert QImage(printed[0]).width() == 1000


@pytest.mark.parametrize(
    "arguments",
    [[], ["a", "b"], ["out", "--size"], ["out", "--size", "big"], ["out", "--review"]],
    ids=["no folder", "two folders", "size missing", "size not numbers", "review missing"],
)
def test_the_picture_tool_refuses_arguments_it_cannot_use(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert make_shots.main(arguments) == 2
    assert "make_shots.py OUT_DIR" in capsys.readouterr().err
