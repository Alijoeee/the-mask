"""Moving between the screens: the sidebar and the Settings action, and the way from the review to
the export dialog. (The window was rebuilt for the design pass: the five buttons of the old tool
bar became the sidebar's three sections, the primary action and the Settings action.)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt

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


def click_section(window: MainWindow, name: str) -> None:
    """Click the sidebar's section ``name`` ("mask", "restore" or "cases"), as the owner does."""
    window.sidebar.items[name].click()


# Renamed from test_the_tool_bar_moves_between_the_screens: the sidebar moves between them now.
def test_the_sidebar_moves_between_the_screens(qtbot: QtBot, app_ctx: AppContext) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    assert list(w.sidebar.items) == ["mask", "restore", "cases"]  # Home, Restore, Cases
    for section, name in (("restore", "restore"), ("cases", "cases")):
        click_section(w, section)
        assert w.current_screen_name() == name
    click_section(w, "mask")
    assert w.current_screen_name() == "home"


def test_the_review_can_be_returned_to_once_there_is_one(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    # On the home screen the primary action is "Review", which was the tool bar's Review button.
    review = w.primary_action
    assert review.text() == "Review" and not review.isEnabled()  # nothing has been analysed yet
    with qtbot.waitSignal(w.analysisFinished, timeout=60000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert w.current_screen_name() == "review"
    w.settings_action.trigger()  # a window over the review: the screen under it does not change
    assert w.settings_window.isVisible() and w.current_screen_name() == "review"
    click_section(w, "mask")
    assert w.current_screen_name() == "home" and review.isEnabled()
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
    w.primary_action.trigger()  # "Review"
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
    click_section(w, "cases")
    assert w.current_screen_name() == "cases" and w.cases_screen.isVisibleTo(w)
    assert not w.settings_window.isVisible()
    w.settings_action.trigger()  # the Settings are in a window of their own
    assert w.settings_screen.isVisibleTo(w.settings_window) and w.settings_window.isVisible()
    assert w.cases_screen.isVisibleTo(w)  # and the screen under it is as it was


def test_the_cases_screen_shows_the_cases_as_the_store_holds_them_when_it_is_shown(
    qtbot: QtBot, app_ctx: AppContext, sample_case: Case
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    assert w.cases_screen.table.rowCount() == 0
    app_ctx.case_store.save(sample_case)  # an export made it while another screen was showing
    click_section(w, "cases")
    assert w.cases_screen.table.rowCount() == 1


def test_the_settings_screen_shows_the_lists_as_they_are_kept_when_it_is_shown(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    app_ctx.user_lists.add_always("Project Falcon")  # what the review's "Always hide" button does
    w.settings_action.trigger()
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
    click_section(w, "restore")
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


def test_unanswered_guesses_are_asked_about_before_the_export_opens(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from themask.model import Finding, Group, PlaceholderType
    from themask.ui import main_window

    started: list[object] = []
    monkeypatch.setattr(ExportDialog, "run", lambda self, *args: started.append(self))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=60000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    review = w.review_screen.review
    guess = Group(
        "guess", PlaceholderType.COMPANY, "Equipment Services", set(),
        [Finding(PlaceholderType.COMPANY, 0, 1, "x", 0.6, "model")], "[COMPANY_77]", False, True,
    )  # fmt: skip
    review.groups.append(guess)
    asked: list[int] = []
    monkeypatch.setattr(main_window, "ask_unanswered", lambda parent, n: asked.append(n) or False)
    w.show_export()
    assert asked == [1] and started == [] and w.export_dialog is None  # "Back to review"
    monkeypatch.setattr(main_window, "ask_unanswered", lambda parent, n: asked.append(n) or True)
    w.show_export()
    assert asked == [1, 1] and started == [w.export_dialog]  # "Export anyway"
    w.export_dialog.reject()  # type: ignore[union-attr]
    review.answered.add("guess")
    w.show_export()
    assert asked == [1, 1]  # answered Show: not asked again
