"""The log: one rotating file in the data folder, and never a word of a document in it.

The rule is written at the top of themask/logging_setup.py: a log line carries counts, types,
durations and file sizes only. These tests check the file (where it is, its lines, its rotation,
that setting it up again adds nothing), that the engine, the first module that logs, follows the
rule, and that a whole export of a corpus contract, run with the log at DEBUG, leaves none of the
contract's values in it, also when the log is set up before the libraries are imported and every
logger of every library is listened to.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

import pytest

from themask.detect.lists import CaseLists
from themask.detect.pipeline import analyze
from themask.export import ExportOptions, combined_text, export_case, load_sources
from themask.logging_setup import setup_logging
from themask.paths import log_dir
from themask.review import ReviewState
from themask.textnorm import normalize

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists

MASK_LOGGER = "themask"
# The libraries whose debug output quotes the document (logging_setup.py says how).
QUOTING_LIBRARIES = ("presidio-analyzer", "pdfminer")
TIMESTAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}"


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    """setup_logging changes loggers that live as long as the process: put them back afterwards."""
    loggers = [logging.getLogger(name) for name in (MASK_LOGGER, *QUOTING_LIBRARIES)]
    mask = loggers[0]
    handlers = list(mask.handlers)
    levels = [logger.level for logger in loggers]
    yield
    for handler in list(mask.handlers):
        if handler not in handlers:
            mask.removeHandler(handler)
            handler.close()
    for logger, level in zip(loggers, levels, strict=True):
        logger.setLevel(level)


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


@pytest.mark.parametrize("name", QUOTING_LIBRARIES)
def test_libraries_that_quote_the_document_are_held_at_warning(name: str):
    library = logging.getLogger(name)
    library.setLevel(logging.DEBUG)  # at DEBUG its output quotes the words of the document

    setup_logging("DEBUG")

    assert library.level == logging.WARNING
    assert not library.isEnabledFor(logging.INFO)
    # A logger the library makes later has no level of its own and takes the hold from this one.
    assert not logging.getLogger(f"{name}.made_later").isEnabledFor(logging.DEBUG)


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


def test_log_has_no_document_content(
    corpus: Path,
    engine: Engine,
    lists: UserLists,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("THEMASK_DATA_DIR", str(tmp_path))
    log = setup_logging("DEBUG")
    srcs = load_sources([corpus / "supply-01.docx"], False)
    review = ReviewState.from_analysis(
        analyze(combined_text(srcs), engine, lists), lists, CaseLists([], [], set())
    )
    export_case(srcs, review, ExportOptions(tmp_path / "out"), engine, lists, lambda c: None)
    text = normalize(log.read_text())
    assert text
    for t in json.loads((corpus / "supply-01.truth.json").read_text()):
        assert normalize(t["value"]) not in text, t["value"]


# A fresh process, in the order the app starts in: the guard, then the log, and only then the
# libraries (Presidio, spaCy, pdfminer), which make their loggers when they are imported. The root
# logger is set to DEBUG and listened to, the worst case: whatever any library says at DEBUG
# would be heard. It exports a Word and a PDF contract of the corpus and reports what was heard.
LOG_FIRST = """
import json
import logging
import sys
import tempfile
from pathlib import Path

from themask.logging_setup import setup_logging
from themask.netguard import install_network_guard

install_network_guard()
corpus = Path(sys.argv[1])
log = setup_logging("DEBUG")

heard = []


class Listener(logging.Handler):
    def emit(self, record):
        heard.append((record.name, record.getMessage()))


logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(Listener())

from themask.detect.engine import Engine
from themask.detect.lists import CaseLists, UserLists
from themask.detect.pipeline import analyze
from themask.export import ExportOptions, combined_text, export_case, load_sources
from themask.review import ReviewState
from themask.textnorm import normalize

lists = UserLists([], [])
engine = Engine()
with tempfile.TemporaryDirectory() as out:
    for name in ("supply-01.docx", "supply-01.pdf"):
        sources = load_sources([corpus / name], False)
        analysis = analyze(combined_text(sources), engine, lists)
        review = ReviewState.from_analysis(analysis, lists, CaseLists([], [], set()))
        options = ExportOptions(Path(out) / name)
        export_case(sources, review, options, engine, lists, lambda case: None)

values = {
    normalize(t["value"]): t["value"]
    for t in json.loads((corpus / "supply-01.truth.json").read_text())
}
file_text = normalize(log.read_text())
report = {
    "heard": len(heard),
    "heard_from": sorted({name for name, _ in heard}),
    "leaks": sorted({name for name, text in heard for v in values if v in normalize(text)}),
    "file_size": len(file_text),
    "file_leaks": [value for key, value in values.items() if key in file_text],
    "levels": {
        name: logging.getLogger(name).getEffectiveLevel()
        for name in ("presidio-analyzer", "pdfminer", "pdfminer.psparser")
    },
}
print(json.dumps(report))
"""


def test_libraries_imported_after_the_log_is_set_up_stay_quiet(corpus: Path, data_dir: Path):
    result = subprocess.run(
        [sys.executable, "-c", LOG_FIRST, str(corpus)],
        env={**os.environ, "THEMASK_DATA_DIR": str(data_dir)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert "themask.detect.engine" in report["heard_from"]  # the listener works
    assert report["leaks"] == []  # no library, no module of ours said a value of the contract
    assert report["file_size"] > 0
    assert report["file_leaks"] == []
    assert report["levels"] == {
        "presidio-analyzer": logging.WARNING,
        "pdfminer": logging.WARNING,
        "pdfminer.psparser": logging.WARNING,  # a logger pdfminer made when it was imported
    }
