"""Helpers shared by tests of several modules."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists
    from themask.export import SourceDoc
    from themask.model import Case
    from themask.review import ReviewState
    from themask.ui.app import AppContext


def plant(src: Path, part: str, payload: bytes, out: Path) -> Path:
    """A copy of the Word file ``src`` at ``out``, with ``payload`` written into ``part``.

    The payload goes just before the part's closing tag, so it lands inside the part's root
    element; a part the file does not have is added, holding the payload alone. Every other entry
    is copied byte for byte, in the zip's order. Returns ``out``.
    """
    with zipfile.ZipFile(src) as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for info, data in entries:
            if info.filename == part:
                closing = data.rindex(b"</")
                data = data[:closing] + payload + data[closing:]
            archive.writestr(info, data)
        if part not in {info.filename for info, _ in entries}:
            archive.writestr(part, payload)
    return out


def reviewed(
    paths: list[Path],
    engine: Engine,
    user_lists: UserLists,
    redline_split: bool = False,
    case: Case | None = None,
) -> tuple[list[SourceDoc], ReviewState]:
    """The files at ``paths`` loaded for an export, analysed, and their review as the app makes it.

    The review works with the case lists the analysis filled. A file added to ``case`` is
    analysed with the case's key, and its review reserves the key's placeholders (ruling R61).
    """
    # Imported here, not at the top: every test that plants a value imports this module.
    from themask.detect.lists import CaseLists
    from themask.detect.pipeline import analyze
    from themask.export import combined_text, load_sources
    from themask.review import ReviewState

    sources = load_sources(paths, redline_split)
    case_lists = CaseLists([], [], set())
    key = case.entries if case is not None else []
    analysis = analyze(combined_text(sources), engine, user_lists, case_lists, seed_entries=key)
    reserved = [entry.placeholder for entry in key]
    return sources, ReviewState.from_analysis(analysis, user_lists, case_lists, reserved)


def analysed(ctx: AppContext, paths: list[Path]) -> tuple[list[SourceDoc], ReviewState]:
    """The files at ``paths`` loaded, analysed and reviewed the way the window does it, with the
    engine and the owner's lists of ``ctx``: what the export dialog is given.
    """
    assert ctx.engine is not None, "the context of a test has its engine"
    return reviewed(paths, ctx.engine, ctx.user_lists)
