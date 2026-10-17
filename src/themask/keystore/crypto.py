"""AES-256-GCM, the lock on every stored case.

A blob is a random 12-byte nonce followed by the ciphertext and its 16-byte authentication tag,
and nothing else. The tag is what tells an intact blob from one that was changed or locked with
another key.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from themask.errors import CaseCorruptError

KEY_SIZE = 32
NONCE_SIZE = 12

# What the owner is told whenever a case file cannot be opened, whatever is wrong with it.
CORRUPT_MESSAGE = (
    "This case file is damaged or was written by another computer and cannot be opened."
)


def _cipher(key: bytes) -> AESGCM:
    # AES-GCM itself also takes 16 and 24 byte keys; the cases must never be locked with less.
    if len(key) != KEY_SIZE:
        raise ValueError(f"The key must be {KEY_SIZE} bytes (AES-256), not {len(key)}.")
    return AESGCM(key)


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Lock ``plaintext`` with a 32-byte key: a new random nonce, then the ciphertext and tag."""
    cipher = _cipher(key)
    nonce = os.urandom(NONCE_SIZE)
    return nonce + cipher.encrypt(nonce, plaintext, None)


def decrypt(key: bytes, blob: bytes) -> bytes:
    """Open a blob made by ``encrypt`` with the same key.

    Raises CaseCorruptError if there is nothing after the nonce, or if the blob fails its
    integrity check, which means it was changed or was locked with another key.
    """
    cipher = _cipher(key)
    if len(blob) <= NONCE_SIZE:
        raise CaseCorruptError(CORRUPT_MESSAGE)
    try:
        return cipher.decrypt(blob[:NONCE_SIZE], blob[NONCE_SIZE:], None)
    except InvalidTag as error:  # also raised for data shorter than a tag
        raise CaseCorruptError(CORRUPT_MESSAGE) from error
