"""The stylesheet of the window's own parts, drawn: the tool bar, the primary action, the sidebar's
notes, the card, the notices and the rows of the recent cases are in the colours of the tokens of
each appearance (the parse test of tests/ui/test_theme.py only says that Qt understands the rules).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QPushButton, QToolBar, QToolButton, QWidget

from themask.keystore.cases import CaseSummary
from themask.ui import theme
from themask.ui.drop_zone import DropZone
from themask.ui.home_screen import CaseRow
from themask.ui.sidebar import Sidebar
from themask.ui.widgets import LinkButton

if TYPE_CHECKING:
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot

APPEARANCES = ["light", "dark"]


def styled(qtbot: QtBot, widget: QWidget, appearance: str) -> QWidget:
    """``widget`` in the palette and the stylesheet of ``appearance``, shown."""
    qtbot.addWidget(widget)
    widget.setPalette(theme.palette(appearance))
    widget.setStyleSheet(theme.stylesheet(appearance))
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def inks(image: QImage) -> set[str]:
    """The colours (as ``#rrggbb``) that are in ``image``."""
    return {
        image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
    }


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_stylesheet_has_the_rules_of_the_windows_parts(appearance: str) -> None:
    sheet = theme.stylesheet(appearance)
    for selector in (
        "QToolBar#mainToolBar",
        "QToolButton#primaryAction",
        "QFrame#sidebar",
        "QLabel#sidebarNote",
        "QFrame#recentPanel",
        "QLabel#caseCode",
        "QPushButton#link",
    ):
        assert selector in sheet, selector
    t = theme.tokens(appearance)
    assert t.chrome in sheet and t.accent_hover in sheet and t.hairline in sheet
    assert "$" not in sheet


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_tool_bar_is_the_chrome_with_a_line_under_it(qtbot: QtBot, appearance: str) -> None:
    t = theme.tokens(appearance)
    bar = QToolBar()
    bar.setObjectName("mainToolBar")
    styled(qtbot, bar, appearance)
    bar.resize(300, 52)  # an unparented tool bar has no size of its own on every style
    image = bar.grab().toImage()
    assert image.pixelColor(150, 20) == QColor(t.chrome)
    assert image.pixelColor(150, image.height() - 1) == QColor(t.border)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_primary_action_is_an_accent_button_and_a_grey_one_when_it_is_off(
    qtbot: QtBot, appearance: str
) -> None:
    from PySide6.QtGui import QAction

    t = theme.tokens(appearance)
    bar = QToolBar()
    bar.setObjectName("mainToolBar")
    action = QAction("Export…", bar)
    bar.addAction(action)
    button = bar.widgetForAction(action)
    assert isinstance(button, QToolButton)
    button.setObjectName("primaryAction")
    button.setToolButtonStyle(button.toolButtonStyle().ToolButtonTextOnly)
    bar.resize(300, 60)
    styled(qtbot, bar, appearance)
    edge = button.grab().toImage()
    assert edge.pixelColor(4, button.height() // 2) == QColor(t.accent)
    assert QColor(t.on_accent).name() in inks(edge)  # the words: white, or dark on the dark accent
    action.setEnabled(False)
    qtbot.wait(20)
    off = button.grab().toImage()
    assert off.pixelColor(4, button.height() // 2) == QColor(t.border)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_sidebar_is_the_chrome_with_a_line_at_its_right_edge(
    qtbot: QtBot, appearance: str
) -> None:
    t = theme.tokens(appearance)
    sidebar = Sidebar()
    sidebar.resize(220, 400)
    styled(qtbot, sidebar, appearance)
    image = sidebar.grab().toImage()
    assert image.pixelColor(150, 300) == QColor(t.chrome)
    assert image.pixelColor(219, 300) == QColor(t.border)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_a_notice_is_drawn_in_the_notice_colours(qtbot: QtBot, appearance: str) -> None:
    t = theme.tokens(appearance)
    notice = QLabel("Not opened: old.doc.")
    notice.setObjectName("notice")
    notice.resize(300, 40)
    styled(qtbot, notice, appearance)
    image = notice.grab().toImage()
    assert image.pixelColor(150, 3) == QColor(t.notice_bg)  # above the text, inside the border
    assert image.pixelColor(0, 20) == QColor(t.notice_border)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_code_of_a_case_is_a_chip_on_the_soft_accent_with_the_text_for_it(
    qtbot: QtBot, appearance: str
) -> None:
    """The letters of the chip are the dark brown (light) or the pale sand (dark) made for the soft
    accent, not the accent itself, which is under 4.5:1 there (ruling R124)."""
    t = theme.tokens(appearance)
    created = datetime.now(UTC)
    summary = CaseSummary("K4F7", created, created + timedelta(days=30), ["supply-01.docx"], 14)
    row = CaseRow(summary, created, last=True)
    row.resize(600, 60)
    styled(qtbot, row, appearance)
    chip = row.code_label.grab().toImage()
    assert chip.pixelColor(chip.width() // 2, 2) == QColor(t.accent_soft)  # above the letters
    text_colours = {
        chip.pixelColor(x, y).name() for x in range(chip.width()) for y in range(chip.height())
    }
    assert QColor(t.accent_text_on_soft).name() in text_colours  # the letters
    assert QColor(t.accent).name() not in text_colours


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_a_primary_button_has_the_text_for_the_accent_on_the_accent(
    qtbot: QtBot, appearance: str
) -> None:
    t = theme.tokens(appearance)
    button = QPushButton("Copy instruction")
    button.setObjectName("primary")
    button.resize(180, 34)
    styled(qtbot, button, appearance)
    image = button.grab().toImage()
    assert image.pixelColor(5, button.height() // 2) == QColor(t.accent)
    assert QColor(t.on_accent).name() in inks(image)  # the words
    assert QColor(t.accent).name() in inks(image)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_hint_beside_the_choose_button_is_drawn_in_the_secondary_colour(
    qtbot: QtBot, appearance: str
) -> None:
    """ "or press ⌘O" is a hint on a card: the tertiary colour is for what is switched off (R124)."""
    t = theme.tokens(appearance)
    zone = DropZone(art="mask", shortcut_hint="or press ⌘O")
    zone.resize(500, 300)
    styled(qtbot, zone, appearance)
    colours = inks(zone.shortcut_label.grab().toImage())
    assert QColor(t.secondary).name() in colours
    assert QColor(t.tertiary).name() not in colours


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_a_row_of_the_list_has_a_hairline_under_it_unless_it_is_the_last(
    qtbot: QtBot, appearance: str
) -> None:
    t = theme.tokens(appearance)
    created = datetime.now(UTC)
    summary = CaseSummary("K4F7", created, created + timedelta(days=30), ["a.docx"], 3)
    middle, last = CaseRow(summary, created, last=False), CaseRow(summary, created, last=True)
    for row in (middle, last):
        row.resize(600, 60)
        styled(qtbot, row, appearance)
    assert middle.grab().toImage().pixelColor(300, middle.height() - 1) == QColor(t.hairline)
    assert last.grab().toImage().pixelColor(300, last.height() - 1) != QColor(t.hairline)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_a_link_is_the_accent_without_a_frame(qtbot: QtBot, appearance: str) -> None:
    t = theme.tokens(appearance)
    link = LinkButton("Restore")
    link.resize(80, 24)
    styled(qtbot, link, appearance)
    image = link.grab().toImage()
    colours = {
        image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
    }
    assert QColor(t.accent).name() in colours  # the words
    assert image.pixelColor(0, 0) != QColor(t.border_strong)  # and no border round them


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_a_disabled_card_dims_its_caption_with_its_title(qtbot: QtBot, appearance: str) -> None:
    t = theme.tokens(appearance)
    zone = DropZone()
    zone.resize(500, 260)
    styled(qtbot, zone, appearance)
    zone.setEnabled(False)
    qtbot.wait(20)
    hint = zone.hint_label.grab().toImage()
    inks = {hint.pixelColor(x, y).name() for x in range(hint.width()) for y in range(hint.height())}
    assert QColor(t.tertiary).name() in inks  # the caption is the colour of what is switched off
    assert QColor(t.secondary).name() not in inks
