"""The screens in the window's shell: what each puts in the tool bar (title, caption, primary
action), that one accent button shows at a time, and that the shortcut for Find is bound once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QPushButton, QToolButton

from tests.helpers import simulate_ai
from tests.ui.review_samples import CONTRACT, FAMILY_SPECS, custom_review
from themask.ui.main_window import MainWindow

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from themask.model import Case
    from themask.ui.app import AppContext

ANALYSIS_TIMEOUT = 60_000


@pytest.fixture
def window(qtbot: QtBot, app_ctx: AppContext) -> MainWindow:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.resize(1180, 760)
    return w


def analysed(qtbot: QtBot, w: MainWindow, corpus: Path) -> None:
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)


def accent_buttons(w: MainWindow) -> list[str]:
    """The accent ("primary") buttons that show on the screen that shows, window's included."""
    found = [
        b.text()
        for b in w.findChildren(QPushButton)
        if b.objectName() == "primary" and b.isVisibleTo(w) and b.parent() is not None
    ]
    action = w.toolbar.widgetForAction(w.primary_action)
    assert isinstance(action, QToolButton)
    if action.isVisibleTo(w):
        found.append(action.text())
    return found


def test_flipping_a_switch_in_the_review_changes_the_caption_of_the_tool_bar(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    analysed(qtbot, window, corpus)
    combined, state = custom_review(CONTRACT, FAMILY_SPECS)
    window.review_screen.load(state, combined)
    fatma = next(g for g in state.groups if g.canonical == "Ms Fatma Yildiz")
    before = window.title_block.caption_label.text()
    assert before == window.review_screen.title()[1]
    window.review_screen.row_for(fatma.id).switch.click()
    after = window.title_block.caption_label.text()
    assert after != before
    assert after == window.review_screen.title()[1]
    assert after.endswith(f"{state.counts().needs_check} to check")
    assert window.title_block.title_label.text() == "supply-01.docx"


def test_the_review_primary_action_is_export_and_opens_the_export(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    analysed(qtbot, window, corpus)
    assert window.primary_action.text() == "Export…" and window.primary_action.isEnabled()
    window.primary_action.trigger()
    assert window.export_dialog is not None
    window.export_dialog.reject()


def test_the_restore_primary_action_follows_the_screen_and_runs_the_restore(
    qtbot: QtBot, window: MainWindow, exported: tuple[Path, Case]
) -> None:
    masked, case = exported
    window.show_screen("restore")
    assert window.title_block.title_label.text() == "Restore"
    assert window.primary_action.text() == "Restore" and not window.primary_action.isEnabled()
    assert window.restore_screen.restore_button.isHidden()
    ai = simulate_ai(masked, masked.parent / "ai.docx")
    window.restore_screen.load_file(ai)
    assert window.restore_screen.case_combo.currentData() == case.id
    assert window.primary_action.isEnabled()
    with qtbot.waitSignal(window.restore_screen.restoreFinished, timeout=30_000):
        window.primary_action.trigger()
    assert (masked.parent / "ai – restored.docx").exists()


def test_the_cases_primary_action_is_new_case_and_goes_home(window: MainWindow) -> None:
    window.show_screen("cases")
    assert window.primary_action.text() == "New case" and window.primary_action.isEnabled()
    assert window.title_block.title_label.text() == window.cases_screen.title()[0]
    window.primary_action.trigger()
    assert window.current_screen_name() == "home"


def test_the_screens_title_changes_reach_the_tool_bar(window: MainWindow) -> None:
    window.show_screen("cases")
    window.cases_screen.titleChanged.emit("Cases", "3 cases")
    assert window.title_block.caption_label.text() == "3 cases"
    window.show_screen("restore")
    window.restore_screen.titleChanged.emit("Restore", "a caption")
    assert window.title_block.caption_label.text() == "a caption"


@pytest.mark.parametrize("name", ["restore", "cases"])
def test_a_screen_shows_one_accent_button_and_it_is_the_tool_bars(
    window: MainWindow, name: str
) -> None:
    window.show()
    window.show_screen(name)
    assert accent_buttons(window) == [window.primary_action.text()]


def test_the_review_shows_one_accent_button(qtbot: QtBot, window: MainWindow, corpus: Path) -> None:
    window.show()
    analysed(qtbot, window, corpus)
    assert accent_buttons(window) == ["Export…"]
    assert window.review_screen.export_button.isHidden()


def test_find_is_bound_once_and_the_review_owns_it(window: MainWindow) -> None:
    find = QKeySequence(QKeySequence.StandardKey.Find)
    actions = [a for a in window.findChildren(QAction) if a.shortcut() == find]
    shortcuts = [c for c in window.findChildren(QShortcut) if c.key() == find]
    assert actions == [] and shortcuts == [window.review_screen.find_shortcut]


def test_a_long_file_list_is_cut_in_the_middle_in_the_case_box_and_the_code_stays(
    window: MainWindow, app_ctx: AppContext
) -> None:
    from datetime import UTC, datetime

    from themask.model import Case, KeyEntry, PlaceholderType

    name = "Master Services and Data Processing Agreement - Northwind.docx"
    entries = [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", [])]
    app_ctx.case_store.save(Case("TC9Z", datetime.now(UTC), [name], [], entries))
    window.show_restore()
    combo = window.restore_screen.case_combo
    text = combo.itemText(0)
    assert text.startswith("TC9Z · Master") and "\N{HORIZONTAL ELLIPSIS}" in text
    assert text.endswith("1 value") and ".docx" in text
    assert combo.itemData(0, Qt.ItemDataRole.ToolTipRole).count(name) == 1


def test_the_cases_expiry_cell_has_room_and_a_tool_tip(window: MainWindow) -> None:
    from themask.ui import cases_screen

    assert cases_screen.COLUMN_WIDTHS[cases_screen.EXPIRES_COLUMN] >= 200


def test_the_title_the_mac_title_bar_already_says_is_not_said_twice(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themask.ui import main_window

    window.show()
    monkeypatch.setattr(main_window.sys, "platform", "darwin")
    window.set_title(window.windowTitle(), "")
    assert window.title_block.title_label.isHidden()
    window.set_title("Other", "")
    assert not window.title_block.title_label.isHidden()
    monkeypatch.setattr(main_window.sys, "platform", "linux")
    window.set_title(window.windowTitle(), "")
    assert not window.title_block.title_label.isHidden()
