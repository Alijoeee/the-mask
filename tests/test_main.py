"""The temporary entry point: the guard, the log, then the name and version.

``python -m themask`` does only this until the window of Task 20 replaces it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from themask.about import APP_NAME, VERSION

if TYPE_CHECKING:
    from pathlib import Path


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


def test_python_m_themask_prints_the_name_and_version(data_dir: Path):
    result = run_python(data_dir, "-m", "themask")

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{APP_NAME} {VERSION}\n"
    assert result.stderr == ""
    assert (data_dir / "logs" / "themask.log").is_file()  # the log was set up


def test_the_entry_point_installs_the_network_guard(data_dir: Path):
    program = (
        "import runpy, socket\n"
        "runpy.run_module('themask', run_name='__main__')\n"
        "try:\n"
        "    socket.create_connection(('127.0.0.1', 9))\n"
        "except OSError as error:\n"
        "    print(type(error).__name__)\n"
    )

    result = run_python(data_dir, "-c", program)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"{APP_NAME} {VERSION}", "NetworkBlockedError"]
