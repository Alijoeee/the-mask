"""The threads: the analysis of the files the owner chose, and the loading of the engine.

Both report to the window by signals. What a thread reports to the owner is plain English, and
what it writes to the log is the kind of an unexpected error and nothing else: its text may quote
a file name, and a file name tells who the parties are (logging_setup.py has the rule).
"""

from __future__ import annotations

import errno
import gc
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from themask.detect.lists import CaseLists
from themask.errors import MaskError, ScannedPdfError
from themask.logging_setup import setup_logging
from themask.model import KeyEntry, PlaceholderType
from themask.paths import log_dir
from themask.ui import workers
from themask.ui.workers import AnalysisWorker, EngineWorker

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists

SECRET = "Secret Client Ltd"
GENERIC = "Something went wrong while analysing the file."
ENGINE_FAILED = "The MASK could not load its detection engine."


def test_the_garbage_collector_is_off_while_a_test_runs() -> None:
    # tests/ui/conftest.py: a collection in a worker thread, while the main thread takes the
    # widgets of an earlier test apart, crashes PySide6 (a segmentation fault in the middle of
    # the run), so the collector runs between the tests only.
    assert not gc.isenabled()


def run_analysis(
    qtbot: QtBot, engine: Engine, lists: UserLists, paths: list[Path]
) -> tuple[list[tuple[int, str]], list[str]]:
    """Runs a worker until it reports one way or the other; returns its progress marks and its
    failures (none when it finished).
    """
    worker = AnalysisWorker(paths, False, engine, lists, CaseLists([], [], set()))
    marks: list[tuple[int, str]] = []
    failures: list[str] = []
    finished: list[object] = []
    worker.progress.connect(lambda percent, step: marks.append((percent, step)))
    worker.failed.connect(failures.append)
    worker.finished.connect(finished.append)
    worker.start()
    qtbot.waitUntil(lambda: bool(failures or finished), timeout=60000)
    worker.wait()
    return marks, failures


def test_the_analysis_reports_five_marks_and_hands_over_what_it_found(
    qtbot: QtBot, engine: Engine, lists: UserLists, corpus: Path
) -> None:
    worker = AnalysisWorker(
        [corpus / "supply-01.docx"], False, engine, lists, CaseLists([], [], set())
    )
    marks: list[tuple[int, str]] = []
    worker.progress.connect(lambda percent, step: marks.append((percent, step)))
    with qtbot.waitSignal(worker.finished, timeout=60000) as done:
        worker.start()
    worker.wait()
    assert marks == [
        (5, "loading"),
        (25, "reading"),
        (40, "finding"),
        (85, "grouping"),
        (100, "done"),
    ]
    sources, analysis = done.args[0]
    assert [s.path.name for s in sources] == ["supply-01.docx"]
    assert analysis.groups and analysis.text == sources[0].text_after.text


def test_the_signals_reach_the_thread_of_the_window(
    qtbot: QtBot, engine: Engine, lists: UserLists, corpus: Path
) -> None:
    threads: list[int] = []
    worker = AnalysisWorker(
        [corpus / "supply-01.docx"], False, engine, lists, CaseLists([], [], set())
    )
    worker.progress.connect(lambda percent, step: threads.append(threading.get_ident()))
    worker.finished.connect(lambda result: threads.append(threading.get_ident()))
    with qtbot.waitSignal(worker.finished, timeout=60000):
        worker.start()
    worker.wait()
    assert threads and set(threads) == {threading.get_ident()}  # not the worker's own


def test_the_analysis_fills_the_case_lists_it_was_given(
    qtbot: QtBot, engine: Engine, lists: UserLists, corpus: Path
) -> None:
    case_lists = CaseLists([], [], set())
    worker = AnalysisWorker([corpus / "supply-01.docx"], False, engine, lists, case_lists)
    with qtbot.waitSignal(worker.finished, timeout=60000):
        worker.start()
    worker.wait()
    assert case_lists.defined_terms  # the contract's defined terms ("the Buyer"...)


def test_the_key_of_a_case_seeds_the_analysis(
    qtbot: QtBot, engine: Engine, lists: UserLists, corpus: Path
) -> None:
    key = [KeyEntry("[COMPANY_7]", PlaceholderType.COMPANY, "Northwind Trading B.V.", [])]
    worker = AnalysisWorker(
        [corpus / "supply-01.docx"], False, engine, lists, CaseLists([], [], set()), key
    )
    with qtbot.waitSignal(worker.finished, timeout=60000) as done:
        worker.start()
    worker.wait()
    _, analysis = done.args[0]
    assert "[COMPANY_7]" in {g.placeholder for g in analysis.groups}


