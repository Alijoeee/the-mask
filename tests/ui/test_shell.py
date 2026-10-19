"""The shell of the window: the tool bar (the sidebar toggle, the title of the screen, its primary
action), the sidebar that follows the screens, the Settings action and its window, the crossfade
between screens and the way through the window with the keyboard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QToolBar,
    QToolButton,
    QWidget,
)

from themask.model import Case, KeyEntry, PlaceholderType
from themask.ui import main_window, theme
from themask.ui.export_dialog import ExportDialog
from themask.ui.main_window import MainWindow
from themask.ui.settings_screen import SettingsWindow

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from themask.ui.app import AppContext

ANALYSIS_TIMEOUT = 60_000


@pytest.fixture
def window(qtbot: QtBot, app_ctx: AppContext) -> MainWindow:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.resize(1180, 760)
    return w


def analysed(qtbot: QtBot, w: MainWindow, corpus: Path, name: str = "supply-01.docx") -> None:
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / name], redline_split=False)


def tool_button(w: MainWindow, action: QAction) -> QToolButton:
    button = w.toolbar.widgetForAction(action)
    assert isinstance(button, QToolButton)
    return button


def a_case(case_id: str = "K4F7") -> Case:
    entries = [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", [])]
    return Case(case_id, datetime.now(UTC), [f"{case_id}.docx"], [], entries)


# ---- the structure ------------------------------------------------------------------------------


def test_the_window_asks_for_the_unified_title_bar_and_tool_bar_of_the_mac(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[bool] = []
    monkeypatch.setattr(
        QMainWindow, "setUnifiedTitleAndToolBarOnMac", lambda self, on: asked.append(on)
    )
    qtbot.addWidget(MainWindow(app_ctx))
    assert asked == [True]


def test_the_tool_bar_is_the_only_one_and_cannot_be_moved_or_floated(window: MainWindow) -> None:
    assert window.findChildren(QToolBar) == [window.toolbar]
    assert not window.toolbar.isMovable() and not window.toolbar.isFloatable()
    assert window.toolbar.objectName() == "mainToolBar"
    assert window.toolbar.contextMenuPolicy() == Qt.ContextMenuPolicy.PreventContextMenu


def test_the_tool_bar_holds_the_toggle_the_title_and_the_primary_action_in_that_order(
    window: MainWindow,
) -> None:
    widgets = [window.toolbar.widgetForAction(action) for action in window.toolbar.actions()]
    assert widgets[0] is window.sidebar_toggle
    assert widgets[1] is window.title_block
    assert widgets[2] is tool_button(window, window.primary_action)
    assert len(widgets) == 3


def test_the_sidebar_stands_left_of_the_screens_and_is_220_wide(window: MainWindow) -> None:
    window.show()
    assert window.sidebar.width() == 220
    assert window.sidebar.x() < window._stack.x()
    assert window.centralWidget().isAncestorOf(window.sidebar)


def test_there_are_four_screens_in_the_stack_and_the_settings_are_not_one_of_them(
    window: MainWindow,
) -> None:
    assert window.screen_names() == ["home", "review", "restore", "cases"]
    assert window.current_screen_name() == "home"


# ---- the toggle of the sidebar ------------------------------------------------------------------


def test_the_toggle_is_an_icon_only_button_called_hide_sidebar(window: MainWindow) -> None:
    toggle = window.sidebar_toggle
    assert isinstance(toggle, QToolButton)
    assert toggle.accessibleName() == "Hide sidebar" and toggle.toolTip() == "Hide sidebar"
    assert toggle.text() == "" and toggle.size().width() == 30 and toggle.size().height() == 26
    assert toggle.focusPolicy() & Qt.FocusPolicy.TabFocus


def test_the_toggle_hides_the_sidebar_and_shows_it_again(window: MainWindow) -> None:
    window.show()
    assert window.sidebar.isVisible()
    window.sidebar_toggle.click()
    assert not window.sidebar.isVisible()
    assert window.sidebar_toggle.accessibleName() == "Show sidebar"
    assert window.sidebar_toggle.toolTip() == "Show sidebar"
    window.sidebar_toggle.click()
    assert window.sidebar.isVisible()
    assert window.sidebar_toggle.accessibleName() == "Hide sidebar"


def test_the_toggle_works_while_a_file_is_analysed(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    window.show()
    with qtbot.waitSignal(window.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        window.open_files([corpus / "supply-01.docx"], redline_split=False)
        assert window.sidebar_toggle.isEnabled()
        window.sidebar_toggle.click()
        assert not window.sidebar.isVisible()


# ---- the title of the screen --------------------------------------------------------------------


def test_the_title_block_is_two_lines_a_title_and_a_caption(window: MainWindow) -> None:
    block = window.title_block
    assert block.title_label.objectName() == "toolbarTitle"
    assert block.caption_label.objectName() == "toolbarCaption"
    assert block.title_label.alignment() & Qt.AlignmentFlag.AlignHCenter


@pytest.mark.parametrize(
    ("show", "title", "caption"),
    [
        ("show_home", "The MASK", ""),
        ("show_restore", "Restore", "Put the real values back into the file an AI tool returned"),
        (
            "show_cases",
            "Cases",
            "The keys that put real values back · kept on this Mac, encrypted",
        ),
    ],
)
def test_each_screen_has_the_title_and_caption_of_its_mockup(
    window: MainWindow, show: str, title: str, caption: str
) -> None:
    getattr(window, show)()
    assert window.title_block.title_label.text() == title
    assert window.title_block.caption_label.text() == caption
    assert window.title_block.caption_label.isHidden() == (caption == "")


def test_a_screen_can_set_its_own_title_and_caption(window: MainWindow) -> None:
    window.set_title("supply-01.docx", "Review · 14 values found · 2 to check")
    assert window.title_block.title_label.text() == "supply-01.docx"
    assert window.title_block.caption_label.text() == "Review · 14 values found · 2 to check"
    window.set_title("Only a title")
    assert window.title_block.caption_label.isHidden()


def test_the_title_of_a_screen_that_is_not_showing_is_kept_for_when_it_does(
    window: MainWindow,
) -> None:
    window.set_title("supply-01.docx", "Review · 3 values found · 0 to check", screen="review")
    assert window.title_block.title_label.text() == "The MASK"  # the home screen is showing
    window.set_title("nda.docx", "Review · 1 value found · 0 to check", screen="review")
    window._show("review")
    assert window.title_block.title_label.text() == "nda.docx"
    window.show_cases()
    assert window.title_block.title_label.text() == "Cases"


def test_the_review_is_titled_with_the_file_and_what_was_found(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    analysed(qtbot, window, corpus)
    counts = window.review_screen.review.counts()
    assert window.title_block.title_label.text() == "supply-01.docx"
    assert window.title_block.caption_label.text() == (
        f"Review · {counts.groups} values found · {counts.needs_check} to check"
    )


def test_a_review_of_several_files_names_them_all(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    with qtbot.waitSignal(window.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        window.open_files(
            [corpus / "supply-01.docx", corpus / "supply-02.docx"], redline_split=False
        )
    assert window.title_block.title_label.text() == "supply-01.docx, supply-02.docx"


def test_a_long_title_is_cut_short_in_a_narrow_window_and_the_primary_action_stays(
    qtbot: QtBot, window: MainWindow
) -> None:
    window.show()
    window.resize(620, 500)
    qtbot.waitExposed(window)
    long_title = ", ".join(f"contract-{n:02d}-with-a-long-name.docx" for n in range(1, 9))
    window.set_title(long_title, "Review · 14 values found · 2 to check")
    qtbot.waitUntil(
        lambda: window.title_block.title_label.displayed_text() != long_title, timeout=2000
    )
    shown = window.title_block.title_label.displayed_text()
    assert shown.endswith("…") and long_title.startswith(shown[:-1])
    assert window.title_block.title_label.text() == long_title  # a screen reader reads it all
    button = tool_button(window, window.primary_action)
    assert button.isVisible() and button.geometry().right() <= window.toolbar.width()
    assert window.sidebar_toggle.geometry().left() >= 0


# ---- the primary action -------------------------------------------------------------------------


def test_the_primary_action_has_the_text_of_the_screen_that_shows(window: MainWindow) -> None:
    assert isinstance(window.primary_action, QAction)
    assert window.primary_action.text() == "Review"
    window.show_restore()
    assert window.primary_action.text() == "Restore"
    window.show_cases()
    assert window.primary_action.text() == "New case"
    window.show_home()
    assert window.primary_action.text() == "Review"


def test_the_primary_action_of_the_home_screen_waits_for_an_analysis(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    assert not window.primary_action.isEnabled()
    assert not tool_button(window, window.primary_action).isEnabled()
    analysed(qtbot, window, corpus)
    assert window.current_screen_name() == "review"
    window.show_home()
    assert window.primary_action.isEnabled()
    window.primary_action.trigger()  # "Review": back to the review that was left
    assert window.current_screen_name() == "review"
    assert window.review_screen.group_count() > 0


def test_the_primary_action_of_the_review_is_the_export(
    qtbot: QtBot, window: MainWindow, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[object] = []
    monkeypatch.setattr(ExportDialog, "run", lambda self, *args: started.append(self))
    analysed(qtbot, window, corpus)
    assert window.primary_action.text() == "Export…" and window.primary_action.isEnabled()
    assert tool_button(window, window.primary_action).text() == "Export…"  # the dots are shown
    tool_button(window, window.primary_action).click()
    assert window.export_dialog is not None and started == [window.export_dialog]
    assert window.current_screen_name() == "review"  # a dialog over the review


def test_the_primary_action_of_the_cases_screen_starts_a_new_case(window: MainWindow) -> None:
    window.show_cases()
    assert window.primary_action.isEnabled()
    window.primary_action.trigger()
    assert window.current_screen_name() == "home"


def test_the_primary_action_of_the_restore_screen_restores_and_follows_the_button(
    qtbot: QtBot, window: MainWindow, app_ctx: AppContext
) -> None:
    window.show_restore()
    button = window.restore_screen.restore_button
    assert not button.isEnabled() and not window.primary_action.isEnabled()  # no case, no file
    clicked: list[bool] = []
    button.clicked.connect(lambda: clicked.append(True))
    button.setEnabled(True)
    assert window.primary_action.isEnabled()
    window.primary_action.trigger()
    assert clicked == [True]
    button.setEnabled(False)
    assert not window.primary_action.isEnabled()


def test_the_primary_action_is_off_while_a_file_is_analysed_and_on_after(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    window.show_cases()
    with qtbot.waitSignal(window.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        window.open_files([corpus / "supply-01.docx"], redline_split=False)
        assert window.is_analysing()
        assert window.current_screen_name() == "home"
        assert not window.primary_action.isEnabled()
    assert window.primary_action.isEnabled()  # the review: "Export…"


# ---- what the screens wire into -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["home", "restore", "cases"])
def test_show_screen_shows_a_screen_by_its_name(window: MainWindow, name: str) -> None:
    window.show_screen("cases" if name == "home" else "home")
    window.show_screen(name)
    assert window.current_screen_name() == name


def test_show_screen_makes_the_screen_up_to_date_as_its_own_show_does(
    window: MainWindow, app_ctx: AppContext
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    window.show_screen("cases")
    assert window.cases_screen.table.rowCount() == 1
    window.show_screen("restore")
    assert window.restore_screen.case_combo.currentData() == "K4F7"
    app_ctx.case_store.save(a_case("B2C3"))
    window.show_screen("home")
    assert {row.code_label.text() for row in window.home.recent.rows} == {"K4F7", "B2C3"}


def test_show_screen_shows_the_review_only_when_there_is_one(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    window.show_screen("review")
    assert window.current_screen_name() == "home"  # nothing was analysed yet
    analysed(qtbot, window, corpus)
    window.show_home()
    window.show_screen("review")
    assert window.current_screen_name() == "review"


@pytest.mark.parametrize("name", ["settings", "nowhere", ""])
def test_show_screen_refuses_a_name_that_is_no_screen(window: MainWindow, name: str) -> None:
    with pytest.raises(KeyError):
        window.show_screen(name)  # the Settings are a window: show_settings
    assert window.current_screen_name() == "home"


def test_set_primary_says_what_the_primary_action_of_a_screen_is_called_and_does(
    window: MainWindow,
) -> None:
    done: list[str] = []
    window.set_primary("cases", "Add a case", lambda: done.append("added"))
    window.show_cases()
    assert window.primary_action.text() == "Add a case" and window.primary_action.isEnabled()
    window.primary_action.trigger()
    assert done == ["added"]
    window.show_home()
    assert window.primary_action.text() == "Review"  # the other screens are as they were


def test_set_primary_changes_the_words_at_once_when_the_screen_shows(window: MainWindow) -> None:
    window.set_primary("home", "Look", lambda: None, lambda: True)
    assert window.primary_action.text() == "Look" and window.primary_action.isEnabled()


def test_the_primary_action_is_on_when_the_screen_says_and_off_while_a_file_is_analysed(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    ready: list[bool] = [False]
    window.set_primary("cases", "Go", lambda: None, lambda: ready[0])
    window.show_cases()
    assert not window.primary_action.isEnabled()
    ready[0] = True
    window.refresh_chrome()  # the screen's state changed
    assert window.primary_action.isEnabled()
    with qtbot.waitSignal(window.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        window.open_files([corpus / "supply-01.docx"], redline_split=False)
        window.refresh_chrome()
        assert not window.primary_action.isEnabled()  # "ready" said yes; the analysis says no


def test_set_primary_and_set_title_refuse_a_name_that_is_no_screen(window: MainWindow) -> None:
    with pytest.raises(KeyError):
        window.set_primary("settings", "Save", lambda: None)
    with pytest.raises(KeyError):
        window.set_title("x", "y", screen="settings")
    with pytest.raises(KeyError):
        window.add_toolbar_widget("settings", QWidget())


def test_a_widget_can_be_put_in_the_tool_bar_for_one_screen(
    qtbot: QtBot, window: MainWindow
) -> None:
    window.show()
    extra = QCheckBox("Redline split")
    window.add_toolbar_widget("cases", extra)
    assert not extra.isVisible()  # the home screen is showing
    window.show_cases()
    qtbot.waitUntil(extra.isVisible, timeout=2000)  # the tool bar lays out on its next turn
    widgets = [window.toolbar.widgetForAction(a) for a in window.toolbar.actions()]
    primary = tool_button(window, window.primary_action)
    assert widgets.index(extra) == widgets.index(primary) - 1  # just before the primary action
    window.show_restore()
    qtbot.waitUntil(lambda: not extra.isVisible(), timeout=2000)
    window.show_screen("cases")
    qtbot.waitUntil(extra.isVisible, timeout=2000)


# ---- the sidebar follows the screens ------------------------------------------------------------


def test_the_sidebar_shows_the_section_of_the_screen_that_shows(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    assert window.sidebar.current() == "mask"
    window.show_restore()
    assert window.sidebar.current() == "restore"
    window.show_cases()
    assert window.sidebar.current() == "cases"
    analysed(qtbot, window, corpus)
    assert window.current_screen_name() == "review" and window.sidebar.current() == "mask"


def test_a_click_on_a_section_shows_its_screen(window: MainWindow) -> None:
    window.sidebar.items["restore"].click()
    assert window.current_screen_name() == "restore"
    window.sidebar.items["cases"].click()
    assert window.current_screen_name() == "cases"
    window.sidebar.items["mask"].click()
    assert window.current_screen_name() == "home"


def test_the_mask_section_goes_home_from_the_review(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    analysed(qtbot, window, corpus)
    window.sidebar.items["mask"].click()
    assert window.current_screen_name() == "home"
    assert window.sidebar.current() == "mask"


def test_the_sidebar_is_off_while_a_file_is_analysed_and_on_again_after(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    items = list(window.sidebar.items.values())
    assert all(item.isEnabled() for item in items)
    with qtbot.waitSignal(window.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        window.open_files([corpus / "supply-01.docx"], redline_split=False)
        assert window.is_analysing() and not any(item.isEnabled() for item in items)
        window.sidebar.items["cases"].click()  # a switched-off button takes no click
        assert window.current_screen_name() == "home"
    assert all(item.isEnabled() for item in items)


def test_the_sidebar_is_on_again_when_the_analysis_fails(
    qtbot: QtBot, window: MainWindow, fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_window, "show_error", lambda parent, message: None)
    with qtbot.waitSignal(window.analysisFailed, timeout=10000):
        window.open_files([fixtures / "not-a-docx.doc"], redline_split=False)
        assert not window.sidebar.items["cases"].isEnabled()
    assert all(item.isEnabled() for item in window.sidebar.items.values())


def test_the_note_under_the_sections_follows_the_screen(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    assert window.sidebar.context() == "home"
    window.show_restore()
    assert window.sidebar.context() == "restore"
    window.show_cases()
    assert window.sidebar.context() == "cases"
    analysed(qtbot, window, corpus)
    assert window.sidebar.context() == "review"


def test_the_note_of_the_cases_screen_says_the_days_the_settings_keep_a_case(
    window: MainWindow, app_ctx: AppContext
) -> None:
    app_ctx.settings.retention_days = 14
    window.show_cases()
    assert "expires 14 days after" in window.sidebar.cases_note.text()


def test_the_engine_status_of_the_sidebar_follows_the_engine(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    from dataclasses import replace

    ctx = replace(app_ctx, engine=None)
    w = MainWindow(ctx, load_engine=lambda: app_ctx.engine)
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: w.home.drop_zone.isEnabled(), timeout=10000)
    assert w.sidebar.engine_label.text() == "Engine ready · offline"
    assert w.sidebar.engine_dot.state() == "ready"


def test_the_engine_status_says_loading_while_the_engine_loads(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    import threading
    from dataclasses import replace

    gate = threading.Event()

    def load() -> object:
        gate.wait(30)
        return app_ctx.engine

    w = MainWindow(replace(app_ctx, engine=None), load_engine=load)  # type: ignore[arg-type]
    qtbot.addWidget(w)
    assert w.sidebar.engine_dot.state() == "loading"
    gate.set()
    qtbot.waitUntil(lambda: w.sidebar.engine_dot.state() == "ready", timeout=10000)


def test_the_engine_status_says_so_when_the_engine_cannot_load(
    qtbot: QtBot, app_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    monkeypatch.setattr(main_window, "show_error", lambda parent, message: None)

    def broken() -> object:
        raise OSError("The language model en_core_web_md is not installed.")

    w = MainWindow(replace(app_ctx, engine=None), load_engine=broken)  # type: ignore[arg-type]
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: w.sidebar.engine_dot.state() == "problem", timeout=10000)
    assert w.sidebar.engine_label.text() == "The engine is not available"


# ---- the Settings -------------------------------------------------------------------------------


def test_the_settings_action_is_the_preferences_of_the_application_menu(
    window: MainWindow,
) -> None:
    action = window.settings_action
    assert action.text() == "Settings…"
    assert action.menuRole() == QAction.MenuRole.PreferencesRole
    standard = QKeySequence(QKeySequence.StandardKey.Preferences)
    expected = standard if not standard.isEmpty() else QKeySequence("Ctrl+,")
    assert action.shortcut() == expected and not action.shortcut().isEmpty()
    assert action.shortcutContext() == Qt.ShortcutContext.WindowShortcut


def test_the_settings_action_is_in_a_menu_of_the_menu_bar(window: MainWindow) -> None:
    menus = window.menuBar().findChildren(type(window.menuBar().addMenu("x")))
    assert any(window.settings_action in menu.actions() for menu in menus)


def test_the_settings_are_not_in_the_sidebar_or_the_tool_bar(window: MainWindow) -> None:
    assert "settings" not in window.sidebar.items
    assert window.settings_action not in window.toolbar.actions()


def test_the_settings_action_opens_the_settings_window(
    qtbot: QtBot, window: MainWindow, app_ctx: AppContext
) -> None:
    assert isinstance(window.settings_window, SettingsWindow)
    assert window.settings_screen is window.settings_window.settings_screen
    assert not window.settings_window.isVisible()
    app_ctx.user_lists.add_always("Project Falcon")
    window.settings_action.trigger()
    assert window.settings_window.isVisible()
    assert (
        window.settings_window.windowTitle() == "Settings" and not window.settings_window.isModal()
    )
    assert window.settings_screen.always_edit.toPlainText() == "Project Falcon"
    assert window.current_screen_name() == "home"  # the screen under it did not change


def test_opening_the_settings_again_does_not_throw_away_what_was_typed(
    window: MainWindow,
) -> None:
    window.show_settings()
    window.settings_screen.always_edit.setPlainText("typed, not saved")
    window.show_settings()
    assert window.settings_screen.always_edit.toPlainText() == "typed, not saved"


def test_the_settings_are_off_while_a_file_is_analysed_and_on_again_after(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    window.show_settings()
    assert window.settings_action.isEnabled() and window.settings_window.isEnabled()
    with qtbot.waitSignal(window.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        window.open_files([corpus / "supply-01.docx"], redline_split=False)
        # What the analysis reads (the lists, the case) must not change under it.
        assert not window.settings_action.isEnabled() and not window.settings_window.isEnabled()
        window.settings_action.trigger()  # a disabled action does nothing
    assert window.settings_action.isEnabled() and window.settings_window.isEnabled()


def test_the_settings_window_closes_with_the_main_window(qtbot: QtBot, window: MainWindow) -> None:
    window.show()
    window.show_settings()
    assert window.settings_window.isVisible()
    window.close()
    assert not window.settings_window.isVisible()


# ---- the file chooser ---------------------------------------------------------------------------


def test_the_choose_action_is_cmd_o_in_the_file_menu_and_opens_the_file_dialog(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[object] = []

    def choose(*args: object, **kwargs: object) -> tuple[list[str], str]:
        asked.append(args)
        return [], ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(choose))
    action = window.choose_action
    assert action.text() == "Choose file…"
    assert action.shortcut() == QKeySequence(QKeySequence.StandardKey.Open)
    action.trigger()
    assert len(asked) == 1


def test_the_choose_action_is_off_while_a_file_is_analysed_or_the_engine_loads(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    assert window.choose_action.isEnabled()
    with qtbot.waitSignal(window.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        window.open_files([corpus / "supply-01.docx"], redline_split=False)
        assert not window.choose_action.isEnabled()
    assert window.choose_action.isEnabled()


def test_the_chosen_files_are_analysed(
    qtbot: QtBot, window: MainWindow, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = [str(corpus / "supply-01.docx")]
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: (chosen, "")))
    with qtbot.waitSignal(window.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        window.choose_action.trigger()
    assert [s.path.name for s in window.sources] == ["supply-01.docx"]


# ---- the crossfade ------------------------------------------------------------------------------


def fade_overlays(w: MainWindow) -> list[QLabel]:
    return [label for label in w.findChildren(QLabel, "crossfade") if label.isVisible()]


def test_the_animations_are_off_in_the_tests(window: MainWindow) -> None:
    assert main_window.ANIMATIONS is False  # tests/ui/conftest.py
    window.show()
    window.show_cases()
    assert fade_overlays(window) == []


def test_a_change_of_screen_fades_the_old_screen_into_the_new_one(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_window, "ANIMATIONS", True)
    window.show()
    qtbot.waitExposed(window)
    window.show_cases()
    assert window.current_screen_name() == "cases"  # the new screen is in place at once
    overlays = fade_overlays(window)
    assert len(overlays) == 1  # a picture of the old screen, fading out over it
    assert overlays[0].testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert main_window.FADE_MS == 120
    qtbot.waitUntil(lambda: fade_overlays(window) == [], timeout=2000)


def test_a_second_change_during_a_fade_ends_the_first(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_window, "ANIMATIONS", True)
    window.show()
    qtbot.waitExposed(window)
    window.show_cases()
    window.show_restore()
    assert window.current_screen_name() == "restore"
    assert len(fade_overlays(window)) == 1
    qtbot.waitUntil(lambda: fade_overlays(window) == [], timeout=2000)


def test_going_to_the_screen_that_shows_does_not_fade(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_window, "ANIMATIONS", True)
    window.show()
    qtbot.waitExposed(window)
    window.show_home()
    assert fade_overlays(window) == []


def test_a_window_that_is_not_shown_does_not_fade(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_window, "ANIMATIONS", True)
    window.show_cases()
    assert window.findChildren(QLabel, "crossfade") == []


# ---- the keyboard -------------------------------------------------------------------------------


def focusable(widget: QWidget) -> bool:
    return bool(widget.focusPolicy() & Qt.FocusPolicy.TabFocus) and widget.isEnabled()


def test_tab_goes_from_the_toggle_to_the_primary_action_and_then_the_sections(
    qtbot: QtBot, window: MainWindow, corpus: Path
) -> None:
    analysed(qtbot, window, corpus)  # the primary action is on, so that Tab stops at it
    window.show()
    qtbot.waitExposed(window)
    order: list[QWidget] = []
    widget: QWidget = window.sidebar_toggle
    for _ in range(60):
        if focusable(widget) and widget not in order:
            order.append(widget)
        widget = widget.nextInFocusChain()
        if widget is window.sidebar_toggle:
            break
    primary = tool_button(window, window.primary_action)
    sections = list(window.sidebar.items.values())
    assert order.index(window.sidebar_toggle) < order.index(primary)
    assert order.index(primary) < order.index(sections[0])
    assert [order.index(item) for item in sections] == sorted(order.index(i) for i in sections)
    assert order.index(sections[2]) < len(order)


def test_the_settings_shortcut_opens_the_window_from_the_keyboard(
    qtbot: QtBot, window: MainWindow
) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)
    QTest.keyClick(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
    assert window.settings_window.isVisible()


def test_the_choose_shortcut_opens_the_file_dialog_from_the_keyboard(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[object] = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *a, **k: (asked.append(a), ([], ""))[1]),
    )
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)
    QTest.keyClick(window, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    assert len(asked) == 1


# ---- the look follows the appearance ------------------------------------------------------------


def test_the_toggle_is_drawn_in_the_secondary_colour_of_the_appearance(window: MainWindow) -> None:
    for appearance in ("light", "dark"):
        window.setPalette(theme.palette(appearance))
        image = window.sidebar_toggle.grab().toImage()
        inks = {image.pixelColor(x, y).name() for x in range(30) for y in range(26)}
        assert theme.tokens(appearance).secondary.lower() in inks, appearance


def test_the_toggle_shows_a_ring_when_the_keyboard_focuses_it_and_not_otherwise(
    qtbot: QtBot, window: MainWindow
) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    toggle = window.sidebar_toggle
    plain = toggle.grab().toImage()
    toggle.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    qtbot.waitUntil(toggle.hasFocus, timeout=2000)
    assert toggle.grab().toImage() == plain
    toggle.clearFocus()
    toggle.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(toggle.hasFocus, timeout=2000)
    assert toggle.grab().toImage() != plain
