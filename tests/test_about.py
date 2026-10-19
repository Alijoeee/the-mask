import pytest

from themask.about import APP_NAME, VERSION
from themask.errors import (
    CaseCorruptError,
    MaskError,
    ProtectedFileError,
    ScannedPdfError,
    UnsupportedFileError,
)


def test_a_blocked_export_is_no_error_class() -> None:
    # Ruling R109: ExportResult.blocked is the contract; a reserved exception nothing raised
    # would invite the next implementer to raise it where the dialog does not expect it.
    from themask import errors

    assert not hasattr(errors, "LeakBlockedError")


def test_app_identity() -> None:
    assert APP_NAME == "The MASK"
    assert VERSION == "0.1.0"


@pytest.mark.parametrize(
    "error_class",
    [UnsupportedFileError, ProtectedFileError, ScannedPdfError, CaseCorruptError],
)
def test_errors_carry_a_user_message(error_class: type[MaskError]) -> None:
    error = error_class("Please provide an unprotected copy.")
    assert isinstance(error, MaskError)
    assert error.user_message == "Please provide an unprotected copy."
    assert str(error) == "Please provide an unprotected copy."
