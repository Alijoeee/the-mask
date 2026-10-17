"""The encrypted case store: one ``<id>.mask`` file per case, in a folder of the app's own.

A file holds only the AES-256-GCM blob of the case's JSON. There is no plaintext header: not an id,
not a date and not a file name is readable without the master key, because the file names of the
originals would tell who the parties are (ruling R10). Listing the cases therefore opens each file.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from themask.errors import CaseCorruptError
from themask.keystore.crypto import CORRUPT_MESSAGE, decrypt, encrypt
from themask.keystore.secrets import KeyStore
from themask.model import Case

SUFFIX = ".mask"
# A case is written under a name like this first and renamed when complete (see ``save``).
TEMP_PREFIX = ".saving-"
TEMP_SUFFIX = ".tmp"


@dataclass
class CaseSummary:
    """What the case list shows about a case; the key itself stays in the file."""

    id: str
    created_at: datetime
    expires_at: datetime
    source_files: list[str]
    n_entries: int


class CaseStore:
    """The cases kept in the folder ``dir``, locked with the master key from ``keystore``.

    A file that cannot be opened (damaged, cut short, locked with another key, or not a case of the
    name it carries) is skipped by ``list`` and named in ``unreadable``; ``load`` of it raises
    CaseCorruptError. Asking the key store for the master key can fail too, for instance when the
    Keychain refuses; that error is not caught here.
    """

    def __init__(self, dir: Path, keystore: KeyStore) -> None:
        self.dir = dir
        self.unreadable: list[Path] = []
        self._keystore = keystore

    def _path(self, case_id: str) -> Path:
        # An id comes from outside this class and becomes a file name, so it may not climb out of
        # the folder.
        if not case_id or case_id in {".", ".."} or Path(case_id).name != case_id:
            raise ValueError(f"Not a valid case id: {case_id!r}.")
        return self.dir / f"{case_id}{SUFFIX}"

    def _files(self) -> list[Path]:
        return sorted((p for p in self.dir.glob(f"*{SUFFIX}") if p.is_file()), key=lambda p: p.name)

    @staticmethod
    def _open(key: bytes, path: Path, blob: bytes) -> Case:
        """The case in ``blob``, the content of ``path``; CaseCorruptError if it is not one."""
        plaintext = decrypt(key, blob)
        try:
            case = Case.from_json(plaintext.decode("utf-8"))
        except ValueError as error:  # bad UTF-8 and "Not a stored case." both are
            raise CaseCorruptError(CORRUPT_MESSAGE) from error
        if path.name != f"{case.id}{SUFFIX}":  # for instance a file copied in Finder
            raise CaseCorruptError(CORRUPT_MESSAGE)
        return case

    def _scan(self) -> tuple[list[Case], list[Path]]:
        """Open every case file: the cases, in order of file name, and the files that do not open.

        The master key is fetched once, and only if there is a file to open.
        """
        paths = self._files()
        if not paths:
            return [], []
        key = self._keystore.get_or_create_master_key()
        cases: list[Case] = []
        unreadable: list[Path] = []
        for path in paths:
            try:
                cases.append(self._open(key, path, path.read_bytes()))
            except CaseCorruptError:
                unreadable.append(path)
        return cases, unreadable

    def save(self, case: Case) -> Path:
        """Lock ``case`` and write it to ``<dir>/<id>.mask``, replacing an earlier version.

        Creates the folder if it is missing. The file is private to its owner (mode 0o600). It is
        written next to the final file and renamed over it, so a crash or a full disk cannot leave
        a half-written case in place of a good one.
        """
        path = self._path(case.id)
        blob = encrypt(self._keystore.get_or_create_master_key(), case.to_json().encode("utf-8"))
        self.dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=self.dir, prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX
        )
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(blob)
                file.flush()
                os.fsync(file.fileno())
            os.chmod(temporary, 0o600)  # whatever the umask took away or left
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return path

    def load(self, case_id: str) -> Case:
        """The case with this id.

        Raises FileNotFoundError if there is no such case and CaseCorruptError if its file cannot
        be opened.
        """
        path = self._path(case_id)
        blob = path.read_bytes()
        return self._open(self._keystore.get_or_create_master_key(), path, blob)

    def delete(self, case_id: str) -> None:
        """Delete a case. One that is already gone is not an error."""
        self._path(case_id).unlink(missing_ok=True)

    def delete_all(self) -> None:
        """Delete every case file, those that cannot be opened too, and any a crashed save left.

        Needs no master key.
        """
        leftovers = self.dir.glob(f"{TEMP_PREFIX}*{TEMP_SUFFIX}")
        for path in [*self._files(), *leftovers]:
            path.unlink(missing_ok=True)

    def purge_expired(self, now: datetime | None = None) -> list[str]:
        """Delete the cases that are due, and return their ids in order of id.

        A case is due from the moment ``created_at`` plus its ``retention_days`` is reached.
        ``now`` defaults to the current time and must have a timezone. A file that cannot be opened
        is left alone: nothing in it is readable, so there is no telling when it was due.
        """
        if now is None:
            now = datetime.now(UTC)
        cases, _ = self._scan()
        expired = sorted(case.id for case in cases if case.expires_at <= now)
        for case_id in expired:
            self._path(case_id).unlink(missing_ok=True)
        return expired

    # Keep ``list`` the last method: below it, ``list[...]`` in a signature would mean this method.
    def list(self) -> list[CaseSummary]:
        """A summary of every case, newest first (cases from the same moment in order of id).

        Each file has to be opened to build its summary. The ones that cannot be opened are left
        out and put in ``unreadable``, which every call makes again.
        """
        cases, self.unreadable = self._scan()
        cases.sort(key=lambda case: case.created_at, reverse=True)  # stable: ties keep file order
        return [
            CaseSummary(
                id=case.id,
                created_at=case.created_at,
                expires_at=case.expires_at,
                source_files=case.source_files,
                n_entries=len(case.entries),
            )
            for case in cases
        ]
