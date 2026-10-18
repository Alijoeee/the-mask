"""Writes the three files in this folder that pretend to be Word files, for the error tests.

Run it from the repository root with ``uv run python tests/docx/fixtures/make_fixtures.py``. It
writes the same bytes every time, so the committed files can always be made again.

- ``not-a-docx.doc``: the 512-byte header of an OLE compound file. An old binary .doc is such a
  file, and so is a .docx that Word has encrypted with a password.
- ``corrupt.docx``: 512 bytes of fixed pseudo-random data, neither a zip nor a compound file.
- ``encrypted.docx``: a small compound file (header, FAT sector, directory sector) whose directory
  names an empty stream ``EncryptionInfo``, the stream Word writes when it encrypts a .docx with a
  password.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

CFB_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
FREE_SECTOR = 0xFFFFFFFF
END_OF_CHAIN = 0xFFFFFFFE
FAT_SECTOR = 0xFFFFFFFD


def cfb_header() -> bytes:
    """The 512-byte header of a version 3 compound file: FAT in sector 0, directory in sector 1."""
    fields = struct.pack(
        "<8s16sHHHHH6sIIIIIIIII",
        CFB_MAGIC,
        bytes(16),  # class id, always zero
        0x003E,  # minor version
        0x0003,  # major version 3: 512-byte sectors
        0xFFFE,  # byte order mark: little-endian
        9,  # sector size 2**9
        6,  # mini sector size 2**6
        bytes(6),  # reserved
        0,  # directory sectors (always 0 in version 3)
        1,  # FAT sectors
        1,  # first directory sector
        0,  # transaction signature
        0x1000,  # mini stream cut-off size
        END_OF_CHAIN,  # first mini FAT sector
        0,  # mini FAT sectors
        END_OF_CHAIN,  # first DIFAT sector
        0,  # DIFAT sectors
    )
    difat = struct.pack("<I", 0) + struct.pack("<I", FREE_SECTOR) * 108  # the FAT is sector 0
    header = fields + difat
    assert len(header) == 512
    return header


def directory_entry(name: str, kind: int) -> bytes:
    """A 128-byte directory entry; ``kind`` is 5 for the root entry and 2 for a stream."""
    encoded = (name + "\0").encode("utf-16-le")
    entry = struct.pack(
        "<64sHBBIII16sIQQIQ",
        encoded,
        len(encoded),
        kind,
        1,  # colour: black
        FREE_SECTOR,  # left sibling: none
        FREE_SECTOR,  # right sibling: none
        FREE_SECTOR if kind == 2 else 1,  # child: the root entry's child is the stream
        bytes(16),  # class id
        0,  # state bits
        0,  # created
        0,  # modified
        END_OF_CHAIN,  # first sector of the stream: none, it is empty
        0,  # stream size
    )
    assert len(entry) == 128
    return entry


def pseudo_random(seed: bytes, size: int) -> bytes:
    """``size`` bytes that look random and are the same on every computer."""
    blocks = (hashlib.sha256(seed + i.to_bytes(4, "big")).digest() for i in range(size // 32 + 1))
    return b"".join(blocks)[:size]


def fixture_bytes() -> dict[str, bytes]:
    """The content of each fixture file, by file name."""
    fat = struct.pack("<II", FAT_SECTOR, END_OF_CHAIN) + struct.pack("<I", FREE_SECTOR) * 126
    directory = directory_entry("Root Entry", 5) + directory_entry("EncryptionInfo", 2)
    corrupt = pseudo_random(b"corrupt.docx", 512)
    assert not corrupt.startswith((b"PK", CFB_MAGIC))
    return {
        "not-a-docx.doc": cfb_header(),
        "corrupt.docx": corrupt,
        "encrypted.docx": cfb_header() + fat + directory.ljust(512, b"\0"),
    }


def main() -> None:
    here = Path(__file__).parent
    for name, data in fixture_bytes().items():
        (here / name).write_bytes(data)


if __name__ == "__main__":
    main()
