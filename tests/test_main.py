"""The entry point: ``python -m themask`` puts the safeguards in place and opens the window.

The program that runs it in a process of its own does three things differently from a real start,
so that the test needs neither a screen nor the language model: Qt draws offscreen (the conftest
sets it), the engine is a stand-in that loads at once, and the event loop returns as soon as it is
asked to run. Everything else, the start-up included, is the real code.
"""

from __future__ import annotations

import gc
import os
import subprocess
import sys
import weakref
from typing import TYPE_CHECKING

import pytest

from themask.about import APP_NAME

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

PROGRAM = """
import gc, runpy, socket
from PySide6.QtWidgets import QApplication

import themask.ui.workers as workers
from themask.ui.app import GarbageCollector

workers.load_default_engine = lambda: object()  # no language model

def run_the_loop(*arguments):
    windows = [w.windowTitle() for w in QApplication.topLevelWidgets() if w.isVisible()]
    print("visible windows:", windows)
    collector = QApplication.instance().findChild(GarbageCollector)
    print("collector running:", collector is not None and collector.timer.isActive())
    print("gc enabled while the window lives:", gc.isenabled())
    return 0

QApplication.exec = run_the_loop
try:
    runpy.run_module("themask", run_name="__main__")
except SystemExit as stop:
    print("exit:", stop.code)
print("gc enabled after:", gc.isenabled())
try:
    socket.create_connection(("127.0.0.1", 9))
except OSError as error:
    print(type(error).__name__)
"""


def run_python(data_dir: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Python with ``arguments``, in a process of its own that keeps its files in ``data_dir``."""
    environment = {**os.environ, "THEMASK_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.fixture
def started(data_dir: Path) -> subprocess.CompletedProcess[str]:
    """The entry point run once, as the program above describes."""
    result = run_python(data_dir, "-c", PROGRAM)
    assert result.returncode == 0, result.stderr
    return result


def test_python_m_themask_opens_the_window_and_ends_cleanly(
    started: subprocess.CompletedProcess[str], data_dir: Path
) -> None:
    lines = started.stdout.splitlines()
    assert f"visible windows: ['{APP_NAME}']" in lines
    assert "exit: 0" in lines
    assert (data_dir / "logs" / "themask.log").is_file()  # the log was set up
    assert (data_dir / "cases").is_dir()  # and the data folder made


def test_the_entry_point_installs_the_network_guard(
    started: subprocess.CompletedProcess[str],
) -> None:
    assert started.stdout.splitlines()[-1] == "NetworkBlockedError"


def test_the_entry_point_prints_nothing_to_the_terminal_of_its_own(
    started: subprocess.CompletedProcess[str],
) -> None:
    assert started.stdout.splitlines() == [
        f"visible windows: ['{APP_NAME}']",
        "collector running: True",
        "gc enabled while the window lives: False",
        "exit: 0",
        "gc enabled after: True",
        "NetworkBlockedError",
    ]


# ---- the garbage collector (ruling R111) --------------------------------------------------------


def test_the_collector_runs_from_the_gui_thread_while_the_window_lives(
    started: subprocess.CompletedProcess[str],
) -> None:
    lines = started.stdout.splitlines()
    assert "collector running: True" in lines
    assert "gc enabled while the window lives: False" in lines
    assert "gc enabled after: True" in lines  # stopped at exit, once the workers are joined


def test_the_collector_collects_cyclic_garbage_when_its_timer_fires(qtbot: QtBot) -> None:
    from themask.ui.app import GarbageCollector

    class Node:
        me: Node | None = None

    collector = GarbageCollector(interval_ms=10)
    collector.start()
    try:
        node = Node()
        node.me = node
        gone = weakref.ref(node)
        del node
        assert gone() is not None  # a cycle: nothing frees it but the collector, which is off
        qtbot.waitUntil(lambda: gone() is None, timeout=3000)
    finally:
        collector.stop()
    assert gc.isenabled()


def test_the_collector_takes_the_generations_in_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    from themask.ui import app

    collected: list[int] = []
    monkeypatch.setattr(app.gc, "collect", lambda generation=2: collected.append(generation))
    collector = app.GarbageCollector()
    for _ in range(8):
        collector.collect()
    assert collected == [0, 0, 1, 0, 0, 2, 0, 0]
    assert collector.timer.interval() == 2000 and not collector.timer.isActive()