def test_the_redline_versions_are_made_when_asked_for(
    qtbot: QtBot, engine: Engine, lists: UserLists, corpus: Path
) -> None:
    worker = AnalysisWorker(
        [corpus / "supply-03.docx"], True, engine, lists, CaseLists([], [], set())
    )
    with qtbot.waitSignal(worker.finished, timeout=60000) as done:
        worker.start()
    worker.wait()
    sources, _ = done.args[0]
    assert sources[0].pkg_before is not None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("scanned-01.pdf", "scan"),
        ("missing.docx", "The file could not be read: No such file or directory"),
    ],
)
def test_a_file_that_cannot_be_read_is_explained(
    qtbot: QtBot,
    engine: Engine,
    lists: UserLists,
    corpus: Path,
    tmp_path: Path,
    name: str,
    expected: str,
) -> None:
    path = corpus / name if name.endswith(".pdf") else tmp_path / name
    marks, failures = run_analysis(qtbot, engine, lists, [path])
    assert len(failures) == 1 and expected in failures[0]
    assert marks == [(5, "loading")]  # it stopped where it failed; nothing says "done"


def test_a_message_for_the_owner_is_passed_on_as_it_is(
    qtbot: QtBot, engine: Engine, lists: UserLists, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(paths: list[Path], redline_split: bool) -> list[object]:
        raise ScannedPdfError("This PDF is a scan.")

    monkeypatch.setattr(workers, "load_sources", refuse)
    _, failures = run_analysis(qtbot, engine, lists, [corpus / "supply-01.docx"])
    assert failures == ["This PDF is a scan."]


def test_a_system_error_gives_the_reason_the_system_gave(
    qtbot: QtBot, engine: Engine, lists: UserLists, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(paths: list[Path], redline_split: bool) -> list[object]:
        raise PermissionError(errno.EACCES, "Permission denied", f"/private/{SECRET}.docx")

    monkeypatch.setattr(workers, "load_sources", refuse)
    _, failures = run_analysis(qtbot, engine, lists, [corpus / "supply-01.docx"])
    assert failures == ["The file could not be read: Permission denied"]  # not the file's name


def test_an_error_without_a_reason_still_gives_a_message(
    qtbot: QtBot, engine: Engine, lists: UserLists, corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(paths: list[Path], redline_split: bool) -> list[object]:
        raise OSError("something odd")

    monkeypatch.setattr(workers, "load_sources", refuse)
    _, failures = run_analysis(qtbot, engine, lists, [corpus / "supply-01.docx"])
    assert failures == ["The file could not be read: something odd"]


def test_an_unexpected_error_is_logged_by_its_kind_only(
    qtbot: QtBot,
    engine: Engine,
    lists: UserLists,
    corpus: Path,
    monkeypatch: pytest.MonkeyPatch,
    data_dir: Path,
) -> None:
    setup_logging()

    def explode(paths: list[Path], redline_split: bool) -> list[object]:
        raise RuntimeError(f"cannot parse {SECRET} (acme-secret.docx)")

    monkeypatch.setattr(workers, "load_sources", explode)
    _, failures = run_analysis(qtbot, engine, lists, [corpus / "supply-01.docx"])
    assert failures == [GENERIC]  # the owner is not shown the text of the error either
    logged = (log_dir() / "themask.log").read_text(encoding="utf-8")
    assert "RuntimeError" in logged
    assert SECRET not in logged and "acme-secret" not in logged and "cannot parse" not in logged


def test_the_engine_is_loaded_in_a_thread_and_handed_over(qtbot: QtBot) -> None:
    engine = object()
    worker = EngineWorker(lambda: engine)  # type: ignore[arg-type,return-value]
    where: list[int] = []
    worker.loaded.connect(lambda loaded: where.append(threading.get_ident()))
    with qtbot.waitSignal(worker.loaded, timeout=10000) as done:
        worker.start()
    worker.wait()
    assert done.args == [engine] and where == [threading.get_ident()]


def test_the_default_engine_is_made_when_no_factory_is_given(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = object()
    monkeypatch.setattr(workers, "load_default_engine", lambda: engine)
    worker = EngineWorker()
    with qtbot.waitSignal(worker.loaded, timeout=10000) as done:
        worker.start()
    worker.wait()
    assert done.args == [engine]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (MaskError("A plain message."), "A plain message."),
        (
            OSError("The language model en_core_web_md is not installed."),
            f"{ENGINE_FAILED} The language model en_core_web_md is not installed.",
        ),
        (RuntimeError(f"{SECRET} broke it"), ENGINE_FAILED),
    ],
    ids=["mask error", "os error", "other error"],
)
def test_an_engine_that_cannot_be_loaded_is_explained(
    qtbot: QtBot, data_dir: Path, error: Exception, expected: str
) -> None:
    setup_logging()

    def broken() -> object:
        raise error

    worker = EngineWorker(broken)  # type: ignore[arg-type]
    with qtbot.waitSignal(worker.failed, timeout=10000) as failed:
        worker.start()
    worker.wait()
    assert failed.args == [expected]
    assert SECRET not in (log_dir() / "themask.log").read_text(encoding="utf-8")
