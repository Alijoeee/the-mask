"""Moving between the screens: the tool bar, and the way from the review to the export dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolBar

from themask.ui.export_dialog import ExportDialog
from themask.ui.main_window import MainWindow

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
