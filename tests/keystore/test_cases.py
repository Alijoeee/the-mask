"""The encrypted case store: what is on disk, what is listed and what is deleted."""

import errno
import json
import os
import stat
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

import themask.keystore as package
from themask.errors import CaseCorruptError
from themask.keystore.cases import CaseStore, CaseSummary
from themask.keystore.crypto import decrypt, encrypt
from themask.keystore.secrets import KeychainKeyStore, KeyStore, MemoryKeyStore
from themask.model import Case, KeyEntry, PlaceholderType

CORRUPT = "This case file is damaged or was written by another computer and cannot be opened."
OCT_17 = datetime(2026, 10, 17, tzinfo=UTC)


def make_case(case_id: str, created_at: datetime = OCT_17, retention_days: int = 30) -> Case:
    """A small case whose file name and one person are named after its id."""
    return Case(
        case_id,
        created_at,
        [f"{case_id}.docx"],
        [],
        [KeyEntry("[PERSON_1]", PlaceholderType.PERSON, f"Person {case_id}", [])],
        retention_days,
    )


class CountingKeyStore:
    """A key store that counts how often it is asked for the key."""

    def __init__(self) -> None:
        self.key = os.urandom(32)
        self.calls = 0

    def get_or_create_master_key(self) -> bytes:
        self.calls += 1
        return self.key


class LockedKeyStore:
    """A key store that fails the test if anything asks it for the key."""

    def get_or_create_master_key(self) -> bytes:
        raise AssertionError("The master key should not have been fetched here.")


def test_save_load_list_delete(case_store: CaseStore, sample_case: Case) -> None:
    p = case_store.save(sample_case)
    assert case_store.load(sample_case.id) == sample_case and oct(p.stat().st_mode)[-3:] == "600"
    assert [s.id for s in case_store.list()] == [sample_case.id]
    case_store.delete(sample_case.id)
    assert case_store.list() == []


def test_values_not_on_disk(case_store: CaseStore, sample_case: Case) -> None:
    raw = case_store.save(sample_case).read_bytes()
    # Not even the file names: they would give away who the parties are (ruling R10).
    for text in (
        "John Smith",
        "Mr Smith",
        "NL91 ABNA 0417 1643 00",
        "a.docx",
        "MASKED-K4F7.docx",
        "[PERSON_1]",
        "[IBAN_1]",
    ):
        assert text.encode() not in raw


def test_the_file_is_nothing_but_the_encrypted_case(
    case_store: CaseStore, keystore: KeyStore, sample_case: Case
) -> None:
    raw = case_store.save(sample_case).read_bytes()
    assert decrypt(keystore.get_or_create_master_key(), raw) == sample_case.to_json().encode()


def test_save_creates_the_folder_and_names_the_file_after_the_case(
    tmp_path: Path, keystore: KeyStore, sample_case: Case
) -> None:
    folder = tmp_path / "data" / "cases"
    store = CaseStore(folder, keystore)
    assert store.dir == folder and not folder.exists()
    path = store.save(sample_case)
    assert path == folder / "K4F7.mask" and path.is_file()
    assert list(folder.iterdir()) == [path]


