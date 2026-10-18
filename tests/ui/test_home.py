"""The window and its home screen: from the files the owner chooses to the review screen.

The first four tests are the brief's: a contract goes from the home screen to the review, an old
.doc and a scanned PDF are refused in plain words, and the progress reaches 100. The rest cover
what the brief leaves to the builder: the question about tracked changes, a file added to a case,
the engine that is still loading, and the old cases that are deleted when the window opens.
"""

from __future__ import annotations

import errno
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from themask.errors import KeyStoreError
from themask.keystore.cases import CaseStore
from themask.model import Case, KeyEntry, PlaceholderType
from themask.ui import main_window
from themask.ui.main_window import MainWindow

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
    assert w.screen_names() == ["home", "review", "export", "restore", "cases", "settings"]
    assert w.home.status_label.text() == "Ready" and w.home.drop_zone.isEnabled()


@pytest.mark.parametrize(
    ("show", "name"),
    [
        ("show_restore", "restore"),
        ("show_cases", "cases"),
        ("show_settings", "settings"),
        ("show_home", "home"),
    ],
)
def test_each_screen_can_be_shown(qtbot: QtBot, app_ctx: AppContext, show: str, name: str) -> None:
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    getattr(w, show)()
    assert w.current_screen_name() == name


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
