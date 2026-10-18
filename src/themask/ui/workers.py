"""The threads: the analysis of the files the owner chose, and the loading of the engine.

Both take seconds and neither may freeze the window, so each runs in a thread of its own and
reports by signals, which Qt hands to the window's thread. What a thread tells the owner is plain
English. What it writes to the log is the kind of an unexpected error and nothing else, as the
rule in logging_setup.py says: the text of an error may quote a file name, and a file name tells
who the parties are.

``AnalysisWorker.finished`` takes the place of QThread's own signal of that name, which has no
payload; Qt still sends that one when the thread ends, to anyone who connects by its signature.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal

from themask.detect.pipeline import analyze
from themask.errors import MaskError
from themask.export import combined_text, load_sources

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import CaseLists, UserLists
    from themask.model import KeyEntry

_LOG = logging.getLogger(__name__)

UNEXPECTED_MESSAGE = "Something went wrong while analysing the file."
ENGINE_MESSAGE = "The MASK could not load its detection engine."

# The steps of an analysis and how far along the progress bar each one starts. The pipeline finds
# and groups in one call, so "grouping" says the groups are ready and the review is being made.
LOADING = (5, "loading")
READING = (25, "reading")
FINDING = (40, "finding")
GROUPING = (85, "grouping")
DONE = (100, "done")


def load_default_engine() -> Engine:
    """The detection engine with its English model (it takes a few seconds)."""
    # Imported here, not at the top: Presidio and spaCy take seconds to import, and the window
    # must not wait for them.
    from themask.detect.engine import Engine

    return Engine()


class AnalysisWorker(QThread):
    """Reads the files, finds what to hide in them and groups it, in a thread of its own.

    ``progress(percent, step)`` is sent when each step starts, with 100 and "done" last;
    ``finished((sources, analysis))`` carries what ``load_sources`` and ``analyze`` made; or
    ``failed(message)`` says in plain words why there is nothing. ``case_lists`` is the case's
    lists: the analysis adds the terms its documents define, so whoever builds the review from
    the result must use this same object. ``seed_entries`` is the key of the case a file is added
    to.
    """

    progress = Signal(int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        paths: list[Path],
        redline_split: bool,
        engine: Engine,
        user_lists: UserLists,
        case_lists: CaseLists,
        seed_entries: list[KeyEntry] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = list(paths)
        self._redline_split = redline_split
        self._engine = engine
        self._user_lists = user_lists
        self._case_lists = case_lists
        self._seed_entries = seed_entries

    def run(self) -> None:
        try:
            self._analyse()
        except MaskError as error:
            self.failed.emit(error.user_message)
        except OSError as error:
            # strerror is what the system says ("No such file or directory"), without the name.
            self.failed.emit(f"The file could not be read: {error.strerror or error}")
        except Exception as error:  # noqa: BLE001 - a thread must not end by an unseen error
            _LOG.error("analysis failed error=%s", type(error).__name__)
            self.failed.emit(UNEXPECTED_MESSAGE)

    def _analyse(self) -> None:
        self.progress.emit(*LOADING)
        sources = load_sources(self._paths, self._redline_split)
        self.progress.emit(*READING)
        combined = combined_text(sources)
        self.progress.emit(*FINDING)
        analysis = analyze(
            combined, self._engine, self._user_lists, self._case_lists, self._seed_entries
        )
        self.progress.emit(*GROUPING)
        self.progress.emit(*DONE)
        self.finished.emit((sources, analysis))


class EngineWorker(QThread):
    """Makes the detection engine in a thread of its own: ``loaded(engine)`` or ``failed(message)``.

    ``factory`` makes the engine; without one it is ``load_default_engine``, looked up when the
    thread runs.
    """

    loaded = Signal(object)
    failed = Signal(str)

    def __init__(
        self, factory: Callable[[], Engine] | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._factory = factory

    def run(self) -> None:
        started = time.perf_counter()
        try:
            engine = (self._factory or load_default_engine)()
        except MaskError as error:
            self.failed.emit(error.user_message)
        except OSError as error:  # for instance, the language model is not installed
            self.failed.emit(f"{ENGINE_MESSAGE} {error.strerror or error}")
        except Exception as error:  # noqa: BLE001 - see AnalysisWorker.run
            _LOG.error("engine failed error=%s", type(error).__name__)
            self.failed.emit(ENGINE_MESSAGE)
        else:
            _LOG.info("engine loaded seconds=%.2f", time.perf_counter() - started)
            self.loaded.emit(engine)
