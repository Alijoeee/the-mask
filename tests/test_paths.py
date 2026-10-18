"""Where The MASK keeps its files, and the data folder of its own that every test gets."""

import os
import stat

from themask import paths


def test_data_dir_follows_the_variable(tmp_path, monkeypatch):
    target = tmp_path / "elsewhere" / "The MASK"
    monkeypatch.setenv("THEMASK_DATA_DIR", str(target))
    assert paths.data_dir() == target
    assert target.is_dir()


def test_folders_and_lists_file_are_in_the_data_dir(data_dir):
    assert paths.data_dir() == data_dir
    assert paths.cases_dir() == data_dir / "cases"
    assert paths.log_dir() == data_dir / "logs"
    assert paths.lists_path() == data_dir / "lists.json"
    assert (data_dir / "cases").is_dir() and (data_dir / "logs").is_dir()
    assert not (data_dir / "lists.json").exists()  # a path to write to, not a file made up front


def test_new_folders_are_private(tmp_path, monkeypatch):
    monkeypatch.setenv("THEMASK_DATA_DIR", str(tmp_path / "new"))
    for folder in (paths.data_dir(), paths.cases_dir(), paths.log_dir()):
        assert stat.S_IMODE(folder.stat().st_mode) & 0o077 == 0, folder


def test_default_is_the_platforms_folder_for_app_data(tmp_path, monkeypatch):
    asked = []

    def user_data_dir(appname, appauthor=None):
        asked.append((appname, appauthor))
        return str(tmp_path / "platform")

    monkeypatch.delenv("THEMASK_DATA_DIR")
    monkeypatch.setattr(paths.platformdirs, "user_data_dir", user_data_dir)
    assert paths.data_dir() == tmp_path / "platform"
    assert asked == [("The MASK", False)]


def test_a_blank_variable_is_not_a_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("THEMASK_DATA_DIR", "")
    monkeypatch.setattr(paths.platformdirs, "user_data_dir", lambda *a, **k: str(tmp_path / "p"))
    assert paths.data_dir() == tmp_path / "p"  # not the current directory


def test_every_test_has_an_empty_data_dir_of_its_own(data_dir, tmp_path):
    assert os.environ["THEMASK_DATA_DIR"] == str(data_dir)
    assert data_dir.is_dir() and not any(data_dir.iterdir())
    assert not any(tmp_path.iterdir())  # the test's own folder is left to the test
