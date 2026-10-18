"""The app's log, and the rule for what goes in it.

THE RULE: a log line carries counts, types, durations and file sizes, and nothing else. Never a
value found in a document, never the words around one, never a name of a person or a company,
never a file name (not even without its extension: it says who the parties are). When a line must
say what it is about, it says how many, what kind, how long or how big:

    analyze characters=48211 findings=93 seconds=1.37

That goes for the message of an exception too, which may quote the text it stopped at: log the
kind of error, not its text. Every module that logs follows this rule, and so does every later
task that adds a log line.

``setup_logging`` sends the records of the ``themask`` logger, and so of every module of the app,
to one rotating file in the log folder. The file handler is on that logger only, so what other
libraries log never reaches the file. Presidio's debug output prints the words around each finding,
which is document content; its logger is held at WARNING whatever level is asked for, in case a
handler of some other logger ever collects it.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from themask.paths import log_dir

LOG_FILE_NAME = "themask.log"
MAX_BYTES = 1_000_000  # 1 MB, then the file is renamed to a backup and a new one is started
BACKUP_COUNT = 3
FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"

_APP_LOGGER = "themask"
_PRESIDIO_LOGGER = "presidio-analyzer"
# The name the file handler goes by, to find it again when the function is called a second time.
_HANDLER_NAME = "themask-log-file"


def setup_logging(level: str = "INFO") -> Path:
    """Start the app's log at ``level`` ("DEBUG", "INFO", "WARNING", ...) and return its file.

    The file is ``themask.log`` in the log folder, 1 MB at most, with three older ones kept
    beside it. Calling it again does not add a second handler; when the data folder has changed
    since, the log moves to the new folder.
    """
    path = log_dir() / LOG_FILE_NAME
    logger = logging.getLogger(_APP_LOGGER)
    _write_to(logger, path)
    logger.setLevel(level)
    logging.getLogger(_PRESIDIO_LOGGER).setLevel(logging.WARNING)
    return path


def _write_to(logger: logging.Logger, path: Path) -> None:
    """Make the file ``path`` the only one ``logger`` writes to."""
    current = logging.getHandlerByName(_HANDLER_NAME)
    if isinstance(current, RotatingFileHandler) and current.baseFilename == os.path.abspath(path):
        return
    if current is not None:
        logger.removeHandler(current)
        current.close()
    handler = RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(FORMAT))
    logger.addHandler(handler)
