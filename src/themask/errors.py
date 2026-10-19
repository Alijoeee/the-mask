"""Errors that The MASK reports to the user instead of crashing.

Each one carries ``user_message``: plain English that says what is wrong and what to do about it.
The interface shows that message and never a stack trace.
"""


class MaskError(Exception):
    """Base class for every error whose message is meant for the user."""

    user_message: str

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class UnsupportedFileError(MaskError):
    """The file is not one The MASK can read, for example an old .doc or a damaged .docx."""


class ProtectedFileError(MaskError):
    """The file is password-protected or encrypted."""


class ScannedPdfError(MaskError):
    """The PDF is a scan or photo without selectable text."""


class CaseCorruptError(MaskError):
    """A stored case failed its integrity check, so it cannot be trusted or opened."""


class KeyStoreError(MaskError):
    """The master key could not be read from or kept in the macOS Keychain, or it is damaged."""
