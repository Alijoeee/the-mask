"""The log: one rotating file in the data folder, and never a word of a document in it.

The rule is written at the top of themask/logging_setup.py: a log line carries counts, types,
durations and file sizes only. These tests check the file (where it is, its lines, its rotation,
that setting it up again adds nothing) and that the engine, the first module that logs, follows
the rule.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

import pytest

from themask.logging_setup import setup_logging
from themask.paths import log_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from themask.detect.engine import Engine

MASK_LOGGER = "themask"
PRESIDIO_LOGGER = "presidio-analyzer"
TIMESTAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}"


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """setup_logging changes loggers that live as long as the process: put them back afterwards."""
    mask = logging.getLogger(MASK_LOGGER)
    presidio = logging.getLogger(PRESIDIO_LOGGER)
    handlers = list(mask.handlers)
    mask_level, presidio_level = mask.level, presidio.level
    yield
    for handler in list(mask.handlers):
        if handler not in handlers:
            mask.removeHandler(handler)
            handler.close()
    mask.setLevel(mask_level)
    presidio.setLevel(presidio_level)


def file_handlers() -> list[RotatingFileHandler]:
    """The rotating file handlers on the app's logger."""
    return [
        handler
        for handler in logging.getLogger(MASK_LOGGER).handlers
        if isinstance(handler, RotatingFileHandler)
    ]


def test_the_log_is_a_file_in_the_log_folder(data_dir: Path):
    path = setup_logging()

    assert path == log_dir() / "themask.log"
    assert path == data_dir / "logs" / "themask.log"
    assert path.is_file()


def test_a_line_has_the_time_the_module_the_level_and_the_message():
    path = setup_logging("INFO")

    logging.getLogger("themask.example").info("read %d pages", 12)

    assert re.fullmatch(
        rf"{TIMESTAMP} themask\.example INFO read 12 pages", path.read_text().strip()
    )


def test_the_level_decides_what_is_written():
    path = setup_logging("INFO")
    logger = logging.getLogger("themask.example")

    logger.debug("quiet")
    logger.info("loud")
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0].endswith(" INFO loud")

    setup_logging("DEBUG")
    logger.debug("louder")
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert lines[1].endswith(" DEBUG louder")


def test_calling_it_twice_keeps_one_handler():
    first = setup_logging()
    second = setup_logging()

    assert first == second
    assert len(file_handlers()) == 1
    logging.getLogger("themask.example").info("once")
    assert len(first.read_text().splitlines()) == 1


def test_another_data_folder_moves_the_log_there(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first = setup_logging()

    monkeypatch.setenv("THEMASK_DATA_DIR", str(tmp_path / "elsewhere"))
    second = setup_logging()
    logging.getLogger("themask.example").info("moved")

    assert second == tmp_path / "elsewhere" / "logs" / "themask.log"
    assert len(file_handlers()) == 1
    assert "moved" in second.read_text()
    assert "moved" not in first.read_text()


def test_the_log_rotates_at_one_megabyte_and_keeps_three_backups():
    path = setup_logging("INFO")
    (handler,) = file_handlers()
    assert (handler.maxBytes, handler.backupCount) == (1_000_000, 3)
    logger = logging.getLogger("themask.example")
    filler = "x" * 1000

    for _ in range(1_100):  # a little over 1 MB
        logger.info("%s", filler)
    assert sorted(p.name for p in path.parent.iterdir()) == ["themask.log", "themask.log.1"]

    for _ in range(4_000):  # more than enough for the oldest backup to be dropped
        logger.info("%s", filler)
    assert sorted(p.name for p in path.parent.iterdir()) == [
        "themask.log",
        "themask.log.1",
        "themask.log.2",
        "themask.log.3",
    ]
    assert all(p.stat().st_size <= 1_000_000 for p in path.parent.iterdir())


def test_the_presidio_logger_is_held_at_warning():
    presidio = logging.getLogger(PRESIDIO_LOGGER)
    presidio.setLevel(logging.DEBUG)  # its debug output prints the words around each finding

    setup_logging("DEBUG")

    assert presidio.level == logging.WARNING
    assert not presidio.isEnabledFor(logging.INFO)


def test_the_engine_logs_counts_and_seconds_only(engine: Engine):
    path = setup_logging("DEBUG")
    text = (
        "Please invoice EUR 12,500.00 to Elena Marchetti (elena.marchetti@northwind.example) "
        "before Friday."
    )

    findings = engine.analyze(text)

    lines = [line for line in path.read_text().splitlines() if " themask.detect.engine " in line]
    assert findings  # there is something the line could have given away
    assert len(lines) == 1
    assert re.fullmatch(
        rf"{TIMESTAMP} themask\.detect\.engine INFO analyze "
        rf"characters={len(text)} findings={len(findings)} seconds=\d+\.\d\d",
        lines[0],
    )
    for finding in findings:
        assert finding.text not in lines[0]
    assert not set(re.findall(r"[A-Za-z]{3,}", text)) & set(re.findall(r"[A-Za-z]{3,}", lines[0]))
