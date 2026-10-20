"""The window and its home screen: from the files the owner chooses to the review screen.

The first four tests are the brief's: a contract goes from the home screen to the review, an old
.doc and a scanned PDF are refused in plain words, and the progress reaches 100. The rest cover
what the brief leaves to the builder: the question about tracked changes, a file added to a case,
the engine that is still loading, and the old cases that are deleted when the window opens. The
last section is what the review of the window left open: one request at a time, an error while
the review is built, the sidebar during an analysis, and the files that were not opened.

The window was rebuilt for the design pass (a sidebar and a tool bar with one primary action, the
Settings in a window of their own): the tests that went through the old five-button tool bar go
through the sidebar, the primary action and the Settings action now, and say so where they do.
"""

from __future__ import annotations

import errno
import logging
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QWidget

from themask.errors import KeyStoreError
from themask.keystore.cases import CaseStore
from themask.model import Case, KeyEntry, PlaceholderType
from themask.ui import main_window
from themask.ui.main_window import MainWindow
from themask.ui.review_screen import ReviewScreen

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from themask.detect.engine import Engine
    from themask.ui.app import AppContext

ANALYSIS_TIMEOUT = 60_000


# ---- the brief's four ---------------------------------------------------------------------------


def test_home_to_review(qtbot: QtBot, app_ctx: AppContext, corpus: Path) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show()
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert w.current_screen_name() == "review" and w.review_screen.group_count() > 0


def test_unsupported_file_shows_message(
    qtbot: QtBot, app_ctx: AppContext, fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000):
        w.open_files([fixtures / "not-a-docx.doc"], redline_split=False)
    assert shown and "save as .docx" in shown[0]


def test_scanned_pdf_message(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000):
        w.open_files([corpus / "scanned-01.pdf"], redline_split=False)
    assert "scan" in shown[0]


def test_progress_reaches_100(qtbot: QtBot, app_ctx: AppContext, corpus: Path) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    seen: list[int] = []
    w.analysisProgress.connect(lambda p, s: seen.append(p))
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert seen[-1] == 100 and seen == sorted(seen)


# ---- what the home screen shows ------------------------------------------------------------------


