"""The export dialog: the masked files made in a thread, and what the owner is told afterwards.

The first three tests are the brief's: a successful export lists the files and puts the
instruction on the clipboard, a blocked one shows where a marked value is still present and offers
nothing but the way back, and the case is saved. The rest cover what the brief leaves to the
builder: an export that fails, what was left visible on purpose or cannot be checked, the buttons,
the dialog that cannot be closed while it works, and the way the window opens it.
"""

from __future__ import annotations

import errno
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from tests.helpers import analysed
from themask.detect.lists import CaseLists, UserLists
from themask.errors import KeyStoreError, MaskError
from themask.export import ExportOptions, ExportResult
from themask.instruction import AI_INSTRUCTION
from themask.leakcheck import LeakHit
from themask.model import Case, Group, KeyEntry, MaskedFile, PlaceholderType
from themask.review import ReviewState
from themask.ui import export_dialog, main_window
from themask.ui.export_dialog import ExportDialog
from themask.ui.main_window import MainWindow

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

    from themask.ui.app import AppContext

EXPORT_TIMEOUT = 60_000  # a real export of a contract takes a few seconds


def empty_review() -> ReviewState:
    """A review of nothing, for the tests that replace the export itself."""
    return ReviewState("", [], [], UserLists([], []), CaseLists([], [], set()))


def saved(tmp_path: Path, **more: object) -> ExportResult:
    """An export that went through: one file written, nothing left over."""
    case = Case(
        "K4F7",
        datetime(2026, 10, 17, 9, 0, tzinfo=UTC),
        ["Supply.docx"],
        [MaskedFile("MASKED-K4F7.docx", "ab" * 32)],
        [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", [])],
        30,
    )
    return ExportResult(
        case,
        [tmp_path / "MASKED-K4F7.docx"],
        [],
        [],
        AI_INSTRUCTION,
        False,
        **more,  # type: ignore[arg-type]
    )


def replace_export(monkeypatch: pytest.MonkeyPatch, fake: Callable[..., ExportResult]) -> None:
    """Make the dialog's export ``fake``, which gets the arguments of ``export_case`` by name."""
    monkeypatch.setattr(export_dialog, "export_case", fake)


def run_dialog(
    qtbot: QtBot,
    ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake: Callable[..., ExportResult],
) -> ExportDialog:
    """A dialog that has run ``fake`` in place of the export, to the end."""
    replace_export(monkeypatch, fake)
    d = ExportDialog()
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=10_000):
        d.run([], empty_review(), ExportOptions(tmp_path), ctx)
    return d


# ---- the brief's three ---------------------------------------------------------------------------


def test_success_shows_outputs_and_instruction(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, tmp_path: Path
) -> None:
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"])
    d = ExportDialog()
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=EXPORT_TIMEOUT):
        d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert "MASKED-" in d.summary_text() and not d.result.blocked
    qtbot.mouseClick(d.copy_button, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == AI_INSTRUCTION


def test_blocked_shows_hits(
    qtbot: QtBot,
    app_ctx: AppContext,
    corpus: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"])
    monkeypatch.setattr(
        export_dialog,
        "export_case",
        lambda *a, **k: ExportResult(
            None,
            [],
            [LeakHit("word/header1.xml", "[COMPANY_1]", "… [COMPANY_1] …")],
            [],
            AI_INSTRUCTION,
            True,
        ),
    )
    d = ExportDialog()
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=10000):
        d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert (
        "blocked" in d.summary_text().lower()
        and "word/header1.xml" in d.summary_text()
        and not d.copy_button.isEnabled()
    )


def test_case_saved(qtbot: QtBot, app_ctx: AppContext, corpus: Path, tmp_path: Path) -> None:
    srcs, review = analysed(app_ctx, [corpus / "supply-01.docx"])
    d = ExportDialog()
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=EXPORT_TIMEOUT):
        d.run(srcs, review, ExportOptions(tmp_path), app_ctx)
    assert [s.id for s in app_ctx.case_store.list()] == [d.result.case.id]


# ---- the thread ----------------------------------------------------------------------------------


