"""The sidebar: three sections, the one that is chosen on the accent, and under them the note that
goes with the screen that is showing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from themask.model import PlaceholderType
from themask.ui import theme
from themask.ui.sidebar import Sidebar, SidebarItem
from themask.ui.theme import TYPE_COLOURS

if TYPE_CHECKING:
    from PySide6.QtGui import QImage
    from pytestqt.qtbot import QtBot


@pytest.fixture
def sidebar(qtbot: QtBot) -> Sidebar:
    bar = Sidebar()
    qtbot.addWidget(bar)
    bar.setPalette(theme.palette("light"))
    bar.resize(220, 560)
    return bar


def shown(sidebar: Sidebar, qtbot: QtBot) -> Sidebar:
    sidebar.show()
    qtbot.waitExposed(sidebar)
    sidebar.activateWindow()
    qtbot.waitUntil(sidebar.isActiveWindow, timeout=2000)
    return sidebar


# ---- the sections -------------------------------------------------------------------------------


def test_the_sidebar_is_220_wide_and_has_the_three_sections_in_order(sidebar: Sidebar) -> None:
    assert sidebar.minimumWidth() == sidebar.maximumWidth() == 220
    assert list(sidebar.items) == ["mask", "restore", "cases"]
    assert [item.text() for item in sidebar.items.values()] == ["Mask", "Restore", "Cases"]
    assert sidebar.accessibleName() == "Sections" and sidebar.objectName() == "sidebar"


def test_each_item_is_a_button_34_high_that_takes_the_focus_by_tab(sidebar: Sidebar) -> None:
    for item in sidebar.items.values():
        assert isinstance(item, SidebarItem)
        assert item.height() == 34 or item.minimumHeight() == item.maximumHeight() == 34
        assert item.focusPolicy() == Qt.FocusPolicy.TabFocus
        assert item.isCheckable()
        assert item.accessibleName() == item.text()


def test_the_mask_section_is_chosen_at_first(sidebar: Sidebar) -> None:
    assert sidebar.current() == "mask"
    assert [item.isChecked() for item in sidebar.items.values()] == [True, False, False]


def test_choosing_a_section_checks_that_one_alone(sidebar: Sidebar) -> None:
    sidebar.set_current("cases")
    assert sidebar.current() == "cases"
    assert [item.isChecked() for item in sidebar.items.values()] == [False, False, True]
    sidebar.set_current("restore")
    assert [item.isChecked() for item in sidebar.items.values()] == [False, True, False]
    sidebar.set_current(None)
    assert sidebar.current() is None and not any(i.isChecked() for i in sidebar.items.values())


def test_a_click_asks_for_the_section_and_leaves_the_choice_to_the_window(
    qtbot: QtBot, sidebar: Sidebar
) -> None:
    with qtbot.waitSignal(sidebar.sectionRequested, timeout=1000) as asked:
        sidebar.items["restore"].click()
    assert asked.args == ["restore"]
    assert sidebar.current() == "mask"  # nothing is chosen until the window says so


def test_a_click_on_the_chosen_section_asks_for_it_too(qtbot: QtBot, sidebar: Sidebar) -> None:
    # On the review screen the Mask item is chosen, and clicking it goes back to the home screen.
    with qtbot.waitSignal(sidebar.sectionRequested, timeout=1000) as asked:
        sidebar.items["mask"].click()
    assert asked.args == ["mask"] and sidebar.items["mask"].isChecked()


def test_the_sections_can_be_switched_off_and_on(qtbot: QtBot, sidebar: Sidebar) -> None:
    sidebar.set_navigation_enabled(False)
    assert not any(item.isEnabled() for item in sidebar.items.values())
    with qtbot.assertNotEmitted(sidebar.sectionRequested):
        sidebar.items["cases"].click()  # a disabled button takes no click
    sidebar.set_navigation_enabled(True)
    assert all(item.isEnabled() for item in sidebar.items.values())


# ---- the keyboard -------------------------------------------------------------------------------


def test_the_arrows_move_between_the_items_and_space_and_return_choose(
    qtbot: QtBot, sidebar: Sidebar
) -> None:
    shown(sidebar, qtbot)
    mask, restore, cases = sidebar.items.values()
    mask.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(mask.hasFocus, timeout=2000)
    QTest.keyClick(mask, Qt.Key.Key_Down)
    assert QApplication.focusWidget() is restore
    QTest.keyClick(restore, Qt.Key.Key_Down)
    assert QApplication.focusWidget() is cases
    QTest.keyClick(cases, Qt.Key.Key_Down)
    assert QApplication.focusWidget() is cases  # the last one stays
    QTest.keyClick(cases, Qt.Key.Key_Up)
    assert QApplication.focusWidget() is restore
    with qtbot.waitSignal(sidebar.sectionRequested, timeout=1000) as asked:
        QTest.keyClick(restore, Qt.Key.Key_Space)
    assert asked.args == ["restore"]
    with qtbot.waitSignal(sidebar.sectionRequested, timeout=1000) as asked:
        QTest.keyClick(restore, Qt.Key.Key_Return)
    assert asked.args == ["restore"]


def test_an_arrow_does_not_choose_by_itself(qtbot: QtBot, sidebar: Sidebar) -> None:
    shown(sidebar, qtbot)
    mask = sidebar.items["mask"]
    mask.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(mask.hasFocus, timeout=2000)
    with qtbot.assertNotEmitted(sidebar.sectionRequested):
        QTest.keyClick(mask, Qt.Key.Key_Down)


# ---- how an item is drawn -----------------------------------------------------------------------


def item_image(sidebar: Sidebar, name: str):  # type: ignore[no-untyped-def]
    item = sidebar.items[name]
    item.resize(200, 34)
    return item.grab().toImage()


def pixels_near(image: QImage, colour: str, x_from: int, x_to: int) -> int:
    """How many pixels of ``image`` between the columns ``x_from`` and ``x_to`` are (within a few
    levels of) ``colour``: the ink of an icon or a word, not its anti-aliased edge."""
    ink = QColor(colour)
    return sum(
        1
        for y in range(image.height())
        for x in range(max(0, x_from), min(image.width(), x_to))
        if max(
            abs(image.pixelColor(x, y).red() - ink.red()),
            abs(image.pixelColor(x, y).green() - ink.green()),
            abs(image.pixelColor(x, y).blue() - ink.blue()),
        )
        <= 12
    )


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_the_chosen_item_is_on_the_accent_with_its_icon_and_word_in_the_text_on_the_accent(
    sidebar: Sidebar, appearance: str
) -> None:
    """White on the light accent, the dark text colour on the dark one (ruling R124): the item is
    drawn in ``on_accent``, whatever that is, and nothing of it is white by assumption."""
    sidebar.setPalette(theme.palette(appearance))
    t = theme.tokens(appearance)
    image = item_image(sidebar, "mask")  # chosen at first
    assert image.pixelColor(150, 4) == QColor(t.accent)
    text_x = 10 + 18 + 10  # the word starts after the icon of 18 points and a gap of 10
    assert pixels_near(image, t.on_accent, 0, text_x) > 8  # the icon
    assert pixels_near(image, t.on_accent, text_x, 200) > 20  # the word


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_an_item_that_is_not_chosen_has_no_background_and_the_text_colour(
    sidebar: Sidebar, appearance: str
) -> None:
    sidebar.setPalette(theme.palette(appearance))
    t = theme.tokens(appearance)
    image = item_image(sidebar, "restore")
    assert image.pixelColor(150, 4) != QColor(t.accent)
    inks = {image.pixelColor(x, y).name() for y in range(34) for x in range(10, 120)}
    assert QColor(t.text).name() in inks  # the word and the icon are in the text colour


def test_the_chosen_item_has_corners_of_8(sidebar: Sidebar) -> None:
    image = item_image(sidebar, "mask")
    assert image.pixelColor(0, 0) != QColor(theme.tokens("light").accent)  # the corner is cut
    assert image.pixelColor(8, 1) == QColor(theme.tokens("light").accent)


def test_a_switched_off_item_is_drawn_dimmed(sidebar: Sidebar) -> None:
    t = theme.tokens("light")
    sidebar.set_navigation_enabled(False)
    image = item_image(sidebar, "mask")
    assert image.pixelColor(150, 4) != QColor(t.accent)
    assert image.pixelColor(150, 4).red() > QColor(t.accent).red()  # paler, towards the ground


def test_an_item_the_keyboard_focused_shows_a_ring_and_one_the_window_focused_does_not(
    qtbot: QtBot, sidebar: Sidebar
) -> None:
    shown(sidebar, qtbot)
    restore = sidebar.items["restore"]
    restore.resize(200, 34)
    plain = restore.grab().toImage()
    restore.setFocus(Qt.FocusReason.ActiveWindowFocusReason)  # as when the window opens
    qtbot.waitUntil(restore.hasFocus, timeout=2000)
    assert restore.grab().toImage() == plain  # no ring for that
    restore.clearFocus()
    restore.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(restore.hasFocus, timeout=2000)
    assert restore.grab().toImage() != plain
    restore.clearFocus()
    assert restore.grab().toImage() == plain


# ---- the notes under the sections ---------------------------------------------------------------


def visible_texts(sidebar: Sidebar) -> list[str]:
    return [
        label.text()
        for label in sidebar.findChildren(QLabel)
        if label.isVisibleTo(sidebar) and label.text()
    ]


def test_the_home_note_is_the_engine_status_and_no_longer_a_hint_to_the_menu(
    sidebar: Sidebar,
) -> None:
    sidebar.set_context("home")
    assert sidebar.context() == "home"
    texts = visible_texts(sidebar)
    assert "Engine ready · offline" in texts
    # The Settings are a button now (see below), not a sentence about the application menu.
    assert not any("The MASK ›" in text for text in texts)
    assert sidebar.engine_dot.state() == "ready"


def test_the_engine_status_follows_the_engine(sidebar: Sidebar) -> None:
    sidebar.set_engine_state("loading")
    assert sidebar.engine_label.text() == "Loading the engine…"
    assert sidebar.engine_dot.state() == "loading"
    sidebar.set_engine_state("problem")
    assert sidebar.engine_label.text() == "The engine is not available"
    assert sidebar.engine_dot.state() == "problem"
    sidebar.set_engine_state("ready")
    assert sidebar.engine_label.text() == "Engine ready · offline"
    with pytest.raises(ValueError, match="asleep"):
        sidebar.set_engine_state("asleep")


@pytest.mark.parametrize("appearance", ["light", "dark"])
def test_the_status_dot_is_green_red_or_grey(sidebar: Sidebar, appearance: str) -> None:
    sidebar.setPalette(theme.palette(appearance))
    t = theme.tokens(appearance)
    dot = sidebar.engine_dot
    for state, colour in (("ready", t.success), ("problem", t.danger), ("loading", t.tertiary)):
        sidebar.set_engine_state(state)
        assert dot.grab().toImage().pixelColor(dot.width() // 2, dot.height() // 2) == QColor(
            colour
        )


def test_the_review_note_is_the_legend_of_the_colours(sidebar: Sidebar) -> None:
    sidebar.set_context("review")
    assert sidebar.context() == "review"
    texts = visible_texts(sidebar)
    assert texts[0] == "Legend"
    assert {"Person", "Company", "Amount", "Address", "E-mail", "IBAN"} <= set(texts)
    assert "Engine ready · offline" not in texts
    expected = {
        "Person": PlaceholderType.PERSON,
        "Company": PlaceholderType.COMPANY,
        "Amount": PlaceholderType.AMOUNT,
        "Address": PlaceholderType.ADDRESS,
        "E-mail": PlaceholderType.EMAIL,
        "IBAN": PlaceholderType.IBAN,
    }
    assert set(sidebar.legend) == set(expected)
    for name, swatch in sidebar.legend.items():
        centre = swatch.grab().toImage().pixelColor(swatch.width() // 2, swatch.height() // 2)
        assert centre == QColor(TYPE_COLOURS[expected[name]]), name


def test_the_restore_note_is_the_one_of_the_mockup(sidebar: Sidebar) -> None:
    sidebar.set_context("restore")
    note = (
        "The restored file is written next to the AI’s file, never over it."
        " Copied text is on the clipboard in clear."
    )
    assert visible_texts(sidebar) == [note]


def test_the_cases_note_says_how_long_a_case_is_kept(sidebar: Sidebar) -> None:
    sidebar.set_context("cases")
    note = (
        "A case expires 30 days after its export (change it in Settings)."
        " An expired or deleted case can never restore its files."
    )
    assert visible_texts(sidebar) == [note]
    sidebar.set_retention_days(14)
    assert "expires 14 days after" in visible_texts(sidebar)[0]
    sidebar.set_retention_days(1)
    assert "expires 1 day after" in visible_texts(sidebar)[0]


def test_only_the_note_of_the_screen_that_shows_is_shown(sidebar: Sidebar) -> None:
    for screen in ("home", "review", "restore", "cases"):
        sidebar.set_context(screen)
        assert sidebar.context() == screen
        assert len(visible_texts(sidebar)) >= 1
    with pytest.raises(KeyError):
        sidebar.set_context("settings")  # Settings has no screen in the stack any more


# ---- the Settings button ------------------------------------------------------------------------


def test_the_settings_button_is_at_the_foot_with_a_name_and_a_tooltip(sidebar: Sidebar) -> None:
    button = sidebar.settings_button
    assert isinstance(button, SidebarItem) and not button.isCheckable()
    assert button.text() == "Settings" and button.accessibleName() == "Settings"
    assert button.toolTip() == "Settings (⌘,)"
    assert button.focusPolicy() == Qt.FocusPolicy.TabFocus
    assert "settings" not in sidebar.items and list(sidebar.items) == ["mask", "restore", "cases"]
    sidebar.show()
    assert button.geometry().top() > sidebar.items["cases"].geometry().bottom()
    for screen in ("home", "review", "restore", "cases"):
        sidebar.set_context(screen)
        assert button.isVisibleTo(sidebar)  # on every screen, not only on the home note


def test_the_settings_button_asks_for_the_settings_and_never_takes_a_check(
    qtbot: QtBot, sidebar: Sidebar
) -> None:
    with qtbot.waitSignal(sidebar.settingsRequested, timeout=1000):
        sidebar.settings_button.click()
    assert not sidebar.settings_button.isChecked() and sidebar.current() == "mask"
    sidebar.settings_button.setEnabled(False)
    with qtbot.assertNotEmitted(sidebar.settingsRequested):
        sidebar.settings_button.click()


def test_the_settings_button_follows_the_keyboard(qtbot: QtBot, sidebar: Sidebar) -> None:
    shown(sidebar, qtbot)
    button = sidebar.settings_button
    button.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(button.hasFocus, timeout=2000)
    with qtbot.waitSignal(sidebar.settingsRequested, timeout=1000):
        QTest.keyClick(button, Qt.Key.Key_Return)
    with qtbot.waitSignal(sidebar.settingsRequested, timeout=1000):
        QTest.keyClick(button, Qt.Key.Key_Space)


def test_the_settings_button_is_not_switched_with_the_sections(sidebar: Sidebar) -> None:
    # The window switches it with the Settings action (it follows that action's state).
    sidebar.set_navigation_enabled(False)
    assert sidebar.settings_button.isEnabled()


def test_the_settings_button_has_hover_focus_and_dimmed_states(
    qtbot: QtBot, sidebar: Sidebar
) -> None:
    shown(sidebar, qtbot)
    button = sidebar.settings_button
    rest = button.grab().toImage()
    QTest.mouseMove(button, button.rect().center())
    qtbot.waitUntil(button.underMouse, timeout=2000)
    assert button.grab().toImage() != rest  # the hover fill
    QTest.mouseMove(sidebar, sidebar.rect().topLeft())
    qtbot.waitUntil(lambda: not button.underMouse(), timeout=2000)
    button.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(button.hasFocus, timeout=2000)
    assert button.grab().toImage() != rest  # the ring
    button.clearFocus()
    button.setEnabled(False)
    assert button.grab().toImage() != rest  # dimmed


def test_the_sidebar_has_no_colour_of_its_own_only_tokens() -> None:
    import re
    from pathlib import Path

    from themask.ui import sidebar as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source)
    assert not re.search(r"QColor\(\s*[\"'0-9]", source)
