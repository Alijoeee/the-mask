"""The look of the review: the colours of the theme in each part of the screen, in both
appearances; a screen that changes from light to dark while it is open; and the pictures of the
screen at 1180 by 760 pixels that the owner looks at (``THEMASK_SHOTS_DIR`` names the folder they
are saved in; else they are made in the test's own folder).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from tests.helpers import analysed
from tests.ui.review_samples import CONTRACT, FAMILY_SPECS, UNSURE_SPECS, custom_review
from themask.export import combined_text
from themask.review import ReviewState
from themask.ui import theme
from themask.ui.review_screen import ReviewScreen
from themask.ui.theme import TYPE_COLOURS

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from themask.detect.lists import CaseLists, UserLists
    from themask.detect.pipeline import CombinedText
    from themask.model import Analysis
    from themask.ui.app import AppContext

APPEARANCES = ["light", "dark"]
SIZE = QSize(1180, 760)  # the size of the approved mockups


@pytest.fixture
def look(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[QApplication]:
    """The application's palette, style sheet and font as they were, and no appearance forced:
    whatever a test applies is taken away again.
    """
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
def shots(tmp_path: Path) -> Path:
    """Where the pictures are saved."""
    named = os.environ.get("THEMASK_SHOTS_DIR")
    folder = Path(named) if named else tmp_path / "shots"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def appear(look: QApplication, monkeypatch: pytest.MonkeyPatch, appearance: str) -> None:
    """Give the application the look of ``appearance``, the way the app does at its start."""
    monkeypatch.setenv(theme.APPEARANCE_VARIABLE, appearance)
    theme.apply(look)


def open_screen(
    qtbot: QtBot,
    review: ReviewState,
    combined: CombinedText,
    selected: str | None = None,
    opened: str | None = None,
) -> ReviewScreen:
    """A review screen at the size of the mockups, shown, with the group ``selected`` (by its
    placeholder) selected and the group ``opened`` showing its places.
    """
    screen = ReviewScreen()
    qtbot.addWidget(screen)
    screen.resize(SIZE)
    screen.load(review, combined)
    screen.show()
    qtbot.waitExposed(screen)
    by_placeholder = {group.placeholder: group.id for group in review.groups}
    if opened is not None:
        screen.tree_item_for(by_placeholder[opened]).setExpanded(True)
    if selected is not None:
        item = screen.tree_item_for(by_placeholder[selected])
        screen.tree.setCurrentItem(item)
        item.setSelected(True)
    qtbot.wait(20)  # the list lays itself out
    return screen


def colour_in(image: QImage, screen: ReviewScreen, widget: object, x: float, y: float) -> str:
    """The colour of the pixel at (x, y) of ``widget`` in a picture of ``screen``."""
    point = widget.mapTo(screen, QPoint(round(x), round(y)))  # type: ignore[attr-defined]
    return image.pixelColor(point).name().upper()


# ---- the colours of each part --------------------------------------------------------------------


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_each_part_of_the_screen_has_the_colour_the_theme_gives_it(
    qtbot: QtBot, look: QApplication, monkeypatch: pytest.MonkeyPatch, appearance: str
) -> None:
    appear(look, monkeypatch, appearance)
    t = theme.tokens(appearance)
    combined, review = custom_review(CONTRACT, FAMILY_SPECS)
    screen = open_screen(qtbot, review, combined, selected="[COMPANY_1]")
    image = screen.grab().toImage()
    assert image.size() == SIZE

    assert colour_in(image, screen, screen.text, 4, 4) == t.panel.upper()  # the page
    assert colour_in(image, screen, screen.inspector, 8, 4) == t.ground.upper()  # the pane
    assert colour_in(image, screen, screen.inspector, 0, 300) == t.border.upper()  # between them

    first = screen.row_for(review.groups[0].id)  # selected
    box = first.row_box()
    assert colour_in(image, screen, first, box.left() + 10, box.top() + 2) == t.accent_soft.upper()
    other = screen.row_for(review.groups[1].id)
    box = other.row_box()
    assert colour_in(image, screen, other, box.left() + 10, box.top() + 2) == t.ground.upper()

    assert first.switch is not None  # on: the track is the accent, the knob what goes on it
    assert colour_in(image, screen, first.switch, 7, 9) == t.accent.upper()
    assert colour_in(image, screen, first.switch, 25, 9) == t.on_accent.upper()

    to_check = screen.row_for(next(g.id for g in review.groups if g.needs_check))
    pill = to_check.pill_box()
    assert pill is not None
    assert colour_in(image, screen, to_check, pill.left() + 2, pill.center().y()) == (
        t.notice_bg.upper()
    )
    chip = first.row_box().left() + 8 + 5
    assert colour_in(image, screen, first, chip, first.row_box().center().y()) == (
        TYPE_COLOURS[review.groups[0].type].upper()
    )


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_a_group_the_owner_is_asked_about_has_its_buttons_in_the_colours_of_the_theme(
    qtbot: QtBot, look: QApplication, monkeypatch: pytest.MonkeyPatch, appearance: str
) -> None:
    appear(look, monkeypatch, appearance)
    t = theme.tokens(appearance)
    combined, review = custom_review(CONTRACT, UNSURE_SPECS)
    screen = open_screen(qtbot, review, combined)
    asked = screen.row_for(next(g.id for g in review.groups if g.needs_check and not g.enabled))
    assert asked.hide_button is not None and asked.show_button is not None
    image = screen.grab().toImage()
    for button in (asked.hide_button, asked.show_button):
        # The buttons are the theme's: control colour, with the border-strong edge round them.
        assert colour_in(image, screen, button, button.width() / 2, 3) == t.control.upper()
        assert colour_in(image, screen, button, button.width() / 2, 0) == t.border_strong.upper()


def test_the_two_appearances_are_drawn_differently(
    qtbot: QtBot, look: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    combined, review = custom_review(CONTRACT, FAMILY_SPECS)
    pictures = []
    for appearance in APPEARANCES:
        appear(look, monkeypatch, appearance)
        pictures.append(open_screen(qtbot, review, combined).grab().toImage())
    light, dark = pictures
    assert light != dark
    assert light.pixelColor(4, 4) != dark.pixelColor(4, 4)


# ---- a change of appearance while the screen is open ---------------------------------------------------------


def lively(qtbot: QtBot, appearance: str) -> ReviewScreen:
    """A screen with a bit of everything: a question, a selection, places shown, a find."""
    combined, review = custom_review(CONTRACT, UNSURE_SPECS + FAMILY_SPECS[2:6])
    screen = open_screen(qtbot, review, combined, selected="[COMPANY_1]", opened="[PERSON_1]")
    screen.find_field.setText("Falcon")  # a hit selected in the page
    screen.find_field.setText("not in the contract")  # and the field marked red
    return screen


def settled(qtbot: QtBot, screen: ReviewScreen) -> QImage:
    """The picture of the screen once it has stopped changing: the clear button of the find field
    fades in when there is text in it.
    """
    previous = screen.grab().toImage()
    for _ in range(80):
        qtbot.wait(25)
        current = screen.grab().toImage()
        if current == previous:
            return current
        previous = current
    raise AssertionError("The screen never stopped changing.")


@pytest.mark.parametrize(("first", "then"), [("light", "dark"), ("dark", "light")])
def test_a_screen_that_changes_appearance_is_drawn_as_one_made_in_the_new_one(
    qtbot: QtBot,
    look: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    then: str,
) -> None:
    appear(look, monkeypatch, first)
    screen = lively(qtbot, first)
    settled(qtbot, screen)
    appear(look, monkeypatch, then)  # what the app does when the system changes
    changed = settled(qtbot, screen)
    fresh = settled(qtbot, lively(qtbot, then))
    assert changed.size() == fresh.size()
    assert changed == fresh


# ---- the pictures for the owner ---------------------------------------------------------------------------------


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_review_of_supply_01_is_drawn_at_the_size_of_the_mockups(
    qtbot: QtBot,
    look: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    app_ctx: AppContext,
    corpus: Path,
    shots: Path,
    appearance: str,
) -> None:
    appear(look, monkeypatch, appearance)
    sources, review = analysed(app_ctx, [corpus / "supply-01.docx"])
    screen = open_screen(qtbot, review, combined_text(sources), selected="[COMPANY_1]")
    picture = screen.grab()
    assert picture.size() == SIZE
    assert picture.save(str(shots / f"review-{appearance}.png"))
    assert screen.title() == ("supply-01.docx", "Review · 41 values found · 0 to check")
    assert screen.section_titles()[:2] == ["COMPANIES · 3", "PEOPLE · 4"]
    assert screen.counts_label.text() == "41 hidden · 0 to check · 0 shown on purpose"


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_review_of_supply_08_with_its_checks_and_a_question_is_drawn_too(
    qtbot: QtBot,
    look: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    lists: UserLists,
    supply_08_analysis: tuple[CombinedText, Analysis, CaseLists],
    shots: Path,
    appearance: str,
) -> None:
    # supply-08 has real groups to check: the pill, why the analysis was unsure, and (with one of
    # them switched off, as the owner would) the "Not sure — hide?" section.
    from themask.detect.lists import CaseLists

    appear(look, monkeypatch, appearance)
    combined, analysis, analysed_lists = supply_08_analysis
    case_lists = CaseLists(
        list(analysed_lists.always_hide),
        list(analysed_lists.never_hide),
        set(analysed_lists.defined_terms),
    )
    review = ReviewState.from_analysis(analysis, lists, case_lists)
    kraft = next(g for g in review.groups if g.canonical == "Kraft")
    assert kraft.needs_check
    kraft.enabled = False
    screen = open_screen(qtbot, review, combined, selected="[COMPANY_1]", opened="[COMPANY_1]")
    picture = screen.grab()
    assert picture.size() == SIZE
    assert picture.save(str(shots / f"review-{appearance}-checks.png"))
    assert screen.section_titles()[0] == "NOT SURE — HIDE? · 1"
    assert screen.row_for(kraft.id).data.caption.endswith("found by the model only")
    assert screen.title()[1] == "Review · 43 values found · 2 to check"
