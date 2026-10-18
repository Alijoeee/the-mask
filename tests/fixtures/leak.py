"""A masked Word file for the tests of the leak check.

``MASKED_ENTRIES`` are the brief's two key entries, a company and its IBAN; the corpus's
supply-01.docx holds both. ``masked_docx`` is supply-01 masked for them the way an export masks a
file: tracked changes accepted, cleaned, every occurrence of each value and variant replaced by
its placeholder, the banner on top, saved under a neutral name. ``mask_file`` masks any Word file
for any entries the same way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from themask.docx.cleaner import clean
from themask.docx.masker import apply_mask, insert_banner
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.docx.revisions import accept_all
from themask.model import KeyEntry, MaskPlan, PlaceholderType, Replacement
from themask.textnorm import flexible_pattern, variants_of

MASKED_ENTRIES = [
    KeyEntry(
        "[COMPANY_1]",
        PlaceholderType.COMPANY,
        "Northwind Trading B.V.",
        ["Northwind Trading", "Northwind"],
    ),
    KeyEntry("[IBAN_1]", PlaceholderType.IBAN, "NL91 ABNA 0417 1643 00", []),
]


def mask_file(src: Path, entries: list[KeyEntry], out: Path) -> Path:
    """Masks the Word file ``src`` for ``entries`` and saves the result at ``out``; returns ``out``.

    Every occurrence in the text of each entry's value, its variants and the further spellings
    ``variants_of`` gives is replaced by the entry's placeholder, however it is spaced and cased.
    Of two occurrences that overlap the longer is replaced, and none that runs over a paragraph's
    end.
    """
    pkg = DocxPackage.open(src)
    accept_all(pkg)
    clean(pkg)
    doc_text = extract_text(pkg)
    found = [
        (match.start(), match.end(), entry.placeholder)
        for entry in entries
        for form in {entry.value, *entry.variants, *variants_of(entry.value, entry.type)}
        for match in flexible_pattern(form).finditer(doc_text.text)
        if "\n" not in match.group()
    ]
    free = bytearray(b"\x01" * len(doc_text.text))
    chosen = []
    for start, end, placeholder in sorted(found, key=lambda f: (f[0] - f[1], f[0])):
        if all(free[start:end]):
            free[start:end] = bytes(end - start)
            chosen.append(Replacement(start, end, placeholder))
    apply_mask(pkg, doc_text, MaskPlan(chosen))
    insert_banner(pkg)
    pkg.save(out)
    return out


@pytest.fixture(scope="session")
def masked_docx(corpus: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """supply-01.docx masked for ``MASKED_ENTRIES``, saved as MASKED-TEST.docx.

    One file for the whole session: a test copies it (``tests.helpers.plant``), never changes it.
    """
    out = tmp_path_factory.mktemp("masked") / "MASKED-TEST.docx"
    return mask_file(corpus / "supply-01.docx", MASKED_ENTRIES, out)
