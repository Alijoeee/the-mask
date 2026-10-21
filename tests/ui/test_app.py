"""What the application starts from: its settings, and the things its windows share."""

from __future__ import annotations

import errno
import json
import stat
from pathlib import Path

import pytest

from themask.errors import KeyStoreError, MaskError
from themask.keystore.cases import CaseStore
from themask.model import Case
from themask.paths import cases_dir, lists_path
from themask.ui import app
from themask.ui.app import AppContext, Settings, build_context, default_out_dir, settings_path


def test_the_default_settings() -> None:
    settings = Settings()
    assert settings.retention_days == 30
    assert settings.out_dir == Path.home() / "Documents" / "The MASK" == default_out_dir()


def test_the_settings_file_is_in_the_data_folder(data_dir: Path) -> None:
    assert settings_path() == data_dir / "settings.json"


def test_settings_are_saved_as_json_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    Settings(14, tmp_path / "Masked files").save(path)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "retention_days": 14,
        "out_dir": str(tmp_path / "Masked files"),
    }
    assert Settings.load(path) == Settings(14, tmp_path / "Masked files")


def test_saving_creates_the_folder_and_leaves_a_private_file_and_nothing_else(
    tmp_path: Path,
) -> None:
    path = tmp_path / "new" / "settings.json"
    Settings(7).save(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]
    Settings(9).save(path)  # again: replaced, with no stray temporary file
    assert Settings.load(path).retention_days == 9
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]


def test_a_failed_save_keeps_the_settings_that_were_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    Settings(7).save(path)

    def disk_full(source: object, destination: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", disk_full)
    with pytest.raises(OSError, match="disk full"):
        Settings(9).save(path)
    monkeypatch.undo()
    assert Settings.load(path).retention_days == 7
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_no_file_means_the_defaults(tmp_path: Path) -> None:
    assert Settings.load(tmp_path / "settings.json") == Settings()


@pytest.mark.parametrize(
    "content",
    [b"", b"not json", b"[]", b"null", b'"text"', b"\xff\xfe\xfd", b"{"],
    ids=["empty", "not json", "list", "null", "string", "not utf-8", "cut short"],
)
def test_a_damaged_file_means_the_defaults(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(content)
    assert Settings.load(path) == Settings()


@pytest.mark.parametrize("days", ["x", None, True, 0, -3, 366, 10**9, 2.5], ids=lambda v: repr(v))
def test_retention_that_makes_no_sense_is_the_default_and_the_rest_is_kept(
    tmp_path: Path, days: object
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"retention_days": days, "out_dir": str(tmp_path / "out")}))
    assert Settings.load(path) == Settings(30, tmp_path / "out")


@pytest.mark.parametrize("folder", [5, None, "", "   ", ["a"]], ids=lambda v: repr(v))
def test_an_output_folder_that_makes_no_sense_is_the_default_and_the_rest_is_kept(
    tmp_path: Path, folder: object
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"retention_days": 14, "out_dir": folder}))
    assert Settings.load(path) == Settings(14, default_out_dir())


def test_retention_from_one_to_365_days_is_kept(tmp_path: Path) -> None:
    for days in (1, 30, 365):
        path = tmp_path / f"{days}.json"
        path.write_text(json.dumps({"retention_days": days}))
        assert Settings.load(path).retention_days == days


def test_the_context_is_built_from_the_data_folder(data_dir: Path) -> None:
    lists_path().write_text(
        json.dumps({"always_hide": ["Project Falcon"], "never_hide": ["Mill"]}), encoding="utf-8"
    )
    settings_path().write_text(json.dumps({"retention_days": 7}), encoding="utf-8")
    ctx = build_context()
    assert isinstance(ctx, AppContext)
    assert ctx.engine is None  # the window loads it in a thread of its own
    assert (ctx.user_lists.always_hide, ctx.user_lists.never_hide) == (["Project Falcon"], ["Mill"])
    assert ctx.settings.retention_days == 7
    assert isinstance(ctx.case_store, CaseStore) and ctx.case_store.dir == cases_dir()


def test_a_new_data_folder_gives_empty_lists_and_default_settings(data_dir: Path) -> None:
    ctx = build_context()
    assert (ctx.user_lists.always_hide, ctx.user_lists.never_hide) == ([], [])
    assert ctx.settings == Settings()
    assert ctx.case_store.list() == []  # nothing stored, and the Keychain not asked


def test_the_cases_are_locked_with_the_key_in_the_keychain(
    data_dir: Path, sample_case: Case
) -> None:
    ctx = build_context()
    # Every test has a Keychain that always fails (tests/fixtures/keystore.py): it is the one asked.
    with pytest.raises(KeyStoreError, match="Keychain"):
        ctx.case_store.save(sample_case)


def test_lists_that_cannot_be_read_stop_the_start(data_dir: Path) -> None:
    # Taking a damaged file for empty lists would quietly stop hiding the owner's values.
    lists_path().write_text("this is not json", encoding="utf-8")
    with pytest.raises(MaskError, match="always-hide"):
        build_context()


def test_main_tells_the_owner_when_the_lists_cannot_be_read(
    qapp: object, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lists_path().write_text("this is not json", encoding="utf-8")
    shown: list[str] = []
    monkeypatch.setattr(app, "show_error", lambda parent, message: shown.append(message))
    monkeypatch.setattr(
        app.theme, "apply", lambda application: None
    )  # the test's app keeps its look
    assert app.main() == 1  # no window, and a failure for the system to see
    assert len(shown) == 1 and "always-hide" in shown[0]


def test_main_tells_the_owner_when_the_data_folder_cannot_be_used(
    qapp: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> AppContext:
        raise PermissionError(errno.EACCES, "Permission denied", "/Users/someone/Library")

    shown: list[str] = []
    monkeypatch.setattr(app, "build_context", refuse)
    monkeypatch.setattr(app, "show_error", lambda parent, message: shown.append(message))
    monkeypatch.setattr(app.theme, "apply", lambda application: None)
    assert app.main() == 1
    assert len(shown) == 1 and "Permission denied" in shown[0] and "/Users" not in shown[0]
