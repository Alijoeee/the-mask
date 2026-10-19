"""The Settings window: the settings screen in a window of its own that does not block the app,
and what keeps it from showing lists that have changed since it was opened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from themask.ui.settings_screen import SettingsScreen, SettingsWindow

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from themask.ui.app import AppContext


@pytest.fixture
def window(qtbot: QtBot, app_ctx: AppContext) -> SettingsWindow:
    w = SettingsWindow(app_ctx)
    qtbot.addWidget(w)
    return w


def activate(window: SettingsWindow) -> None:
    """Tell the window that it became the active one, as the window system does."""
    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowActivate))


# ---- the window ---------------------------------------------------------------------------------


def test_the_window_is_a_dialog_called_settings_that_does_not_block(window: SettingsWindow) -> None:
    assert isinstance(window, QDialog)
    assert window.windowTitle() == "Settings"
    assert not window.isModal()  # the owner can go on working in the main window
    assert window.windowType() == Qt.WindowType.Tool  # a tool window, as the brief says


def test_the_window_holds_the_settings_screen(window: SettingsWindow) -> None:
    assert isinstance(window.settings_screen, SettingsScreen)
    assert window.settings_screen.isAncestorOf(window.settings_screen.save_button)
    assert window.isAncestorOf(window.settings_screen)
    assert window.settings_screen.about_label.text().startswith("The MASK")  # About stays inside


def test_the_window_is_big_enough_for_the_two_lists_and_the_form(window: SettingsWindow) -> None:
    assert window.width() >= 640 and window.height() >= 560


def test_escape_closes_the_window(qtbot: QtBot, window: SettingsWindow) -> None:
    window.show()
    qtbot.waitExposed(window)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isVisible()


def test_the_window_shows_the_lists_as_they_are_kept_when_it_opens(
    qtbot: QtBot, window: SettingsWindow, app_ctx: AppContext
) -> None:
    app_ctx.user_lists.add_always("Project Falcon")
    window.show()
    qtbot.waitExposed(window)
    assert window.settings_screen.always_edit.toPlainText() == "Project Falcon"
    window.settings_screen.always_edit.setPlainText("typed, not saved")
    window.hide()
    window.show()  # what was typed and not saved is dropped, as when the screen was left
    assert window.settings_screen.always_edit.toPlainText() == "Project Falcon"


# ---- the lists that changed meanwhile -----------------------------------------------------------


def test_a_screen_knows_whether_it_holds_edits_that_were_not_saved(
    window: SettingsWindow, app_ctx: AppContext
) -> None:
    screen = window.settings_screen
    assert not screen.has_unsaved_edits()
    screen.always_edit.setPlainText("Project Falcon")
    assert screen.has_unsaved_edits()
    screen.reload()
    assert not screen.has_unsaved_edits()
    screen.retention_spin.setValue(screen.retention_spin.value() + 1)
    assert screen.has_unsaved_edits()


def test_a_screen_knows_whether_what_is_kept_changed_since_it_showed_it(
    window: SettingsWindow, app_ctx: AppContext
) -> None:
    screen = window.settings_screen
    assert not screen.is_stale()
    app_ctx.user_lists.add_never("the Mill")  # what the review's "Never hide" button does
    assert screen.is_stale()
    screen.reload()
    assert not screen.is_stale()
    app_ctx.settings.retention_days = 7
    assert screen.is_stale()


def test_saving_leaves_the_screen_with_nothing_unsaved_and_nothing_stale(
    window: SettingsWindow, app_ctx: AppContext, data_dir: Path
) -> None:
    screen = window.settings_screen
    screen.always_edit.setPlainText("Project Falcon\n\nProject Falcon\nOther")
    screen.save_button.click()
    assert app_ctx.user_lists.always_hide == ["Project Falcon", "Other"]
    assert not screen.has_unsaved_edits() and not screen.is_stale()


def test_a_window_that_becomes_active_shows_the_lists_that_changed_meanwhile(
    qtbot: QtBot, window: SettingsWindow, app_ctx: AppContext
) -> None:
    window.show()
    qtbot.waitExposed(window)
    app_ctx.user_lists.add_always("Project Falcon")  # added in the review, with this window open
    assert window.settings_screen.always_edit.toPlainText() == ""
    activate(window)
    assert window.settings_screen.always_edit.toPlainText() == "Project Falcon"


def test_a_window_that_becomes_active_keeps_what_was_typed(
    qtbot: QtBot, window: SettingsWindow, app_ctx: AppContext
) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.settings_screen.never_edit.setPlainText("typed, not saved")
    app_ctx.user_lists.add_always("Project Falcon")
    activate(window)
    assert window.settings_screen.never_edit.toPlainText() == "typed, not saved"
    assert window.settings_screen.always_edit.toPlainText() == ""  # nothing is thrown away


def test_a_window_that_becomes_active_with_nothing_new_leaves_its_message_alone(
    qtbot: QtBot, window: SettingsWindow, app_ctx: AppContext, data_dir: Path
) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.settings_screen.always_edit.setPlainText("Project Falcon")
    window.settings_screen.save_button.click()
    assert window.settings_screen.status_label.text() == "Saved."
    activate(window)
    assert window.settings_screen.status_label.text() == "Saved."
