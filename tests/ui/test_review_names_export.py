"""Going on to the export with a name typed in the review (R127, fix round 1): the Export… button
does not take the keyboard on a Mac, so a name typed and not confirmed is given before the dialog
opens; a name the review refuses, or one that clashes with a value, stops the export in words.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton

from tests.ui.review_samples import CONTRACT, FAMILY_SPECS, custom_review
from themask.detect.lists import CaseLists, UserLists
from themask.review import ReviewState
from themask.ui import main_window
from themask.ui.export_dialog import ExportDialog
from themask.ui.main_window import MainWindow

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from themask.ui.app import AppContext


@pytest.fixture
def window(qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.resize(1180, 760)
    combined, state = custom_review(CONTRACT, FAMILY_SPECS)
    w.review_screen.load(state, combined)
    w.sources = []
    w._review_ready = True
    w.show_screen("review")
    w.show()
    monkeypatch.setattr(ExportDialog, "run", lambda self, *args: None)
    return w


def export_button(w: MainWindow) -> QToolButton:
    button = w.toolbar.widgetForAction(w.primary_action)
    assert isinstance(button, QToolButton)
    return button


def type_without_return(qtbot: QtBot, w: MainWindow, text: str) -> None:
    screen = w.review_screen
    group = screen.review.groups[0]
    item = screen.tree_item_for(group.id)
    screen.tree.setCurrentItem(item)
    item.setSelected(True)
    field = screen.inspector.name_panel.name_field
    field.setFocus()
    qtbot.keyClicks(field, text)


def test_a_typed_name_is_given_when_export_is_clicked_without_return(
    qtbot: QtBot, window: MainWindow
) -> None:
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=3000)
    export_button(window).setFocusPolicy(Qt.FocusPolicy.TabFocus)  # as on a Mac
    type_without_return(qtbot, window, "Provider")
    qtbot.mouseClick(export_button(window), Qt.MouseButton.LeftButton)
    assert window.review_screen.review.groups[0].label == "Provider"
    assert window.export_dialog is not None  # and the export went on


def test_a_refused_typed_name_stops_the_export_with_the_reason_on_screen(
    qtbot: QtBot, window: MainWindow
) -> None:
    type_without_return(qtbot, window, "Bad [x]")
    window.show_export()
    assert window.export_dialog is None
    panel = window.review_screen.inspector.name_panel
    assert "square brackets" in panel.message_label.text()
    assert window.review_screen.review.groups[0].label is None


def test_a_name_that_clashes_with_a_value_stops_the_export_in_words(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    combined, state = custom_review(CONTRACT, FAMILY_SPECS)
    first = state.groups[0]
    state = ReviewState(
        state.text,
        state.groups,
        [],
        UserLists([], []),
        CaseLists([], [], set()),
        reserved=[first.placeholder],
        reserved_labels={first.placeholder: "Supplies"},
    )
    window.review_screen.load(state, combined)
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, message: shown.append(message))
    window.show_export()
    assert window.export_dialog is None
    assert shown == [state.label_problems()[0]]
