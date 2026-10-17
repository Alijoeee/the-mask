"""Fixtures for the encrypted case store: a master key in memory, a store, and one sample case."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from themask.keystore.cases import CaseStore
from themask.keystore.secrets import KeyStore, MemoryKeyStore
from themask.model import Case, KeyEntry, MaskedFile, PlaceholderType


@pytest.fixture
def keystore() -> MemoryKeyStore:
    """A master key that lives in memory, so no test touches the real Keychain."""
    return MemoryKeyStore()


@pytest.fixture
def case_store(tmp_path: Path, keystore: KeyStore) -> CaseStore:
    """A case store in a folder that does not exist yet, so the first save has to create it."""
    return CaseStore(tmp_path / "cases", keystore)


@pytest.fixture
def sample_case() -> Case:
    """A case with two key entries, one of them with a variant."""
    return Case(
        "K4F7",
        datetime(2026, 10, 17, 9, 0, tzinfo=UTC),
        ["a.docx"],
        [MaskedFile("MASKED-K4F7.docx", "ab" * 32)],
        [
            KeyEntry("[PERSON_1]", PlaceholderType.PERSON, "John Smith", ["Mr Smith"]),
            KeyEntry("[IBAN_1]", PlaceholderType.IBAN, "NL91 ABNA 0417 1643 00", []),
        ],
    )
