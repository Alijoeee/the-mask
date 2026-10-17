"""The encryption primitives and the two places a master key can live."""

import base64
import os
from collections.abc import Iterator
from contextlib import contextmanager

import keyring
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from keyring.backend import KeyringBackend

from themask.errors import CaseCorruptError
from themask.keystore.crypto import decrypt, encrypt
from themask.keystore.secrets import KeychainKeyStore, MemoryKeyStore

CORRUPT = "This case file is damaged or was written by another computer and cannot be opened."
KEYCHAIN_ITEM = ("The MASK", "master-key")


def test_roundtrip_and_tamper() -> None:
    k = os.urandom(32)
    blob = encrypt(k, b"secret")
    assert decrypt(k, blob) == b"secret"
    with pytest.raises(CaseCorruptError):
        decrypt(k, blob[:-1] + bytes([blob[-1] ^ 1]))


def test_the_blob_is_a_nonce_then_the_ciphertext_and_tag_of_standard_aes_gcm() -> None:
    key = os.urandom(32)
    blob = encrypt(key, b"secret")
    assert len(blob) == 12 + len(b"secret") + 16
    assert b"secret" not in blob
    # Read back with the library directly, so the layout is pinned and not just self-consistent.
    assert AESGCM(key).decrypt(blob[:12], blob[12:], None) == b"secret"


def test_every_encryption_uses_a_new_nonce() -> None:
    key = os.urandom(32)
    blobs = [encrypt(key, b"secret") for _ in range(20)]
    assert len({blob[:12] for blob in blobs}) == 20
    assert len(set(blobs)) == 20


def test_nothing_to_encrypt_roundtrips() -> None:
    key = os.urandom(32)
    blob = encrypt(key, b"")
    assert len(blob) == 12 + 16
    assert decrypt(key, blob) == b""


# One byte changed in each part of a six-byte secret's 34-byte blob: 12 of nonce, 6 of ciphertext
# and 16 of tag.
POSITIONS = {
    "first byte of the nonce": 0,
    "last byte of the nonce": 11,
    "first byte of the ciphertext": 12,
    "last byte of the ciphertext": 17,
    "first byte of the tag": 18,
    "last byte of the tag": 33,
}


@pytest.mark.parametrize("position", POSITIONS.values(), ids=POSITIONS.keys())
def test_a_changed_byte_anywhere_in_the_blob_is_detected(position: int) -> None:
    key = os.urandom(32)
    blob = bytearray(encrypt(key, b"secret"))
    assert len(blob) == 34
    blob[position] ^= 0x01
    with pytest.raises(CaseCorruptError):
        decrypt(key, bytes(blob))


def test_a_blob_that_lost_or_gained_a_byte_is_detected() -> None:
    key = os.urandom(32)
    blob = encrypt(key, b"secret")
    for damaged in (blob[1:], blob[:-1], blob + b"\x00", b"\x00" + blob):
        with pytest.raises(CaseCorruptError):
            decrypt(key, damaged)


def test_the_wrong_key_is_detected() -> None:
    blob = encrypt(os.urandom(32), b"secret")
    with pytest.raises(CaseCorruptError):
        decrypt(os.urandom(32), blob)


@pytest.mark.parametrize("size", [0, 1, 11, 12, 13, 27])
def test_a_blob_too_short_to_hold_a_nonce_and_a_tag_is_corrupt(size: int) -> None:
    with pytest.raises(CaseCorruptError):
        decrypt(os.urandom(32), os.urandom(size))


def test_a_corrupt_blob_reports_the_agreed_message_to_the_user() -> None:
    key = os.urandom(32)
    for blob in (encrypt(os.urandom(32), b"secret"), b"", b"x" * 12):  # wrong key, empty, short
        with pytest.raises(CaseCorruptError) as caught:
            decrypt(key, blob)
        assert caught.value.user_message == CORRUPT
        assert str(caught.value) == CORRUPT


@pytest.mark.parametrize("size", [0, 15, 16, 24, 31, 33, 64])
def test_only_a_256_bit_key_is_accepted(size: int) -> None:
    # AES-GCM itself would take 16 and 24 bytes too; the cases must never be locked with less.
    key = os.urandom(size)
    with pytest.raises(ValueError, match="32 bytes"):
        encrypt(key, b"secret")
    with pytest.raises(ValueError, match="32 bytes"):
        decrypt(key, encrypt(os.urandom(32), b"secret"))
    with pytest.raises(ValueError, match="32 bytes"):
        decrypt(key, b"")  # a wrong key is a mistake in the program, whatever the blob is