def test_the_export_is_given_what_the_context_holds(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    got: dict[str, object] = {}

    def fake(
        sources: object,
        review: object,
        options: object,
        engine: object,
        user_lists: object,
        save_case: object,
    ) -> ExportResult:
        got.update(
            sources=sources,
            review=review,
            options=options,
            engine=engine,
            user_lists=user_lists,
            save_case=save_case,
        )
        return saved(tmp_path)

    replace_export(monkeypatch, fake)
    sources, review, options = [], empty_review(), ExportOptions(tmp_path)
    d = ExportDialog()
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=10_000):
        d.run(sources, review, options, app_ctx)
    assert got["sources"] is sources and got["review"] is review and got["options"] is options
    assert got["engine"] is app_ctx.engine and got["user_lists"] is app_ctx.user_lists
    assert got["save_case"] == app_ctx.case_store.save  # the case goes into the owner's store


def test_the_files_are_made_in_a_thread_and_reported_in_the_window_s(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: dict[str, int] = {}

    def fake(*_: object) -> ExportResult:
        threads["work"] = threading.get_ident()
        return saved(tmp_path)

    replace_export(monkeypatch, fake)
    d = ExportDialog()
    qtbot.addWidget(d)
    d.finishedExport.connect(lambda: threads.setdefault("report", threading.get_ident()))
    with qtbot.waitSignal(d.finishedExport, timeout=10_000):
        d.run([], empty_review(), ExportOptions(tmp_path), app_ctx)
    assert threads["work"] != threading.get_ident()  # the window stays free while it works
    assert threads["report"] == threading.get_ident()  # what the screen shows is made at home


def test_while_the_files_are_made_the_dialog_shows_progress_and_cannot_be_closed(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()

    def slow(*_: object) -> ExportResult:
        gate.wait(30)
        return saved(tmp_path)

    replace_export(monkeypatch, slow)
    d = ExportDialog()
    qtbot.addWidget(d)
    d.show()
    d.run([], empty_review(), ExportOptions(tmp_path), app_ctx)
    try:
        assert d.is_running() and d.progress_bar.isVisibleTo(d)
        assert not any(
            b.isVisibleTo(d)
            for b in (d.copy_button, d.finder_button, d.close_button, d.back_button)
        )
        d.reject()  # the Escape key
        d.close()  # the close button of the window
        assert d.isVisible() and d.is_running()  # a thread is making the files: it must end first
    finally:
        with qtbot.waitSignal(d.finishedExport, timeout=10_000):
            gate.set()
    assert not d.is_running() and not d.progress_bar.isVisibleTo(d)
    d.reject()
    assert not d.isVisible()


def test_a_second_run_is_refused(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()

    def slow(*_: object) -> ExportResult:
        gate.wait(30)
        return saved(tmp_path)

    replace_export(monkeypatch, slow)
    d = ExportDialog()
    qtbot.addWidget(d)
    d.run([], empty_review(), ExportOptions(tmp_path), app_ctx)
    try:
        with pytest.raises(RuntimeError, match="already"):
            d.run([], empty_review(), ExportOptions(tmp_path), app_ctx)
    finally:
        with qtbot.waitSignal(d.finishedExport, timeout=10_000):
            gate.set()


# ---- what is shown after a save ------------------------------------------------------------------


def test_a_save_lists_the_files_the_case_and_offers_the_instruction(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = saved(tmp_path)
    result.outputs.append(tmp_path / "MASKED-K4F7-2.docx")
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    text = d.summary_text()
    assert "MASKED-K4F7.docx" in text and "MASKED-K4F7-2.docx" in text
    assert "K4F7" in text and "30 days" in text  # the key's case, and how long it is kept
    # Nothing to warn about: the sections for what was found beyond the marks stay away.
    assert (
        "not marked by you" not in text and "on purpose" not in text and "Not checkable" not in text
    )
    assert d.result is result and not d.result.blocked
    assert d.copy_button.isVisibleTo(d) and d.copy_button.isEnabled()
    assert d.finder_button.isVisibleTo(d) and d.close_button.isVisibleTo(d)
    assert not d.back_button.isVisibleTo(d) and not d.progress_bar.isVisibleTo(d)


def test_what_was_found_beyond_the_marks_is_listed(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = saved(
        tmp_path,
        allowed_hits=[LeakHit("word/document.xml", "[COMPANY_1]", "… sold by [COMPANY_1] …", 2)],
        unverifiable=["[ID_1]", "[PERSON_3]"],
    )
    result.unmarked = [
        Group("g1", PlaceholderType.PERSON, "Jane Doe", {"Jane Doe"}, [], "[PERSON_9]"),
        Group(
            "g2", PlaceholderType.COMPANY, "Falcon Freight", {"Falcon Freight"}, [], "[COMPANY_9]"
        ),
    ]
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    text = d.summary_text()
    assert "Also found in the masked copy — not marked by you:" in text
    assert "Jane Doe (PERSON)" in text and "Falcon Freight (COMPANY)" in text
    assert "Left visible on purpose:" in text
    assert "word/document.xml" in text and "… sold by [COMPANY_1] …" in text
    assert "Not checkable (too short): [ID_1], [PERSON_3]" in text


def test_the_first_section_to_read_is_the_marks_the_owner_did_not_make(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = saved(tmp_path)
    result.unmarked = [Group("g1", PlaceholderType.PERSON, "Jane Doe", set(), [], "[PERSON_9]")]
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    text = d.summary_text()
    # The files come first, then the warning; the owner reads the files before the fine print.
    assert text.index("MASKED-K4F7.docx") < text.index("not marked by you") < text.index("Jane Doe")


def test_show_in_finder_opens_the_folder_of_the_files(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revealed: list[Path] = []
    monkeypatch.setattr(export_dialog, "reveal", revealed.append)
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: saved(tmp_path))
    qtbot.mouseClick(d.finder_button, Qt.MouseButton.LeftButton)
    assert revealed == [tmp_path]


def test_reveal_asks_the_system_to_open_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(opened.append))
    export_dialog.reveal(tmp_path)
    assert opened == [QUrl.fromLocalFile(str(tmp_path))]


def test_the_close_button_closes_the_dialog(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: saved(tmp_path))
    d.show()
    qtbot.mouseClick(d.close_button, Qt.MouseButton.LeftButton)
    assert not d.isVisible()


# ---- a block -------------------------------------------------------------------------------------


def test_a_block_names_every_place_and_leaves_only_the_way_back(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hits = [
        LeakHit("MASKED-K4F7-1.docx: word/header1.xml", "[COMPANY_1]", "… [COMPANY_1] …"),
        LeakHit("MASKED-K4F7-2.docx: word/document.xml", "[PERSON_2]", "Dear [PERSON_2],", 3),
    ]
    blocked = ExportResult(None, [], hits, [], AI_INSTRUCTION, True)
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: blocked)
    text = d.summary_text()
    assert "Saving blocked: a marked value is still present" in text
    for hit in hits:
        assert hit.part in text and hit.context in text
    assert "3 places" in text  # a place that holds the value three times says so
    assert d.result is blocked
    assert d.back_button.isVisibleTo(d)
    assert not any(
        b.isVisibleTo(d) for b in (d.copy_button, d.finder_button, d.close_button, d.progress_bar)
    )
    assert not d.copy_button.isEnabled()
    assert app_ctx.case_store.list() == []  # nothing was saved


def test_the_way_back_closes_the_dialog(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = ExportResult(None, [], [LeakHit("word/x.xml", "[ID_1]", "[ID_1]")], [], "", True)
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: blocked)
    d.show()
    qtbot.mouseClick(d.back_button, Qt.MouseButton.LeftButton)
    assert not d.isVisible()


# ---- an export that fails ------------------------------------------------------------------------


def failing(error: Exception) -> Callable[..., ExportResult]:
    def fail(*_: object) -> ExportResult:
        raise error

    return fail


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (MaskError("The file is damaged and cannot be masked."), "damaged and cannot be masked"),
        (KeyStoreError("The MASK could not reach the macOS Keychain. Unlock it."), "Keychain"),
        (
            OSError(errno.ENOSPC, "No space left on device", "/Users/someone/Masked/x.docx"),
            "No space left on device",
        ),
    ],
    ids=["mask error", "keychain", "disk"],
)
def test_an_export_that_fails_says_why_and_still_finishes(
    qtbot: QtBot,
    app_ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    shown: str,
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, failing(error))  # it did not hang
    text = d.summary_text()
    assert shown in text and "/Users" not in text  # the message, never a path or a trace
    assert "Nothing was saved." in text
    assert d.result is None
    assert d.back_button.isVisibleTo(d) and not d.copy_button.isEnabled()
    assert not any(b.isVisibleTo(d) for b in (d.copy_button, d.finder_button, d.close_button))


def test_an_unexpected_error_is_a_plain_sentence_and_only_its_type_is_logged(
    qtbot: QtBot,
    app_ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="themask"):
        d = run_dialog(
            qtbot, app_ctx, tmp_path, monkeypatch, failing(RuntimeError("Secret Client Ltd"))
        )
    assert export_dialog.UNEXPECTED_MESSAGE in d.summary_text()
    assert "Secret" not in d.summary_text()
    assert "RuntimeError" in caplog.text  # the kind of error, for whoever looks into it
    assert "Secret" not in caplog.text  # a file name or a party never reaches the log
    assert d.result is None and d.back_button.isVisibleTo(d)


def test_a_context_without_an_engine_is_a_plain_message_too(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path
) -> None:
    app_ctx.engine = None
    d = ExportDialog()
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.finishedExport, timeout=1000):
        d.run([], empty_review(), ExportOptions(tmp_path), app_ctx)
    assert "detection engine" in d.summary_text() and d.result is None


# ---- how the window opens it ---------------------------------------------------------------------


@pytest.fixture
def window(qtbot: QtBot, app_ctx: AppContext, corpus: Path) -> MainWindow:
    """A window that shows the review of supply-01.docx."""
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=EXPORT_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    return w


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[tuple[ExportDialog, ...]]:
    """What ``ExportDialog.run`` was called with: the dialog, sources, review, options, context.

    The dialog does nothing, so that a test can look at what the window gave it.
    """
    calls: list[tuple[ExportDialog, ...]] = []
    monkeypatch.setattr(
        ExportDialog,
        "run",
        lambda self, sources, review, options, ctx: calls.append(
            (self, sources, review, options, ctx)
        ),
    )
    return calls


def a_case(case_id: str = "K4F7") -> Case:
    """A case whose key holds Northwind (numbered [COMPANY_3]) and a person who is not in supply-01."""
    return Case(
        case_id,
        datetime.now(UTC),
        ["earlier.docx"],
        [],
        [
            KeyEntry(
                "[COMPANY_3]", PlaceholderType.COMPANY, "Northwind Trading B.V.", ["Northwind"]
            ),
            KeyEntry("[PERSON_2]", PlaceholderType.PERSON, "Nobody Inthetext", []),
        ],
    )


def test_continuing_from_the_review_opens_the_dialog_with_the_review_and_the_settings(
    qtbot: QtBot, app_ctx: AppContext, window: MainWindow, opened: list[tuple[ExportDialog, ...]]
) -> None:
    app_ctx.settings.retention_days = 14
    qtbot.mouseClick(window.review_screen.export_button, Qt.MouseButton.LeftButton)
    assert len(opened) == 1
    dialog, sources, review, options, ctx = opened[0]
    assert isinstance(dialog, ExportDialog) and dialog.isVisible()
    assert dialog is window.export_dialog and dialog.parent() is window
    assert sources is window.sources and review is window.review_screen.review
    assert ctx is app_ctx
    assert isinstance(options, ExportOptions)
    assert options.out_dir == app_ctx.settings.out_dir
    assert options.retention_days == 14
    assert options.redline_split is False and options.existing_case is None
    assert list(options.existing_codes) == []
    assert window.current_screen_name() == "review"  # the dialog is on top of the review


def test_a_redline_review_is_exported_as_one(
    qtbot: QtBot,
    app_ctx: AppContext,
    corpus: Path,
    monkeypatch: pytest.MonkeyPatch,
    opened: list[tuple[ExportDialog, ...]],
) -> None:
    monkeypatch.setattr(main_window, "ask_redline", lambda parent: True)
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=EXPORT_TIMEOUT):
        w.open_files([corpus / "supply-03.docx"], redline_split=None)
    qtbot.mouseClick(w.review_screen.export_button, Qt.MouseButton.LeftButton)
    assert opened[0][3].redline_split is True


def test_a_file_added_to_a_case_is_exported_into_that_case(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, opened: list[tuple[ExportDialog, ...]]
) -> None:
    case = a_case()
    app_ctx.case_store.save(case)
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=EXPORT_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False, case_id="K4F7")
    qtbot.mouseClick(w.review_screen.export_button, Qt.MouseButton.LeftButton)
    options = opened[0][3]
    assert options.existing_case == case and list(options.existing_codes) == ["K4F7"]