@pytest.mark.parametrize("umask", [0o000, 0o022, 0o077, 0o277])
def test_the_file_is_private_to_its_owner_whatever_the_umask(
    case_store: CaseStore, sample_case: Case, umask: int
) -> None:
    case_store.dir.mkdir()
    previous = os.umask(umask)
    try:
        path = case_store.save(sample_case)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_saving_again_replaces_the_case_and_leaves_nothing_else_behind(
    case_store: CaseStore, sample_case: Case
) -> None:
    case_store.save(sample_case)
    path = case_store.dir / "K4F7.mask"
    path.chmod(0o644)
    changed = replace(sample_case, retention_days=7)
    case_store.save(changed)
    assert case_store.load("K4F7") == changed
    assert [p.name for p in case_store.dir.iterdir()] == ["K4F7.mask"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_failed_save_keeps_the_stored_case_and_leaves_nothing_else_behind(
    case_store: CaseStore, sample_case: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_store.save(sample_case)
    before = (case_store.dir / "K4F7.mask").read_bytes()

    def disk_full(source: object, destination: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(OSError, match="disk full"):
        case_store.save(replace(sample_case, retention_days=7))
    monkeypatch.undo()

    assert (case_store.dir / "K4F7.mask").read_bytes() == before
    assert case_store.load("K4F7") == sample_case
    assert [p.name for p in case_store.dir.iterdir()] == ["K4F7.mask"]


def test_a_case_with_non_ascii_text_roundtrips(case_store: CaseStore) -> None:
    case = Case(
        "ZZ99",
        datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC),
        ["Überträge – Å.docx", "株式会社.docx"],
        [],
        [KeyEntry("[COMPANY_1]", PlaceholderType.COMPANY, "Zoë Müller-Ålesund B.V.", ["Müller"])],
    )
    case_store.save(case)
    assert case_store.load("ZZ99") == case


def test_list_of_a_folder_that_does_not_exist_is_empty(case_store: CaseStore) -> None:
    assert not case_store.dir.exists()
    assert case_store.list() == []
    assert case_store.unreadable == []


def test_list_summarises_each_case(case_store: CaseStore, sample_case: Case) -> None:
    case_store.save(sample_case)
    assert case_store.list() == [
        CaseSummary(
            id="K4F7",
            created_at=datetime(2026, 10, 17, 9, 0, tzinfo=UTC),
            expires_at=datetime(2026, 11, 16, 9, 0, tzinfo=UTC),
            source_files=["a.docx"],
            n_entries=2,
        )
    ]


def test_list_puts_the_newest_case_first(case_store: CaseStore) -> None:
    # The ids are in neither alphabetical order nor its reverse, so only the dates can sort these.
    for case_id, day in (("K4F7", 2), ("B2C3", 4), ("Z9Z9", 1), ("M5N6", 3)):
        case_store.save(make_case(case_id, datetime(2026, 10, day, tzinfo=UTC)))
    assert [s.id for s in case_store.list()] == ["B2C3", "M5N6", "K4F7", "Z9Z9"]


def test_list_puts_cases_made_at_the_same_moment_in_order_of_id(case_store: CaseStore) -> None:
    for case_id in ("M5N6", "B2C3", "K4F7"):
        case_store.save(make_case(case_id))
    assert [s.id for s in case_store.list()] == ["B2C3", "K4F7", "M5N6"]


def test_list_ignores_whatever_is_not_a_case_file(case_store: CaseStore, sample_case: Case) -> None:
    case_store.save(sample_case)
    (case_store.dir / "notes.txt").write_text("not a case")
    (case_store.dir / ".saving-x1y2z3.tmp").write_bytes(b"left over by a crash")
    (case_store.dir / "folder.mask").mkdir()
    assert [s.id for s in case_store.list()] == ["K4F7"]
    assert case_store.unreadable == []


def locked(case: Case, key: bytes) -> bytes:
    return encrypt(key, case.to_json().encode())


def with_last_byte_changed(blob: bytes) -> bytes:
    return blob[:-1] + bytes([blob[-1] ^ 1])


# Ways a file can be named like a case but not hold one, as (case, master key) -> file content.
DAMAGED_FILES: dict[str, Callable[[Case, bytes], bytes]] = {
    "empty": lambda case, key: b"",
    "not encrypted": lambda case, key: case.to_json().encode(),
    "one byte changed": lambda case, key: with_last_byte_changed(locked(case, key)),
    "cut short": lambda case, key: locked(case, key)[:-10],
    "locked with another key": lambda case, key: locked(case, os.urandom(32)),
    "text that is not JSON": lambda case, key: encrypt(key, b"not json"),
    "JSON that is not a case": lambda case, key: encrypt(key, b'{"id": "K4F7"}'),
    "bytes that are not UTF-8": lambda case, key: encrypt(key, b"\xff\xfe\xfd"),
    # Ruling R108: a key holding the same placeholder twice is no case the app wrote.
    "a placeholder twice in the key": lambda case, key: encrypt(
        key, with_a_placeholder_twice(case).encode()
    ),
}


def with_a_placeholder_twice(case: Case) -> str:
    """The case's JSON with its first key entry repeated under another value."""
    data = json.loads(case.to_json())
    data["entries"].append({**data["entries"][0], "value": "Somebody Else"})
    return json.dumps(data)


def plant(
    store: CaseStore,
    keystore: KeyStore,
    case: Case,
    damage: Callable[[Case, bytes], bytes],
    case_id: str = "K4F7",
) -> Path:
    """Write a damaged file for ``case_id`` into the store's folder, bypassing the store."""
    store.dir.mkdir(parents=True, exist_ok=True)
    path = store.dir / f"{case_id}.mask"
    path.write_bytes(damage(case, keystore.get_or_create_master_key()))
    return path


@pytest.mark.parametrize("damage", DAMAGED_FILES.values(), ids=DAMAGED_FILES.keys())
def test_load_refuses_a_file_that_is_not_an_intact_case(
    case_store: CaseStore,
    keystore: KeyStore,
    sample_case: Case,
    damage: Callable[[Case, bytes], bytes],
) -> None:
    plant(case_store, keystore, sample_case, damage)
    with pytest.raises(CaseCorruptError) as caught:
        case_store.load("K4F7")
    assert caught.value.user_message == CORRUPT


@pytest.mark.parametrize("damage", DAMAGED_FILES.values(), ids=DAMAGED_FILES.keys())
def test_list_skips_a_file_that_is_not_an_intact_case_and_reports_it(
    case_store: CaseStore,
    keystore: KeyStore,
    sample_case: Case,
    damage: Callable[[Case, bytes], bytes],
) -> None:
    case_store.save(make_case("B2C3"))
    bad = plant(case_store, keystore, sample_case, damage)
    assert [s.id for s in case_store.list()] == ["B2C3"]
    assert case_store.unreadable == [bad]


def test_a_file_that_cannot_be_read_is_unreadable_not_an_error(
    case_store: CaseStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_store.save(make_case("B2C3"))
    refused = case_store.save(make_case("K4F7"))
    read_bytes = Path.read_bytes

    def read(self: Path) -> bytes:
        if self == refused:
            raise PermissionError(errno.EACCES, "Permission denied")
        return read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read)
    assert [s.id for s in case_store.list()] == ["B2C3"]
    assert case_store.unreadable == [refused]
    assert case_store.purge_expired(datetime(2030, 1, 1, tzinfo=UTC)) == ["B2C3"]  # no crash
    assert refused.exists()  # a file nobody can read is left alone


def test_unreadable_is_made_again_by_every_listing(
    case_store: CaseStore, keystore: KeyStore, sample_case: Case
) -> None:
    assert case_store.unreadable == []
    bad = plant(case_store, keystore, sample_case, DAMAGED_FILES["empty"])
    case_store.list()
    assert case_store.unreadable == [bad]
    bad.unlink()
    case_store.list()
    assert case_store.unreadable == []


def test_unreadable_files_come_in_the_order_of_their_names(
    case_store: CaseStore, keystore: KeyStore, sample_case: Case
) -> None:
    for case_id in ("Z9Z9", "B2C3", "M5N6"):
        plant(case_store, keystore, sample_case, DAMAGED_FILES["empty"], case_id)
    assert case_store.list() == []
    assert [p.name for p in case_store.unreadable] == ["B2C3.mask", "M5N6.mask", "Z9Z9.mask"]


def test_wrong_key_is_corrupt(case_store: CaseStore, sample_case: Case) -> None:
    case_store.save(sample_case)
    other = CaseStore(case_store.dir, MemoryKeyStore())
    with pytest.raises(CaseCorruptError) as caught:
        other.load(sample_case.id)
    assert caught.value.user_message == CORRUPT


def test_a_store_with_another_key_lists_nothing_and_reports_every_file(
    case_store: CaseStore, sample_case: Case
) -> None:
    case_store.save(sample_case)
    case_store.save(make_case("B2C3"))
    other = CaseStore(case_store.dir, MemoryKeyStore())
    assert other.list() == []
    assert [p.name for p in other.unreadable] == ["B2C3.mask", "K4F7.mask"]


def test_load_all_gives_every_case_that_opens_with_its_key_newest_first(
    case_store: CaseStore, keystore: KeyStore, sample_case: Case
) -> None:
    case_store.save(make_case("B2C3", OCT_17))
    case_store.save(make_case("K4F7", datetime(2026, 10, 20, tzinfo=UTC)))
    case_store.save(make_case("M5N6", datetime(2026, 10, 18, tzinfo=UTC)))
    plant(case_store, keystore, sample_case, DAMAGED_FILES["empty"], "Z9Z9")
    cases = case_store.load_all()
    assert [c.id for c in cases] == ["K4F7", "M5N6", "B2C3"]
    # What ``list`` leaves in the file is here: the key itself, and the files' names.
    assert cases[0].entries == make_case("K4F7").entries
    assert cases[0].source_files == ["K4F7.docx"]
    assert [p.name for p in case_store.unreadable] == ["Z9Z9.mask"]  # reported like ``list`` does


def test_load_all_puts_cases_made_at_the_same_moment_in_order_of_id(case_store: CaseStore) -> None:
    for case_id in ("M5N6", "B2C3", "K4F7"):
        case_store.save(make_case(case_id))
    assert [c.id for c in case_store.load_all()] == ["B2C3", "K4F7", "M5N6"]


def test_load_all_of_a_folder_that_does_not_exist_is_empty(case_store: CaseStore) -> None:
    assert case_store.load_all() == [] and case_store.unreadable == []


def test_list_is_load_all_without_the_keys(case_store: CaseStore) -> None:
    case_store.save(make_case("B2C3", OCT_17, retention_days=7))
    case_store.save(make_case("K4F7", datetime(2026, 10, 20, tzinfo=UTC)))
    assert case_store.list() == [
        CaseSummary(c.id, c.created_at, c.expires_at, c.source_files, len(c.entries))
        for c in case_store.load_all()
    ]


def test_a_copy_of_a_case_file_under_another_name_is_not_a_second_case(
    case_store: CaseStore, sample_case: Case
) -> None:
    copy = case_store.dir / "K4F7 copy.mask"
    original = case_store.save(sample_case)
    copy.write_bytes(original.read_bytes())
    with pytest.raises(CaseCorruptError):
        case_store.load("K4F7 copy")
    assert [s.id for s in case_store.list()] == ["K4F7"]
    assert case_store.unreadable == [copy]


def test_load_of_a_case_that_is_not_there(case_store: CaseStore) -> None:
    with pytest.raises(FileNotFoundError):
        case_store.load("K4F7")  # not even the folder exists yet
    case_store.save(make_case("B2C3"))
    with pytest.raises(FileNotFoundError):
        case_store.load("K4F7")


@pytest.mark.parametrize(
    "case_id", ["", ".", "..", "../K4F7", "a/b", "/K4F7", "K4F7/", "sub/../K4F7"]
)
def test_a_case_id_that_is_not_a_plain_file_name_is_refused(
    case_store: CaseStore, sample_case: Case, case_id: str
) -> None:
    with pytest.raises(ValueError, match="case id"):
        case_store.save(replace(sample_case, id=case_id))
    with pytest.raises(ValueError, match="case id"):
        case_store.load(case_id)
    with pytest.raises(ValueError, match="case id"):
        case_store.delete(case_id)
    assert list(case_store.dir.parent.iterdir()) == []  # nothing written here or anywhere above


def test_delete_removes_only_that_case(case_store: CaseStore, sample_case: Case) -> None:
    case_store.save(sample_case)
    case_store.save(make_case("B2C3"))
    case_store.delete("K4F7")
    assert [s.id for s in case_store.list()] == ["B2C3"]


def test_delete_of_a_case_that_is_already_gone_is_not_an_error(case_store: CaseStore) -> None:
    case_store.delete("K4F7")  # not even the folder exists yet
    case_store.save(make_case("B2C3"))
    case_store.delete("K4F7")
    case_store.delete("B2C3")
    case_store.delete("B2C3")
    assert case_store.list() == []


def test_delete_all_removes_every_case_even_those_that_cannot_be_opened(
    case_store: CaseStore, keystore: KeyStore, sample_case: Case
) -> None:
    case_store.save(sample_case)
    case_store.save(make_case("B2C3"))
    plant(case_store, keystore, sample_case, DAMAGED_FILES["empty"], "Z9Z9")
    (case_store.dir / "notes.txt").write_text("not a case")
    case_store.delete_all()
    assert [p.name for p in case_store.dir.iterdir()] == ["notes.txt"]
    assert case_store.list() == [] and case_store.unreadable == []


def test_delete_all_also_removes_what_a_crashed_save_left_behind(
    case_store: CaseStore, sample_case: Case
) -> None:
    case_store.save(sample_case)
    (case_store.dir / ".saving-x1y2z3.tmp").write_bytes(b"half a case")
    (case_store.dir / "notes.txt").write_text("not a case")
    case_store.delete_all()
    assert [p.name for p in case_store.dir.iterdir()] == ["notes.txt"]


def test_delete_all_of_a_folder_that_does_not_exist(case_store: CaseStore) -> None:
    case_store.delete_all()
    assert not case_store.dir.exists()


def test_delete_unreadable_removes_that_file_and_only_that_file(
    case_store: CaseStore, keystore: KeyStore, sample_case: Case
) -> None:
    case_store.save(make_case("B2C3"))
    bad = plant(case_store, keystore, sample_case, DAMAGED_FILES["empty"], "Z9Z9")
    other = plant(case_store, keystore, sample_case, DAMAGED_FILES["cut short"], "M5N6")
    case_store.list()
    case_store.delete_unreadable("Z9Z9.mask")
    assert not bad.exists() and other.exists()
    assert case_store.unreadable == [other]
    assert [s.id for s in case_store.list()] == ["B2C3"]


def test_delete_unreadable_never_deletes_a_case_that_opens(
    case_store: CaseStore, sample_case: Case
) -> None:
    case_store.save(sample_case)
    case_store.list()
    with pytest.raises(ValueError, match="cannot be opened"):
        case_store.delete_unreadable("K4F7.mask")
    assert [s.id for s in case_store.list()] == ["K4F7"]


@pytest.mark.parametrize(
    "name", ["../outside.mask", "/etc/passwd", "", ".", "..", "sub/K4F7.mask", "notes.txt"]
)
def test_delete_unreadable_only_deletes_what_the_listing_reported(
    case_store: CaseStore,
    keystore: KeyStore,
    sample_case: Case,
    tmp_path: Path,
    name: str,
) -> None:
    plant(case_store, keystore, sample_case, DAMAGED_FILES["empty"])
    (case_store.dir / "notes.txt").write_text("not a case")
    outside = tmp_path / "outside.mask"
    outside.write_bytes(b"not a case either")
    case_store.list()
    with pytest.raises(ValueError):
        case_store.delete_unreadable(name)
    assert outside.exists() and (case_store.dir / "notes.txt").exists()
    assert [p.name for p in case_store.unreadable] == ["K4F7.mask"]


def test_delete_unreadable_of_a_file_that_is_gone_already_is_not_an_error(
    case_store: CaseStore, keystore: KeyStore, sample_case: Case
) -> None:
    bad = plant(case_store, keystore, sample_case, DAMAGED_FILES["empty"])
    case_store.list()
    bad.unlink()
    case_store.delete_unreadable("K4F7.mask")
    assert case_store.unreadable == []


def test_purge_expired(case_store: CaseStore, sample_case: Case) -> None:
    case_store.save(sample_case)
    assert (
        case_store.purge_expired(sample_case.created_at + timedelta(days=31)) == [sample_case.id]
        and case_store.list() == []
    )
    case_store.save(sample_case)
    assert case_store.purge_expired(sample_case.created_at + timedelta(days=29)) == []


def test_a_case_is_purged_from_the_moment_it_expires(
    case_store: CaseStore, sample_case: Case
) -> None:
    case_store.save(sample_case)
    due = sample_case.expires_at
    assert case_store.purge_expired(due - timedelta(microseconds=1)) == []
    assert case_store.purge_expired(due.astimezone(timezone(timedelta(hours=-7)))) == ["K4F7"]
    assert case_store.list() == []


def test_purge_expired_goes_by_each_cases_own_retention(case_store: CaseStore) -> None:
    case_store.save(make_case("K4F7", OCT_17, retention_days=7))
    case_store.save(make_case("B2C3", OCT_17, retention_days=30))
    case_store.save(make_case("M5N6", OCT_17 + timedelta(days=6), retention_days=7))
    assert case_store.purge_expired(OCT_17 + timedelta(days=8)) == ["K4F7"]
    assert [s.id for s in case_store.list()] == ["M5N6", "B2C3"]
    assert [s.expires_at for s in case_store.list()] == [
        OCT_17 + timedelta(days=13),
        OCT_17 + timedelta(days=30),
    ]


def test_purge_expired_names_every_case_it_deleted_in_order_of_id(case_store: CaseStore) -> None:
    for case_id in ("M5N6", "B2C3", "K4F7"):
        case_store.save(make_case(case_id))
    case_store.save(make_case("Z9Z9", OCT_17 + timedelta(days=20)))
    assert case_store.purge_expired(OCT_17 + timedelta(days=31)) == ["B2C3", "K4F7", "M5N6"]
    assert [s.id for s in case_store.list()] == ["Z9Z9"]


def test_purge_expired_goes_by_the_clock_when_not_told_the_time(case_store: CaseStore) -> None:
    case_store.save(make_case("K4F7", datetime(2020, 1, 1, tzinfo=UTC)))
    case_store.save(make_case("B2C3", datetime.now(UTC)))
    assert case_store.purge_expired() == ["K4F7"]
    assert [s.id for s in case_store.list()] == ["B2C3"]


def test_purge_expired_cannot_tell_how_old_an_unreadable_file_is_so_it_keeps_it(
    case_store: CaseStore, keystore: KeyStore, sample_case: Case
) -> None:
    case_store.save(sample_case)
    bad = plant(case_store, keystore, sample_case, DAMAGED_FILES["empty"], "Z9Z9")
    assert case_store.purge_expired(sample_case.created_at + timedelta(days=365)) == ["K4F7"]
    assert bad.exists()


def test_purge_expired_of_a_folder_that_does_not_exist(case_store: CaseStore) -> None:
    assert case_store.purge_expired() == []


def test_the_master_key_is_not_fetched_when_there_is_nothing_to_open(tmp_path: Path) -> None:
    store = CaseStore(tmp_path / "cases", LockedKeyStore())
    assert store.list() == []
    assert store.purge_expired() == []
    store.delete("K4F7")
    store.delete_all()
    with pytest.raises(FileNotFoundError):
        store.load("K4F7")


def test_deleting_does_not_need_the_master_key(tmp_path: Path, sample_case: Case) -> None:
    CaseStore(tmp_path, MemoryKeyStore()).save(sample_case)
    CaseStore(tmp_path, MemoryKeyStore()).save(make_case("B2C3"))
    store = CaseStore(tmp_path, LockedKeyStore())
    store.delete("K4F7")
    assert [p.name for p in tmp_path.glob("*.mask")] == ["B2C3.mask"]
    store.delete_all()
    assert list(tmp_path.glob("*.mask")) == []


def test_the_master_key_is_fetched_once_per_operation_and_not_once_per_file(
    tmp_path: Path,
) -> None:
    keys = CountingKeyStore()
    store = CaseStore(tmp_path, keys)
    for case_id in ("K4F7", "B2C3", "M5N6"):
        store.save(make_case(case_id))
    assert keys.calls == 3  # once per save
    keys.calls = 0
    store.load("K4F7")
    assert keys.calls == 1
    store.list()
    assert keys.calls == 2
    assert store.purge_expired(OCT_17) == []
    assert keys.calls == 3
    store.load_all()
    assert keys.calls == 4  # one for every case, not one for each


def test_the_package_exports_the_public_names() -> None:
    assert {name: getattr(package, name) for name in package.__all__} == {
        "CaseStore": CaseStore,
        "CaseSummary": CaseSummary,
        "KeyStore": KeyStore,
        "KeychainKeyStore": KeychainKeyStore,
        "MemoryKeyStore": MemoryKeyStore,
        "decrypt": decrypt,
        "encrypt": encrypt,
    }
