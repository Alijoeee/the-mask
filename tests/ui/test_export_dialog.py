"""The export dialog: the masked files made in a thread, and what the owner is told afterwards.

The first three tests are the brief's: a successful export lists the files and puts the
instruction on the clipboard, a blocked one shows where a marked value is still present and offers
nothing but the way back, and the case is saved. The rest cover what the brief leaves to the
builder: an export that fails, what was left visible on purpose or cannot be checked, the buttons,
the dialog that cannot be closed while it works, and the way the window opens it.

The design pass made the dialog a sheet (560 points wide, a sheet of its window on the Mac, in
four states: working, saved, blocked, failed): the last section holds the tests of what the
sheet shows and how it looks in the light and the dark appearance.
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
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

from tests.fixtures.d3_look import appears_in
from tests.helpers import analysed
from themask.detect.lists import CaseLists, UserLists
from themask.errors import KeyStoreError, MaskError
from themask.export import ExportOptions, ExportResult
from themask.instruction import AI_INSTRUCTION
from themask.leakcheck import LeakHit
from themask.model import Case, Group, KeyEntry, MaskedFile, PlaceholderType
from themask.review import ReviewState
from themask.ui import export_dialog, main_window, theme
from themask.ui.cards import folder_trail, style_vars
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
    # The sheet of the design pass offers "Back to review" next to "Done" after a save; the old
    # dialog had "Close" alone.
    assert d.back_button.isVisibleTo(d) and not d.progress_bar.isVisibleTo(d)


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


# ---- the sheet ------------------------------------------------------------------------------------


def many_files(tmp_path: Path, **more: object) -> ExportResult:
    """A save of two files, in a folder of its own."""
    result = saved(tmp_path, **more)
    result.outputs.append(tmp_path / "MASKED-K4F7-2.docx")
    return result


def key_of(values: int) -> list[KeyEntry]:
    return [
        KeyEntry(f"[PERSON_{n}]", PlaceholderType.PERSON, f"Person {n}", []) for n in range(values)
    ]


def blocked_result() -> ExportResult:
    hits = [
        LeakHit(
            "MASKED-K4F7-1.docx: word/header1.xml",
            "[COMPANY_1]",
            "\N{HORIZONTAL ELLIPSIS} [COMPANY_1] \N{HORIZONTAL ELLIPSIS}",
        ),
        LeakHit("MASKED-K4F7-2.docx: word/document.xml", "[PERSON_2]", "Dear [PERSON_2],", 3),
    ]
    return ExportResult(None, [], hits, [], AI_INSTRUCTION, True)


def test_on_the_mac_the_dialog_is_a_sheet_of_its_window_and_elsewhere_a_modal_dialog(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    monkeypatch.setattr(export_dialog, "_is_mac", lambda: True)
    sheet = ExportDialog(window)
    assert sheet.windowType() == Qt.WindowType.Sheet
    assert sheet.windowModality() == Qt.WindowModality.WindowModal  # modal to its window only
    monkeypatch.setattr(export_dialog, "_is_mac", lambda: False)
    dialog = ExportDialog(window)
    assert dialog.windowType() == Qt.WindowType.Dialog and dialog.isModal()
    for each in (sheet, dialog):
        each.deleteLater()


@pytest.mark.parametrize("state", ["saved", "blocked", "failed"])
def test_the_sheet_is_560_points_wide_after_every_outcome(
    qtbot: QtBot,
    app_ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    fakes: dict[str, Callable[..., ExportResult]] = {
        "saved": lambda *a: many_files(tmp_path),
        "blocked": lambda *a: blocked_result(),
        "failed": failing(MaskError("The file is damaged.")),
    }
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, fakes[state])
    d.show()
    assert d.width() == export_dialog.WIDTH
    assert d.minimumWidth() == d.maximumWidth() == export_dialog.WIDTH  # and it cannot be dragged
    assert d.height() == d.minimumHeight() == d.maximumHeight()  # as tall as its words need


def test_the_progress_state_is_the_bar_and_the_masking_words(
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
        assert d.headline_label.text() == "Masking\N{HORIZONTAL ELLIPSIS}"
        assert d.width() == export_dialog.WIDTH
        assert d.progress_bar.isVisibleTo(d) and d.progress_bar.maximum() == 0  # busy
        assert not d.badge.isVisibleTo(d) and not d.buttons.isVisibleTo(d)
        assert not d.saved_body.isVisibleTo(d) and not d.hits_list.isVisibleTo(d)
        assert "Nothing is saved unless the check passes." in d.caption_label.text()
    finally:
        with qtbot.waitSignal(d.finishedExport, timeout=10_000):
            gate.set()


def test_long_output_names_are_cut_in_the_middle_and_named_in_the_tooltip(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_name = "B" * 145 + ".docx"
    result = saved(tmp_path)
    result.outputs[:] = [tmp_path / long_name, tmp_path / "MASKED-K4F7-2.docx"]
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    d.show()
    label = d.file_names_label
    assert label.text().split("\n") == [long_name, "MASKED-K4F7-2.docx"]  # all of it is kept
    lines = label.displayed_lines()
    assert lines[1] == "MASKED-K4F7-2.docx"
    assert "\N{HORIZONTAL ELLIPSIS}" in lines[0] and lines[0].endswith(".docx")
    assert label.fontMetrics().horizontalAdvance(lines[0]) <= label.contentsRect().width()
    assert label.toolTip() == label.text()  # every name in full
    assert d.width() == export_dialog.WIDTH  # the sheet keeps its width


def test_the_success_state_is_the_mockup_s_sheet(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = saved(tmp_path)
    assert result.case is not None
    result.case.entries.extend(key_of(13))  # a case of 14 values, with the one it was made with
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    d.show()
    assert d.headline_label.text() == "Masked copy saved"
    assert d.caption_label.text() == (
        "Every marked value was replaced and checked twice. Nothing of the original left this Mac."
    )
    assert d.badge.isVisibleTo(d) and d.badge.width() == 56  # the green check
    assert d.file_names_label.text() == "MASKED-K4F7.docx"
    assert d.file_caption_label.text() == (
        f"{folder_trail(tmp_path)} \N{MIDDLE DOT} case K4F7 \N{MIDDLE DOT} 14 values hidden"
        " \N{MIDDLE DOT} key kept for 30 days"
    )
    assert d.finder_button.text() == "Show in Finder"
    assert d.copy_button.text() == "Copy instruction"
    assert d.back_button.text() == "Back to review" and d.close_button.text() == "Done"
    assert d.close_button.objectName() == "primary" and d.close_button.isDefault()
    assert not d.hits_list.isVisibleTo(d) and not d.progress_bar.isVisibleTo(d)


def test_a_case_of_one_value_and_one_day_is_not_written_in_the_plural(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = saved(tmp_path)
    assert result.case is not None
    result.case.retention_days = 1
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    assert "1 value hidden" in d.file_caption_label.text()
    assert "key kept for 1 day" in d.file_caption_label.text()
    assert "1 days" not in d.file_caption_label.text()


def test_several_files_are_one_card_with_every_name_and_one_finder_button(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: many_files(tmp_path))
    assert d.headline_label.text() == "Masked copies saved"
    assert d.file_names_label.text().split("\n") == ["MASKED-K4F7.docx", "MASKED-K4F7-2.docx"]
    assert len(d.findChildren(QToolButton, "detailsButton")) == 1


def test_the_instruction_box_holds_the_instruction_word_for_word_and_copies_it(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: saved(tmp_path))
    assert d.instruction_label.text() == AI_INSTRUCTION
    assert d.instruction_label.textFormat() == Qt.TextFormat.PlainText
    assert d.copy_button.objectName() == "primary"
    QApplication.clipboard().setText("something else")
    qtbot.mouseClick(d.copy_button, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == AI_INSTRUCTION  # what the owner pastes into the AI


def test_the_details_count_what_was_found_and_open_and_close_with_their_arrow(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = saved(
        tmp_path,
        allowed_hits=[
            LeakHit("word/document.xml", "[COMPANY_1]", "\N{HORIZONTAL ELLIPSIS} Acme", 1)
        ],
        unverifiable=["[PERCENT_1]", "[ID_2]"],
    )
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    d.show()
    button = d.details_button
    assert isinstance(button, QToolButton)
    assert button.text() == (
        "Details \N{MIDDLE DOT} 1 left visible on purpose \N{MIDDLE DOT} 2 not checkable"
        " \N{MIDDLE DOT} 0 found unmarked"
    )
    assert not d.details.isVisibleTo(d) and button.arrowType() == Qt.ArrowType.RightArrow
    height = d.height()
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert d.details.isVisibleTo(d) and button.arrowType() == Qt.ArrowType.DownArrow
    assert d.height() > height and d.width() == export_dialog.WIDTH  # the sheet makes room
    text = d.details.toPlainText()
    assert (
        "Left visible on purpose:" in text
        and "Not checkable (too short): [PERCENT_1], [ID_2]" in text
    )
    assert "not marked by you" not in text  # nothing of that kind was found: no such heading
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not d.details.isVisibleTo(d) and d.height() == height


def test_what_the_owner_never_marked_opens_the_details_by_itself(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = saved(tmp_path)
    result.unmarked = [
        Group("g1", PlaceholderType.PERSON, "Jane Doe", {"Jane Doe"}, [], "[PERSON_9]")
    ]
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    assert "1 found unmarked" in d.details_button.text()
    assert d.details_button.isChecked() and d.details.isVisibleTo(d)
    assert "Also found in the masked copy \N{EM DASH} not marked by you:" in d.details.toPlainText()
    assert "Jane Doe (PERSON)" in d.details.toPlainText()


def test_a_save_with_nothing_beyond_the_marks_says_so_when_the_details_are_opened(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: saved(tmp_path))
    assert d.details_button.text().endswith(
        "0 left visible on purpose \N{MIDDLE DOT} 0 not checkable \N{MIDDLE DOT} 0 found unmarked"
    )
    assert d.details.toPlainText() == export_dialog.NOTHING_TO_REPORT
    assert not d.details.isVisibleTo(d)


def test_the_details_of_a_second_export_are_not_the_first_one_s(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = saved(tmp_path)
    result.unmarked = [Group("g1", PlaceholderType.PERSON, "Jane Doe", set(), [], "[PERSON_9]")]
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    assert d.details.isVisibleTo(d)
    d._show_saved(saved(tmp_path))  # the sheet says what it is told: a clean save closes them
    assert not d.details_button.isChecked() and not d.details.isVisibleTo(d)
    assert d.details.toPlainText() == export_dialog.NOTHING_TO_REPORT


def test_a_block_is_a_red_tinted_header_over_the_places_and_the_way_back(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: blocked_result())
    d.show()
    assert d.header.property("tone") == "danger"  # the style sheet tints it red
    assert d.headline_label.text() == "Saving blocked: a marked value is still present"
    assert d.caption_label.text() == export_dialog.BLOCKED_ADVICE
    assert d.badge.isVisibleTo(d) and not d.saved_body.isVisibleTo(d)
    assert d.hits_list.isVisibleTo(d) and d.hits_list.count() == 2
    first, second = d.hits_list.item(0), d.hits_list.item(1)
    assert first is not None and second is not None
    assert (
        first.data(export_dialog._HitDelegate.PART_ROLE) == "MASKED-K4F7-1.docx: word/header1.xml"
    )
    assert second.data(export_dialog._HitDelegate.CONTEXT_ROLE) == "Dear [PERSON_2],"
    assert second.data(export_dialog._HitDelegate.PLACES_ROLE) == "3 places"
    assert first.data(export_dialog._HitDelegate.PLACES_ROLE) == ""  # one place says nothing more
    assert "3 places" in second.text()  # and a reader of the list hears it
    assert [b.text() for b in (d.back_button, d.close_button) if b.isVisibleTo(d)] == [
        "Back to review"
    ]
    assert not d.copy_button.isEnabled() and not d.finder_button.isVisibleTo(d)


def test_the_tint_of_a_block_does_not_stay_for_the_next_state(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: blocked_result())
    d._show_saved(saved(tmp_path))
    assert d.header.property("tone") == "plain" and not d.hits_list.isVisibleTo(d)


def test_a_long_list_of_places_scrolls_inside_the_sheet(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hits = [
        LeakHit(f"MASKED-K4F7.docx: word/part{n}.xml", "[ID_1]", f"[ID_1] {n}") for n in range(40)
    ]
    result = ExportResult(None, [], hits, [], AI_INSTRUCTION, True)
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    d.show()
    assert d.hits_list.count() == 40
    assert d.hits_list.height() == export_dialog.HITS_SHOWN * export_dialog.HIT_ROW + 2
    assert d.hits_list.verticalScrollBar().maximum() > 0  # the rest is a scroll away


def test_a_failure_is_plain_words_and_the_way_back(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(
        qtbot, app_ctx, tmp_path, monkeypatch, failing(MaskError("The file is damaged."))
    )
    d.show()
    assert d.headline_label.text() == "The masked files could not be saved"
    assert d.caption_label.text() == "Nothing was saved. The file is damaged."
    assert d.header.property("tone") == "plain" and not d.badge.isVisibleTo(d)  # plain text
    assert not d.saved_body.isVisibleTo(d) and not d.hits_list.isVisibleTo(d)
    assert [b.text() for b in (d.back_button, d.close_button) if b.isVisibleTo(d)] == [
        "Back to review"
    ]


def test_the_caption_of_a_failure_is_text_not_markup(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, failing(MaskError("<b>Acme</b> & Co")))
    assert d.caption_label.textFormat() == Qt.TextFormat.PlainText
    assert "<b>Acme</b> & Co" in d.caption_label.text()


def test_the_sheet_can_be_read_by_a_screen_reader(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: saved(tmp_path))
    assert d.accessibleName() == "Export"
    assert "MASKED-K4F7.docx" in d.accessibleDescription()  # what summary_text() says
    assert d.accessibleDescription() == d.summary_text()
    assert d.details.accessibleName() and d.hits_list.accessibleName()
    for button in (d.copy_button, d.finder_button, d.back_button, d.close_button):
        assert button.text()  # a real button with words, not an icon alone


def test_escape_closes_a_finished_sheet_and_the_way_back_is_a_rejection(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: saved(tmp_path))
    d.show()
    results: list[int] = []
    d.finished.connect(results.append)
    qtbot.keyClick(d, Qt.Key.Key_Escape)
    assert not d.isVisible() and results == [export_dialog.QDialog.DialogCode.Rejected]


def test_done_accepts_and_back_to_review_rejects(
    qtbot: QtBot, app_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: saved(tmp_path))
    codes: list[int] = []
    d.finished.connect(codes.append)
    d.show()
    qtbot.mouseClick(d.back_button, Qt.MouseButton.LeftButton)
    d.show()
    qtbot.mouseClick(d.close_button, Qt.MouseButton.LeftButton)
    assert codes == [
        export_dialog.QDialog.DialogCode.Rejected,
        export_dialog.QDialog.DialogCode.Accepted,
    ]


# ---- the look ------------------------------------------------------------------------------------


def test_the_sheet_is_drawn_in_the_colours_of_its_appearance_when_saved(
    qtbot: QtBot,
    app_ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    d3_appearance: str,
    d3_shot: object,
) -> None:
    t = theme.tokens(d3_appearance)
    result = saved(
        tmp_path,
        allowed_hits=[LeakHit("word/document.xml", "[COMPANY_1]", "\N{HORIZONTAL ELLIPSIS} Acme")],
        unverifiable=["[PERCENT_1]"],
    )
    assert result.case is not None
    result.case.entries.extend(key_of(13))
    # Where the owner's files are by default, so that the picture says what the mockup says.
    result.outputs = [Path.home() / "Documents" / "The MASK" / "MASKED-K4F7.docx"]
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: result)
    assert d.file_caption_label.text().startswith(
        "Documents \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} The MASK"
    )
    d.show()
    qtbot.waitExposed(d)
    image = d3_shot(d, "export-success", d3_appearance)  # type: ignore[operator]
    assert image.width() == export_dialog.WIDTH * round(image.devicePixelRatio())
    assert image.pixelColor(3, 3) == QColor(t.panel)  # the sheet's own ground
    assert appears_in(image, t.success_bg, d.badge, d)  # the disc behind the check
    assert appears_in(image, t.ground, d.finder_button.parentWidget() or d, d)  # the file card
    assert appears_in(image, t.accent_soft, d.instruction_label.parentWidget() or d, d)
    assert appears_in(image, t.accent, d.close_button, d)  # Done is the one primary button
    assert appears_in(image, t.accent, d.copy_button, d)  # and so is Copy, on the soft box


def test_the_blocked_sheet_is_red_tinted_in_both_appearances(
    qtbot: QtBot,
    app_ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    d3_appearance: str,
    d3_shot: object,
) -> None:
    t = theme.tokens(d3_appearance)
    d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: blocked_result())
    d.show()
    qtbot.waitExposed(d)
    image = d3_shot(d, "export-blocked", d3_appearance)  # type: ignore[operator]
    values = style_vars(t)
    assert appears_in(image, values["danger_bg"], d.header, d)
    assert appears_in(image, t.danger, d.badge, d)  # the exclamation mark
    assert not appears_in(image, t.success, d.header, d)  # and no green anywhere in the header
    assert d.back_button.isVisibleTo(d)


def test_the_sheet_follows_the_system_from_light_to_dark(
    qtbot: QtBot,
    app_ctx: AppContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qapp: QApplication,
) -> None:
    palette, sheet, font = qapp.palette(), qapp.styleSheet(), qapp.font()
    try:
        monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "light")
        theme.apply(qapp)
        d = run_dialog(qtbot, app_ctx, tmp_path, monkeypatch, lambda *a: saved(tmp_path))
        d.show()
        light = d.grab().toImage().pixelColor(3, 3)
        monkeypatch.setenv(theme.APPEARANCE_VARIABLE, "dark")
        qapp.setPalette(theme.palette("dark"))  # what the follower does when the system changes
        qapp.setStyleSheet(theme.stylesheet("dark"))
        qtbot.waitUntil(lambda: d.grab().toImage().pixelColor(3, 3) != light, timeout=2000)
        assert d.grab().toImage().pixelColor(3, 3) == QColor(theme.tokens("dark").panel)
        assert light == QColor(theme.tokens("light").panel)
    finally:
        qapp.setPalette(palette)
        qapp.setStyleSheet(sheet)
        qapp.setFont(font)