def test_memory_keystore_stable() -> None:
    ks = MemoryKeyStore()
    assert (
        ks.get_or_create_master_key() == ks.get_or_create_master_key()
        and len(ks.get_or_create_master_key()) == 32
    )


def test_every_memory_keystore_has_its_own_key() -> None:
    first, second = MemoryKeyStore(), MemoryKeyStore()
    assert first.get_or_create_master_key() != second.get_or_create_master_key()


class MemoryKeyring(KeyringBackend):
    """A keyring that is a dict, so a test never reads or writes the real Keychain.

    It has no priority, so keyring never picks it by itself: a test has to install it.
    """

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]  # keyring does not annotate it
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password


@contextmanager
def installed_memory_keyring() -> Iterator[MemoryKeyring]:
    """Put a MemoryKeyring in place of the system keyring, and put the system keyring back."""
    previous = keyring.get_keyring()
    memory = MemoryKeyring()
    keyring.set_keyring(memory)
    try:
        yield memory
    finally:
        keyring.set_keyring(previous)


@pytest.fixture
def memory_keyring() -> Iterator[MemoryKeyring]:
    with installed_memory_keyring() as memory:
        yield memory


def test_the_memory_keyring_gives_the_system_keyring_back() -> None:
    before = keyring.get_keyring()
    with installed_memory_keyring() as memory:
        assert keyring.get_keyring() is memory
    assert keyring.get_keyring() is before
    assert not isinstance(keyring.get_keyring(), MemoryKeyring)


def test_keychain_keystore_creates_a_random_32_byte_key_on_first_use(
    memory_keyring: MemoryKeyring,
) -> None:
    key = KeychainKeyStore().get_or_create_master_key()
    assert len(key) == 32
    assert list(memory_keyring.items) == [KEYCHAIN_ITEM]  # service "The MASK", account "master-key"
    assert base64.b64decode(memory_keyring.items[KEYCHAIN_ITEM], validate=True) == key


def test_keychain_keystore_keys_are_random() -> None:
    keys = set()
    for _ in range(3):
        with installed_memory_keyring():
            keys.add(KeychainKeyStore().get_or_create_master_key())
    assert len(keys) == 3


def test_keychain_keystore_gives_the_same_key_every_time(memory_keyring: MemoryKeyring) -> None:
    first = KeychainKeyStore().get_or_create_master_key()
    stored = dict(memory_keyring.items)
    after_a_restart = KeychainKeyStore()
    assert after_a_restart.get_or_create_master_key() == first
    assert after_a_restart.get_or_create_master_key() == first
    assert memory_keyring.items == stored  # found, not created again


def test_keychain_keystore_reads_a_key_that_is_already_in_the_keychain(
    memory_keyring: MemoryKeyring,
) -> None:
    key = os.urandom(32)
    entry = base64.b64encode(key).decode("ascii")
    memory_keyring.items[KEYCHAIN_ITEM] = entry
    assert KeychainKeyStore().get_or_create_master_key() == key
    assert memory_keyring.items == {KEYCHAIN_ITEM: entry}


DAMAGED_ENTRIES = {
    "empty": "",
    "not base64": "this is not base64!",
    "too short": base64.b64encode(os.urandom(16)).decode("ascii"),
    "too long": base64.b64encode(os.urandom(33)).decode("ascii"),
}


@pytest.mark.parametrize("entry", DAMAGED_ENTRIES.values(), ids=DAMAGED_ENTRIES.keys())
def test_a_damaged_keychain_entry_is_reported_and_never_replaced(
    memory_keyring: MemoryKeyring, entry: str
) -> None:
    # Replacing it would quietly lock the owner out of every case already stored.
    memory_keyring.items[KEYCHAIN_ITEM] = entry
    with pytest.raises(ValueError, match="damaged"):
        KeychainKeyStore().get_or_create_master_key()
    assert memory_keyring.items == {KEYCHAIN_ITEM: entry}
