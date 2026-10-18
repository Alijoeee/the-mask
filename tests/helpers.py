"""Helpers shared by tests of several modules."""

from __future__ import annotations

import zipfile
from pathlib import Path


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
