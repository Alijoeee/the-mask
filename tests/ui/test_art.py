"""The illustrations: PNG files drawn by tools/make_art.py, loaded with their pixel ratio, and the
widget that shows one in the colours of its appearance.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QSize, QSizeF
from PySide6.QtGui import QColor, QImage

from themask.ui import art, theme
from tools import make_art

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

# Every file of the art folder, with the size in pixels the picture is drawn at.
EXPECTED = {
    "mask-light.png": (112, 88),
    "mask-light@2x.png": (224, 176),
    "mask-dark.png": (112, 88),
    "mask-dark@2x.png": (224, 176),
    "check-light.png": (64, 64),
    "check-light@2x.png": (128, 128),
    "check-dark.png": (64, 64),
    "check-dark@2x.png": (128, 128),
}
ART_FOLDER = Path(art.__file__).resolve().parent


def test_every_picture_is_there_at_the_size_it_is_drawn_at(qapp: object) -> None:
    assert sorted(path.name for path in ART_FOLDER.glob("*.png")) == sorted(EXPECTED)
    for name, (width, height) in EXPECTED.items():
        picture = art.pixmap(name.removesuffix(".png"))
        assert not picture.isNull(), name
        assert picture.size() == QSize(width, height), name


def test_a_2x_picture_has_a_pixel_ratio_of_two_and_the_size_of_the_1x_one(qapp: object) -> None:
    for kind in ("mask", "check"):
        for appearance in ("light", "dark"):
            one = art.pixmap(f"{kind}-{appearance}")
            two = art.pixmap(f"{kind}-{appearance}@2x")
            assert one.devicePixelRatio() == 1 and two.devicePixelRatio() == 2
            assert two.deviceIndependentSize() == QSizeF(one.size())


def test_a_picture_that_is_not_there_is_an_error(qapp: object) -> None:
    with pytest.raises(FileNotFoundError, match="no-such-picture"):
        art.pixmap("no-such-picture")


def test_make_art_draws_the_committed_files_again_pixel_for_pixel(tmp_path: Path) -> None:
    written = make_art.make_art(tmp_path)
    assert sorted(path.name for path in written) == sorted(EXPECTED)
    for path in written:
        # The pixels, not the bytes: the PNG encoder differs from one Qt build to another.
        drawn, committed = QImage(str(path)), QImage(str(ART_FOLDER / path.name))
        assert not committed.isNull(), path.name
        assert drawn.size() == committed.size(), path.name
        assert drawn.format() == committed.format(), path.name
        assert drawn == committed, path.name


def test_make_art_draws_the_same_files_every_time(tmp_path: Path) -> None:
    first = {path.name: path.read_bytes() for path in make_art.make_art(tmp_path / "one")}
    second = {path.name: path.read_bytes() for path in make_art.make_art(tmp_path / "two")}
    assert first == second


def test_make_art_writes_to_the_art_folder_unless_told_otherwise(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert make_art.DEFAULT_OUT == ART_FOLDER
    assert make_art.main([str(tmp_path)]) == 0
    assert sorted(path.name for path in tmp_path.glob("*.png")) == sorted(EXPECTED)
    assert capsys.readouterr().out.count("\n") == len(EXPECTED)
    assert make_art.main(["one", "two"]) == 2  # more than a folder is a mistake


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_the_pictures_are_drawn_in_the_colours_of_the_theme(appearance: str) -> None:
    t = theme.tokens(appearance)
    colours = make_art.LIGHT if appearance == "light" else make_art.DARK
    assert QColor(*colours.accent) == QColor(t.accent)
    assert QColor(*colours.soft) == QColor(t.accent_soft)
    assert QColor(*colours.panel) == QColor(t.panel)


def pixel(name: str, x: int, y: int) -> QColor:
    """The colour at (x, y) of the 1x picture ``name``."""
    return art.pixmap(name).toImage().pixelColor(x, y)


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_the_mask_is_a_document_with_a_face_on_it(qapp: object, appearance: str) -> None:
    t = theme.tokens(appearance)
    name = f"mask-{appearance}"
    assert pixel(name, 2, 2).alpha() == 0  # transparent around the document
    assert pixel(name, 28, 14) == QColor(t.accent_soft)  # the page
    assert pixel(name, 56, 60) == QColor(t.panel)  # the face
    assert pixel(name, 46, 55) == QColor(t.accent)  # an eye
    assert pixel(name, 66, 55) == QColor(t.accent)  # the other
    edge = pixel(name, 22, 40)  # the edge of the page is a line in the accent
    assert edge.alpha() == 255 and edge != QColor(t.accent_soft)


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_the_check_is_a_document_with_a_round_check_on_it(qapp: object, appearance: str) -> None:
    t = theme.tokens(appearance)
    name = f"check-{appearance}"
    assert pixel(name, 2, 2).alpha() == 0
    assert pixel(name, 16, 14) == QColor(t.accent_soft)  # the page
    assert pixel(name, 44, 41) == QColor(t.panel)  # inside the round mark, above the check
    assert pixel(name, 43, 49).alpha() == 255 and pixel(name, 43, 49) != QColor(t.panel)  # the tick


def test_the_light_and_dark_pictures_differ(qapp: object) -> None:
    assert pixel("mask-light", 28, 14) != pixel("mask-dark", 28, 14)
    assert pixel("check-light", 16, 14) != pixel("check-dark", 16, 14)


# ---- the widget ---------------------------------------------------------------------------------


def test_an_illustration_has_the_size_of_its_picture(qtbot: QtBot) -> None:
    mask, check = art.Illustration("mask"), art.Illustration("check")
    qtbot.addWidget(mask)
    qtbot.addWidget(check)
    assert mask.size() == QSize(112, 88) and mask.sizeHint() == QSize(112, 88)
    assert check.size() == QSize(64, 64)


def test_an_unknown_kind_of_illustration_is_refused(qtbot: QtBot) -> None:
    with pytest.raises(KeyError):
        art.Illustration("cat")


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_an_illustration_is_drawn_in_the_appearance_of_its_palette(
    qtbot: QtBot, appearance: str
) -> None:
    t = theme.tokens(appearance)
    illustration = art.Illustration("mask")
    qtbot.addWidget(illustration)
    illustration.setPalette(theme.palette(appearance))
    picture = illustration.grab().toImage()
    assert picture.pixelColor(28, 14) == QColor(t.accent_soft)
    assert picture.pixelColor(46, 55) == QColor(t.accent)


def test_an_illustration_follows_a_change_of_palette(qtbot: QtBot) -> None:
    illustration = art.Illustration("check")
    qtbot.addWidget(illustration)
    illustration.setPalette(theme.palette("light"))
    light = illustration.grab().toImage().pixelColor(16, 14)
    illustration.setPalette(theme.palette("dark"))
    dark = illustration.grab().toImage().pixelColor(16, 14)
    assert light == QColor(theme.tokens("light").accent_soft)
    assert dark == QColor(theme.tokens("dark").accent_soft)


def test_a_disabled_illustration_is_drawn_dimmed(qtbot: QtBot) -> None:
    illustration = art.Illustration("mask")
    qtbot.addWidget(illustration)
    illustration.setPalette(theme.palette("light"))
    enabled = illustration.grab().toImage().pixelColor(46, 55)
    illustration.setEnabled(False)
    assert illustration.grab().toImage().pixelColor(46, 55) != enabled
