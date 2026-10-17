import pytest

from themask.about import APP_NAME, VERSION
from themask.errors import (
    CaseCorruptError,
    LeakBlockedError,
    MaskError,
    ProtectedFileError,
    ScannedPdfError,
    UnsupportedFileError,
)


def test_app_identity() -> None:
    assert APP_NAME == "The MASK"
    assert VERSION == "0.1.0"


def test_leak_blocked_is_a_mask_error() -> None:
    assert issubclass(LeakBlockedError, MaskError)


@pytest.mark.parametrize(
    "error_class",
    [UnsupportedFileError, ProtectedFileError, ScannedPdfError, CaseCorruptError, LeakBlockedError],
)
def test_errors_carry_a_user_message(error_class: type[MaskError]) -> None:
    error = error_class("Please provide an unprotected copy.")
    assert isinstance(error, MaskError)
    assert error.user_message == "Please provide an unprotected copy."
    assert str(error) == "Please provide an unprotected copy."
