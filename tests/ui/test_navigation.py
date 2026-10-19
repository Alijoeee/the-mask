"""Moving between the screens: the tool bar, and the way from the review to the export dialog."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolBar

from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.model import Case, KeyEntry, PlaceholderType
from themask.placeholders import find_placeholders
from themask.ui.cases_screen import CasesScreen
from themask.ui.export_dialog import ExportDialog
from themask.ui.main_window import MainWindow
from themask.ui.settings_screen import SettingsScreen

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from themask.ui.app import AppContext


def actions_of(window: MainWindow) -> dict[str, QAction]:
    """The actions of the window's tool bar, by their text."""
    bar = window.findChild(QToolBar)
    assert bar is not None
    return {action.text(): action for action in bar.actions()}


def test_the_tool_bar_moves_between_the_screens(qtbot: QtBot, app_ctx: AppContext) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    actions = actions_of(w)
    assert list(actions) == ["Home", "Review", "Restore", "Cases", "Settings"]
    for text, name in (("Restore", "restore"), ("Cases", "cases"), ("Settings", "settings")):
        actions[text].trigger()
        assert w.current_screen_name() == name
    actions["Home"].trigger()
    assert w.current_screen_name() == "home"


def test_the_review_can_be_returned_to_once_there_is_one(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    review = actions_of(w)["Review"]
    assert not review.isEnabled()  # nothing has been analysed yet
    with qtbot.waitSignal(w.analysisFinished, timeout=60000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert review.isEnabled() and w.current_screen_name() == "review"
    actions_of(w)["Settings"].trigger()
    assert w.current_screen_name() == "settings"
    review.trigger()
    assert w.current_screen_name() == "review"
    # The review is as it was left: the owner's work is not lost by looking at another screen.
    assert w.review_screen.group_count() > 0


def test_continuing_from_the_review_opens_the_export_dialog_over_it(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[object] = []
    monkeypatch.setattr(ExportDialog, "run", lambda self, *args: started.append(self))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=60000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    qtbot.mouseClick(w.review_screen.export_button, Qt.MouseButton.LeftButton)
    assert started == [w.export_dialog] and w.export_dialog is not None
    assert w.export_dialog.isVisible()
    assert w.current_screen_name() == "review"  # a dialog over the review, not a screen of its own


def test_the_work_done_in_the_review_survives_a_visit_to_another_screen(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=60000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    review = w.review_screen.review
    w.review_screen.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    switched_off = [g.id for g in review.groups if not g.enabled]
    assert len(switched_off) == 1
    w.show_home()
    actions_of(w)["Review"].trigger()
    assert w.review_screen.review is review
    assert [g.id for g in review.groups if not g.enabled] == switched_off
    item = w.review_screen.tree_item_for(switched_off[0])
    assert item.checkState(0) == Qt.CheckState.Unchecked


def test_the_cases_and_settings_screens_are_the_real_ones(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    assert isinstance(w.cases_screen, CasesScreen) and isinstance(w.settings_screen, SettingsScreen)
    actions_of(w)["Cases"].trigger()
    assert w.current_screen_name() == "cases" and w.cases_screen.isVisibleTo(w)
    assert not w.settings_screen.isVisibleTo(w)
    actions_of(w)["Settings"].trigger()
    assert w.settings_screen.isVisibleTo(w) and not w.cases_screen.isVisibleTo(w)


def test_the_cases_screen_shows_the_cases_as_the_store_holds_them_when_it_is_shown(
    qtbot: QtBot, app_ctx: AppContext, sample_case: Case
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    assert w.cases_screen.table.rowCount() == 0
    app_ctx.case_store.save(sample_case)  # an export made it while another screen was showing
    actions_of(w)["Cases"].trigger()
    assert w.cases_screen.table.rowCount() == 1


def test_the_settings_screen_shows_the_lists_as_they_are_kept_when_it_is_shown(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    app_ctx.user_lists.add_always("Project Falcon")  # what the review's "Always hide" button does
    actions_of(w)["Settings"].trigger()
    assert w.settings_screen.always_edit.toPlainText() == "Project Falcon"


def test_a_file_added_to_a_case_from_the_cases_screen_is_analysed_with_that_case(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    case = Case(
        "K4F7",
        datetime.now(UTC),
        ["earlier.docx"],
        [],
        [KeyEntry("[COMPANY_3]", PlaceholderType.COMPANY, "Northwind Trading B.V.", [])],
    )
    app_ctx.case_store.save(case)
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show_cases()
    with qtbot.waitSignal(w.analysisFinished, timeout=60000):
        w.cases_screen.addFilesRequested.emit([corpus / "supply-01.docx"], "K4F7")
    assert w.pending_case == case and w.current_screen_name() == "review"
    assert "[COMPANY_3]" in w.review_screen.review.reserved


def test_restore_from_a_case_shows_the_restore_screen_with_that_case(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    for case_id, days in (("K4F7", 0), ("B2C3", 5)):
        app_ctx.case_store.save(
            Case(
                case_id,
                datetime.now(UTC) - timedelta(days=days),
                [f"{case_id}.docx"],
                [],
                [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", [])],
            )
        )
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show_cases()
    w.cases_screen.table.selectRow(1)  # B2C3, the older one: not the one that is preselected
    qtbot.mouseClick(w.cases_screen.restore_button, Qt.MouseButton.LeftButton)
    assert w.current_screen_name() == "restore"
    assert w.restore_screen.case_combo.currentData() == "B2C3"


def test_the_restore_screen_shows_the_cases_as_the_store_holds_them_when_it_is_shown(
    qtbot: QtBot, app_ctx: AppContext, sample_case: Case
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    assert w.restore_screen.case_combo.count() == 0
    app_ctx.case_store.save(sample_case)  # an export made it while another screen was showing
    actions_of(w)["Restore"].trigger()
    assert w.current_screen_name() == "restore"
    assert w.restore_screen.case_combo.currentData() == sample_case.id


def test_a_masked_file_goes_from_the_export_through_the_cases_to_the_restored_file(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    """The round trip through the windows: the export dialog masks the file and saves the case, the
    Cases screen lists it, the Restore screen offers it and puts the real values back.
    """
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=60000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    qtbot.mouseClick(w.review_screen.export_button, Qt.MouseButton.LeftButton)
    dialog = w.export_dialog
    assert dialog is not None
    qtbot.waitUntil(lambda: dialog.result is not None, timeout=60000)
    result = dialog.result
    assert result is not None and result.case is not None and not result.blocked
    qtbot.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
    assert w.export_dialog is None

    w.show_cases()
    table = w.cases_screen.table
    first = table.item(0, 0)
    assert table.rowCount() == 1 and first is not None and first.text() == result.case.id

    masked = result.outputs[0]
    w.show_restore(result.case.id)
    w.restore_screen.load_file(masked)
    assert w.restore_screen.case_combo.currentData() == result.case.id
    with qtbot.waitSignal(w.restore_screen.restoreFinished, timeout=30000):
        qtbot.mouseClick(w.restore_screen.restore_button, Qt.MouseButton.LeftButton)
    assert w.restore_screen.report_label.text().endswith("0 need your check.")
    text = extract_text(
        DocxPackage.open(masked.with_name(f"{masked.stem} \N{EN DASH} restored.docx"))
    ).text
    assert all(entry.value in text for entry in result.case.entries)
    assert find_placeholders(text) == []  # every placeholder of the file was in the key