def test_the_window_opens_on_the_home_screen_with_every_screen_in_its_stack(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show()
    assert w.windowTitle() == "The MASK"
    assert w.current_screen_name() == "home"
    # The Settings are a window of their own now (themask.ui.settings_screen.SettingsWindow), not a
    # screen of the stack.
    assert w.screen_names() == ["home", "review", "restore", "cases"]
    assert w.home.status_label.text() == "Ready" and w.home.drop_zone.isEnabled()


@pytest.mark.parametrize(
    ("show", "name"),
    [("show_restore", "restore"), ("show_cases", "cases"), ("show_home", "home")],
)
def test_each_screen_can_be_shown(qtbot: QtBot, app_ctx: AppContext, show: str, name: str) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    getattr(w, show)()
    assert w.current_screen_name() == name


def test_the_settings_can_be_shown_as_a_window_over_the_screen_that_shows(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    # Was one of the screens above ("show_settings", "settings"); the Settings are a window now.
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show_cases()
    w.show_settings()
    assert w.settings_window.isVisible() and w.settings_screen.isVisibleTo(w.settings_window)
    assert w.current_screen_name() == "cases"


def test_progress_is_shown_on_the_home_screen_and_the_drop_zone_waits(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show()
    steps: list[tuple[bool, int, str]] = []
    w.analysisProgress.connect(
        lambda percent, step: steps.append(
            (w.home.drop_zone.isEnabled(), w.home.progress_bar.value(), w.home.step_label.text())
        )
    )
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert steps and all(
        not enabled for enabled, _, _ in steps
    )  # busy: nothing more can be dropped
    assert steps[-1][1] == 100 and all(label for _, _, label in steps)
    assert w.home.drop_zone.isEnabled() and w.home.progress_bar.isHidden()


def test_a_second_request_while_one_runs_is_refused(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
        assert w.is_analysing()
        w.open_files([corpus / "supply-02.docx"], redline_split=False)
    assert shown and "still" in shown[0]
    assert [s.path.name for s in w.sources] == ["supply-01.docx"]  # the first one carried on


def test_opening_nothing_does_nothing(qtbot: QtBot, app_ctx: AppContext) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.assertNotEmitted(w.analysisFinished), qtbot.assertNotEmitted(w.analysisFailed):
        w.open_files([], redline_split=None)
    assert not w.is_analysing()


def test_dropping_files_on_the_home_screen_starts_the_analysis(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.home.drop_zone.filesDropped.emit([corpus / "supply-01.docx"])
    assert w.current_screen_name() == "review"


# ---- tracked changes -----------------------------------------------------------------------------


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """The answers ``ask_redline`` was given a question for; it answers yes."""
    questions: list[bool] = []
    monkeypatch.setattr(main_window, "ask_redline", lambda parent: questions.append(True) or True)
    return questions


def test_a_file_with_tracked_changes_is_asked_about(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, asked: list[bool]
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-03.docx"], redline_split=None)
    assert asked == [True]
    assert w.redline_split is True
    assert [s.pkg_before is not None for s in w.sources] == [True]  # both versions were made
    names = [name for name, _, _ in w.review_screen.combined.parts]
    assert names == ["supply-03.docx (after)", "supply-03.docx (before)"]


def test_a_no_to_the_question_gives_one_version(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_window, "ask_redline", lambda parent: False)
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-03.docx"], redline_split=None)
    assert w.redline_split is False and w.sources[0].pkg_before is None


def test_a_file_without_tracked_changes_is_not_asked_about(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, asked: list[bool]
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=None)
    assert asked == [] and w.redline_split is False


def test_several_files_with_tracked_changes_are_asked_about_once(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, asked: list[bool]
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files(
            [corpus / "supply-01.docx", corpus / "supply-03.docx", corpus / "nda-05.docx"],
            redline_split=None,
        )
    assert asked == [True]
    assert [s.pkg_before is not None for s in w.sources] == [False, True, True]


def test_a_pdf_never_has_tracked_changes(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, asked: list[bool]
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.pdf"], redline_split=None)
    assert asked == [] and [s.kind for s in w.sources] == ["pdf"]


def test_an_answer_given_by_the_caller_is_not_asked_again(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, asked: list[bool]
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-03.docx"], redline_split=False)
    assert asked == [] and w.sources[0].pkg_before is None


def test_a_file_that_cannot_be_opened_is_left_to_the_analysis_to_report(
    qtbot: QtBot,
    app_ctx: AppContext,
    fixtures: Path,
    monkeypatch: pytest.MonkeyPatch,
    asked: list[bool],
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000):
        w.open_files([fixtures / "corrupt.docx"], redline_split=None)
    assert asked == [] and shown  # no question, and the one message is the analysis's


# ---- a file added to a case ----------------------------------------------------------------------


def a_case(case_id: str = "K4F7", created_at: datetime | None = None) -> Case:
    """A case whose key holds Northwind (numbered [COMPANY_3]) and a person who is not in supply-01."""
    return Case(
        case_id,
        created_at or datetime.now(UTC),
        ["earlier.docx"],
        [],
        [
            KeyEntry(
                "[COMPANY_3]", PlaceholderType.COMPANY, "Northwind Trading B.V.", ["Northwind"]
            ),
            KeyEntry("[PERSON_2]", PlaceholderType.PERSON, "Nobody Inthetext", []),
        ],
    )


def test_a_file_added_to_a_case_keeps_the_numbers_of_its_key(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    case = a_case()
    app_ctx.case_store.save(case)
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False, case_id="K4F7")
    review = w.review_screen.review
    assert w.pending_case == case
    assert review.reserved == {"[COMPANY_3]", "[PERSON_2]"}  # a new group never takes these numbers
    by_name = {g.canonical: g.placeholder for g in review.groups}
    assert by_name["Northwind Trading B.V."] == "[COMPANY_3]"  # the key's own number
    assert by_name["Thamesgate Catering plc"] == "[COMPANY_4]"  # numbering goes on after the key
    assert "Nobody Inthetext" not in by_name  # a value this file lacks is not offered


def test_a_new_case_has_nothing_reserved_and_nothing_pending(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert w.pending_case is None and w.review_screen.review.reserved == frozenset()


def test_the_pending_case_is_forgotten_when_the_next_file_is_not_for_it(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    app_ctx.case_store.save(a_case())
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False, case_id="K4F7")
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-02.docx"], redline_split=False)
    assert w.pending_case is None and w.review_screen.review.reserved == frozenset()


def test_a_case_that_is_gone_is_reported(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False, case_id="K4F7")
    assert shown and "case" in shown[0] and "no longer" in shown[0]
    assert w.current_screen_name() == "home" and w.pending_case is None


def test_a_case_that_cannot_be_opened_is_reported(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    path = app_ctx.case_store.save(a_case())
    path.write_bytes(b"not a case")
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False, case_id="K4F7")
    assert shown and "damaged" in shown[0]


# ---- the engine that is still loading ------------------------------------------------------------


def test_a_request_made_before_the_engine_is_ready_waits_for_it(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    gate = threading.Event()

    def load_engine() -> Engine:
        gate.wait(30)
        return app_ctx.engine  # the session's, already loaded

    ctx = replace(app_ctx, engine=None)
    w = MainWindow(ctx, load_engine=load_engine)
    qtbot.addWidget(w)
    w.show()
    assert w.home.status_label.text() == "Loading…" and not w.home.drop_zone.isEnabled()

    progress: list[int] = []
    w.analysisProgress.connect(lambda percent, step: progress.append(percent))
    w.open_files([corpus / "supply-01.docx"], redline_split=False)
    qtbot.wait(200)
    assert progress == [] and w.current_screen_name() == "home"  # it waits for the engine

    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        gate.set()
    assert ctx.engine is app_ctx.engine and w.current_screen_name() == "review"
    assert w.home.status_label.text() == "Ready" and w.home.drop_zone.isEnabled()


def test_the_drop_zone_is_enabled_once_the_engine_has_loaded(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    ctx = replace(app_ctx, engine=None)
    w = MainWindow(ctx, load_engine=lambda: app_ctx.engine)
    qtbot.addWidget(w)
    assert not w.home.drop_zone.isEnabled()
    qtbot.waitUntil(lambda: w.home.drop_zone.isEnabled(), timeout=10000)
    assert ctx.engine is app_ctx.engine and w.home.status_label.text() == "Ready"


def test_an_engine_that_cannot_load_is_reported_and_the_waiting_request_fails(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    gate = threading.Event()

    def broken() -> Engine:
        gate.wait(30)
        raise OSError("The language model en_core_web_md is not installed.")

    w = MainWindow(replace(app_ctx, engine=None), load_engine=broken)
    qtbot.addWidget(w)
    w.open_files([corpus / "supply-01.docx"], redline_split=False)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000) as failed:
        gate.set()
    assert len(shown) == 1 and "language model" in shown[0]
    assert failed.args == [shown[0]]
    assert not w.home.drop_zone.isEnabled() and "language model" in w.home.notice_label.text()
    # Asking again does not wait for an engine that is never coming.
    with qtbot.waitSignal(w.analysisFailed, timeout=10000):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert len(shown) == 2


# ---- the old cases are deleted when the window opens ---------------------------------------------


def test_expired_cases_are_deleted_when_the_window_opens(qtbot: QtBot, app_ctx: AppContext) -> None:
    app_ctx.case_store.save(a_case("K4F7", datetime.now(UTC) - timedelta(days=40)))
    app_ctx.case_store.save(a_case("B2C3", datetime.now(UTC) - timedelta(days=5)))
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    assert [s.id for s in app_ctx.case_store.list()] == ["B2C3"]
    assert w.home.notice_label.text() == ""


class BrokenStore(CaseStore):
    """A case store whose clean-up fails with ``error``."""

    def __init__(self, error: Exception) -> None:
        super().__init__(Path("/nonexistent"), None)  # the key store is never asked
        self.error = error

    def purge_expired(self, now: datetime | None = None) -> list[str]:
        raise self.error


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (KeyStoreError("The MASK could not reach the macOS Keychain. Unlock it."), "Keychain"),
        (OSError(errno.EACCES, "Permission denied"), "Permission denied"),
    ],
    ids=["keychain", "disk"],
)
def test_a_failed_clean_up_does_not_stop_the_window(
    qtbot: QtBot, app_ctx: AppContext, error: Exception, shown: str
) -> None:
    w = MainWindow(replace(app_ctx, case_store=BrokenStore(error)))
    qtbot.addWidget(w)
    w.show()
    assert w.isVisible() and w.current_screen_name() == "home"
    assert shown in w.home.notice_label.text()  # said in the status line, not in a dialog
    assert w.home.drop_zone.isEnabled()


# ---- closing -------------------------------------------------------------------------------------


def test_closing_the_window_waits_for_the_analysis_to_end(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show()
    w.open_files([corpus / "supply-10.docx"], redline_split=False)
    assert w.is_analysing()
    w.close()  # a thread must never be destroyed while it runs
    assert not w.is_analysing() and not w.isVisible()


# ---- what the review of this window left open ------------------------------------------------------


def test_a_second_request_while_the_engine_loads_is_refused(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    gate = threading.Event()

    def load_engine() -> Engine:
        gate.wait(30)
        return app_ctx.engine  # the session's, already loaded

    w = MainWindow(replace(app_ctx, engine=None), load_engine=load_engine)
    qtbot.addWidget(w)
    w.open_files([corpus / "supply-01.docx"], redline_split=False)  # waits for the engine
    w.open_files([corpus / "supply-02.docx"], redline_split=False)  # must not replace it
    assert shown == [main_window.BUSY_MESSAGE]
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        gate.set()
    assert [s.path.name for s in w.sources] == ["supply-01.docx"]  # the first one carried on


def test_an_error_while_the_review_is_built_is_told_and_only_its_type_is_logged(
    qtbot: QtBot,
    app_ctx: AppContext,
    corpus: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))

    def broken(self: ReviewScreen, review: object, combined: object) -> None:
        raise RuntimeError("Secret Client Ltd")

    monkeypatch.setattr(ReviewScreen, "load", broken)
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with (
        caplog.at_level(logging.INFO, logger="themask"),
        qtbot.assertNotEmitted(w.analysisFinished),
        qtbot.waitSignal(w.analysisFailed, timeout=ANALYSIS_TIMEOUT) as failed,
    ):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert shown == [main_window.REVIEW_FAILED] and failed.args == [main_window.REVIEW_FAILED]
    assert "RuntimeError" in caplog.text and "Secret" not in caplog.text
    # Nothing of the window was changed on the way: it is as if the file had never been opened.
    assert w.sources == [] and w.pending_case is None and w.current_screen_name() == "home"
    assert not w.is_analysing() and w.home.drop_zone.isEnabled()
    # Was the tool bar's Review button (off: nothing to go back to) and Home button (on).
    assert w.primary_action.text() == "Review" and not w.primary_action.isEnabled()
    assert all(item.isEnabled() for item in w.sidebar.items.values())


# Renamed from test_the_tool_bar_is_off_while_a_file_is_analysed_and_on_again_after: the screens
# are reached through the sidebar now, and the Settings through their own action.
def test_the_sidebar_and_the_settings_are_off_while_a_file_is_analysed_and_on_again_after(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    items = list(w.sidebar.items.values())
    assert all(item.isEnabled() for item in items) and not w.primary_action.isEnabled()
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
        assert w.is_analysing() and not any(item.isEnabled() for item in items)
        assert not w.settings_action.isEnabled() and not w.primary_action.isEnabled()
        w.settings_action.trigger()  # nothing the analysis reads may change under it
        w.sidebar.items["cases"].click()
        assert not w.settings_window.isVisible()
        assert w.current_screen_name() == "home"  # the analysis is what the owner waits for
    assert all(item.isEnabled() for item in items)
    assert w.settings_action.isEnabled() and w.primary_action.isEnabled()  # "Export…": a review
    w.sidebar.items["cases"].click()
    assert w.current_screen_name() == "cases"


# Renamed from test_the_tool_bar_comes_back_when_the_analysis_fails (see above).
def test_the_sidebar_comes_back_when_the_analysis_fails(
    qtbot: QtBot, app_ctx: AppContext, fixtures: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: None)
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFailed, timeout=10000):
        w.open_files([fixtures / "not-a-docx.doc"], redline_split=False)
        assert not w.sidebar.items["cases"].isEnabled()
    assert w.sidebar.items["cases"].isEnabled() and w.sidebar.items["restore"].isEnabled()
    assert not w.primary_action.isEnabled()  # "Review": still nothing to go back to


def test_opening_files_from_another_screen_shows_the_progress_on_the_home_screen(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show_restore()  # was show_settings: the Settings are not a screen of the stack any more
    screens: list[str] = []
    w.analysisProgress.connect(lambda percent, step: screens.append(w.current_screen_name()))
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
        assert w.current_screen_name() == "home"
    assert screens and set(screens) == {"home"} and w.current_screen_name() == "review"


def test_a_request_made_while_the_engine_loads_shows_the_home_screen_at_once(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    gate = threading.Event()

    def load_engine() -> Engine:
        gate.wait(30)
        return app_ctx.engine

    w = MainWindow(replace(app_ctx, engine=None), load_engine=load_engine)
    qtbot.addWidget(w)
    w.show_cases()  # the owner asked from the Cases screen ("Add file to this case")
    w.open_files([corpus / "supply-01.docx"], redline_split=False)
    assert w.current_screen_name() == "home" and w.home.status_label.text() == "Loading…"
    gate.set()
    qtbot.waitUntil(lambda: w.current_screen_name() == "review", timeout=ANALYSIS_TIMEOUT)


def test_the_home_screen_is_shown_again_when_a_waiting_request_starts(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    gate = threading.Event()

    def load_engine() -> Engine:
        gate.wait(30)
        return app_ctx.engine

    w = MainWindow(replace(app_ctx, engine=None), load_engine=load_engine)
    qtbot.addWidget(w)
    w.open_files([corpus / "supply-01.docx"], redline_split=False)
    w.show_cases()  # the owner looks at something else while the engine loads (was show_settings)
    gate.set()
    qtbot.waitUntil(w.is_analysing, timeout=ANALYSIS_TIMEOUT)
    assert w.current_screen_name() == "home"  # the progress is where the owner can see it
    qtbot.waitUntil(lambda: w.current_screen_name() == "review", timeout=ANALYSIS_TIMEOUT)


def drop(zone: QWidget, *paths: Path) -> None:
    """Drop files on the zone the way a drag does: it enters first, then the drop is delivered."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    entering = QDragEnterEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(zone, entering)
    dropped = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(zone, dropped)


def test_files_that_were_not_opened_are_named_on_the_home_screen(
    qtbot: QtBot, app_ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    w.show()
    assert w.home.refused_label.isHidden()
    with caplog.at_level(logging.DEBUG, logger="themask"):
        drop(w.home.drop_zone, Path("/somewhere/old.doc"), Path("/somewhere/notes.txt"))
    text = w.home.refused_label.text()
    assert not w.home.refused_label.isHidden()
    assert "old.doc" in text and "notes.txt" in text
    assert "Word (.docx) and PDF" in text and "saved as .docx" in text  # the advice is reachable
    assert not w.is_analysing()  # nothing was opened
    assert "old.doc" not in caplog.text and "notes.txt" not in caplog.text  # on screen only


def test_the_advice_about_an_old_doc_is_only_given_for_one(
    qtbot: QtBot, app_ctx: AppContext
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    drop(w.home.drop_zone, Path("/somewhere/notes.txt"))
    text = w.home.refused_label.text()
    assert "notes.txt" in text and "Word (.docx) and PDF" in text and ".doc " not in text


def test_a_mixed_drop_opens_the_contracts_and_names_the_rest(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        drop(w.home.drop_zone, corpus / "supply-01.docx", Path("/somewhere/old.doc"))
    assert [s.path.name for s in w.sources] == ["supply-01.docx"]
    assert "old.doc" in w.home.refused_label.text()  # still there when the owner comes back
    w.show_home()
    assert not w.home.refused_label.isHidden()


def test_the_next_drop_clears_the_notice_about_the_last(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path
) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    drop(w.home.drop_zone, Path("/somewhere/old.doc"))
    assert "old.doc" in w.home.refused_label.text()
    drop(w.home.drop_zone, Path("/somewhere/notes.txt"))
    assert "notes.txt" in w.home.refused_label.text()
    assert "old.doc" not in w.home.refused_label.text()  # replaced, not added to
    with qtbot.waitSignal(w.analysisFinished, timeout=ANALYSIS_TIMEOUT):
        drop(w.home.drop_zone, corpus / "supply-01.docx")
    assert w.home.refused_label.isHidden() and w.home.refused_label.text() == ""
