"""A round trip: a file exported and its masked text restored gives every value back as its own.

Ruling R100: values that differ only in a decimal point, a currency symbol or a dot are
different values, each with a placeholder of its own, so a restore never writes one value in
place of another (the reviewer's reproduction, with the real engine).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from tests.helpers import reviewed
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.export import ExportOptions, export_case
from themask.model import Case
from themask.restore.text import restore_text

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.docx import MakeDocx
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists

A4_TEXT = (
    "The unit fee is EUR 1.25 per item and the annual cap is EUR 125 per customer. "
    "The deposit is $100 and the refund is \N{EURO SIGN}100. "
    "Questions to a.b@example.com or to ab@example.com."
)


def para(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def test_values_that_differ_in_a_point_a_symbol_or_a_dot_restore_to_themselves(
    make_docx: MakeDocx, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    srcs, review = reviewed([make_docx(para(A4_TEXT))], engine, lists)
    saved: list[Case] = []
    res = export_case(srcs, review, ExportOptions(tmp_path / "out"), engine, lists, saved.append)
    assert not res.blocked and res.case is not None
    masked = extract_text(DocxPackage.open(res.outputs[0])).text.splitlines()[-1]
    assert masked == (
        "The unit fee is [AMOUNT_1] per item and the annual cap is [AMOUNT_2] per customer. "
        "The deposit is [AMOUNT_3] and the refund is [AMOUNT_4]. "
        "Questions to [EMAIL_1] or to [EMAIL_2]."
    )
    assert [(e.placeholder, e.value, e.variants) for e in res.case.entries] == [
        ("[AMOUNT_1]", "EUR 1.25", ["EUR 1.25"]),
        ("[AMOUNT_2]", "EUR 125", ["EUR 125"]),
        ("[AMOUNT_3]", "$100", ["$100"]),
        ("[AMOUNT_4]", "\N{EURO SIGN}100", ["\N{EURO SIGN}100"]),
        ("[EMAIL_1]", "a.b@example.com", ["a.b@example.com"]),
        ("[EMAIL_2]", "ab@example.com", ["ab@example.com"]),
    ]
    restored, report = restore_text(masked, res.case, True)
    assert restored == A4_TEXT
    assert report.summary() == "6 placeholders restored, 0 need your check."