def test_the_codes_in_use_include_the_case_files_that_cannot_be_read(
    qtbot: QtBot, app_ctx: AppContext, corpus: Path, opened: list[tuple[ExportDialog, ...]]
) -> None:
    app_ctx.case_store.save(a_case("K4F7"))
    (app_ctx.case_store.dir / "B2C3.mask").write_bytes(b"not a case")  # a new case never takes it
    w = MainWindow(app_ctx)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.analysisFinished, timeout=EXPORT_TIMEOUT):
        w.open_files([corpus / "supply-01.docx"], redline_split=False)
    qtbot.mouseClick(w.review_screen.export_button, Qt.MouseButton.LeftButton)
    assert sorted(opened[0][3].existing_codes) == ["B2C3", "K4F7"]


def test_a_second_request_while_the_dialog_is_open_is_ignored(
    qtbot: QtBot, window: MainWindow, opened: list[tuple[ExportDialog, ...]]
) -> None:
    qtbot.mouseClick(window.review_screen.export_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.review_screen.export_button, Qt.MouseButton.LeftButton)
    assert len(opened) == 1


def test_the_dialog_can_be_opened_again_once_it_was_closed(
    qtbot: QtBot, window: MainWindow, opened: list[tuple[ExportDialog, ...]]
) -> None:
    qtbot.mouseClick(window.review_screen.export_button, Qt.MouseButton.LeftButton)
    first = window.export_dialog
    assert first is not None
    first.reject()
    assert window.export_dialog is None
    qtbot.mouseClick(window.review_screen.export_button, Qt.MouseButton.LeftButton)
    assert len(opened) == 2 and window.export_dialog is not first


