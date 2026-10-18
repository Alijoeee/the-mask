"""Where the master key lives: the macOS Keychain in the app, plain memory in tests."""

import base64
import secrets
from typing import Protocol

import keyring
from keyring.errors import KeyringError

from themask.errors import KeyStoreError
from themask.keystore.crypto import KEY_SIZE

KEYCHAIN_SERVICE = "The MASK"
KEYCHAIN_ACCOUNT = "master-key"

UNREACHABLE_KEYCHAIN = (
    "The MASK could not reach the macOS Keychain. The key that locks your saved cases is kept"
    " there. Unlock your Keychain (and allow The MASK to use it when macOS asks), then try again."
)
DAMAGED_KEY = (
    f"The master key stored in the Keychain (service {KEYCHAIN_SERVICE!r}, account "
    f"{KEYCHAIN_ACCOUNT!r}) is damaged, so your saved cases cannot be opened. To start again with"
    " a new key, delete that item in Keychain Access."
)


class KeyStore(Protocol):
    """Somewhere that keeps the one master key that locks every case."""

    def get_or_create_master_key(self) -> bytes:
        """The 32-byte master key: made on the first call, the same one on every call after."""
        ...


class KeychainKeyStore:
    """The master key in the macOS Keychain, under service "The MASK" and account "master-key".

    The first call makes 32 random bytes and keeps them there, base64-encoded; later calls, in
    this run or any other, read them back. The owner has no password to remember: only this user
    on this computer can read the Keychain item.

    Raises KeyStoreError when the Keychain cannot be reached (it is locked, the owner refused, or
    there is none) and for an item that is not a base64-encoded 32-byte key. Such an item is left
    as it is: replacing it with a new key would quietly lock the owner out of every case already
    stored.
    """

    def get_or_create_master_key(self) -> bytes:
        try:
            stored = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
            if stored is None:
                key = secrets.token_bytes(KEY_SIZE)
                encoded = base64.b64encode(key).decode("ascii")
                keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, encoded)
                return key
        except KeyringError as error:
            raise KeyStoreError(UNREACHABLE_KEYCHAIN) from error
        try:
            key = base64.b64decode(stored, validate=True)
        except ValueError as error:  # binascii.Error is one
            raise KeyStoreError(DAMAGED_KEY) from error
        if len(key) != KEY_SIZE:
            raise KeyStoreError(DAMAGED_KEY)
        return key


class MemoryKeyStore:
    """A master key that lives only in memory, for tests. It is gone with the object."""

    def __init__(self) -> None:
        self._key = secrets.token_bytes(KEY_SIZE)

    def get_or_create_master_key(self) -> bytes:
        return self._key
