"""The key: each case's placeholders and their real values, locked on the owner's computer.

Cases are encrypted with AES-256-GCM. The master key is kept in the macOS Keychain.
"""

from themask.keystore.cases import CaseStore, CaseSummary
from themask.keystore.crypto import decrypt, encrypt
from themask.keystore.secrets import KeychainKeyStore, KeyStore, MemoryKeyStore

__all__ = [
    "CaseStore",
    "CaseSummary",
    "KeyStore",
    "KeychainKeyStore",
    "MemoryKeyStore",
    "decrypt",
    "encrypt",
]