def test_a_store_that_cannot_be_read_is_said_in_words_and_no_dialog_opens(
    qtbot: QtBot,
    app_ctx: AppContext,
    window: MainWindow,
    opened: list[tuple[ExportDialog, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(main_window, "show_error", lambda parent, msg: shown.append(msg))
    keychain = "The MASK could not reach the macOS Keychain. Unlock it."

    def refuse() -> list[object]:
        raise KeyStoreError(keychain)

    monkeypatch.setattr(app_ctx.case_store, "list", refuse)
    qtbot.mouseClick(window.review_screen.export_button, Qt.MouseButton.LeftButton)
    assert shown == [keychain] and opened == [] and window.export_dialog is None


def test_closing_the_window_waits_for_the_export_to_end(
    qtbot: QtBot,
    app_ctx: AppContext,
    window: MainWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finished = threading.Event()

    def slow(*_: object) -> ExportResult:
        threading.Event().wait(0.4)
        finished.set()
        return saved(tmp_path)

    replace_export(monkeypatch, slow)
    qtbot.mouseClick(window.review_screen.export_button, Qt.MouseButton.LeftButton)
    dialog = window.export_dialog
    assert dialog is not None and dialog.is_running()
    window.close()  # a thread must never be destroyed while it runs
    assert finished.is_set() and not dialog.is_running()
