"""Core data model for The MASK: placeholder types, findings, groups, plans, keys and cases."""

from __future__ import annotations

from enum import StrEnum


class PlaceholderType(StrEnum):
    """The twelve placeholder types, spelled exactly as they appear inside ``[TYPE_N]``."""

    PERSON = "PERSON"
    COMPANY = "COMPANY"
    AMOUNT = "AMOUNT"
    PERCENT = "PERCENT"
    QUANTITY = "QUANTITY"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"
    IBAN = "IBAN"
    ID = "ID"
    URL = "URL"
    CUSTOM = "CUSTOM"
