"""The leak check: nothing marked may be left anywhere in a masked Word file.

The brief's tests run on supply-01 masked for the brief's two values (``masked_docx``), with
values planted into its parts afterwards (``tests.helpers.plant``). Small made-up files cover the
rest: the digit and length rules (ruling R14), %-escaped link targets and instructions (R26),
text kept in attributes (R19), field names in instructions (R31), a person's bare surname (R52),
a value split across runs, XML comments, the bytes of parts that are not XML, part names, and
what a hit shows. No hit may show a value: every test that gets hits checks them.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import pytest

from tests.fixtures.docx import PACKAGE_RELS, MakeDocx
from tests.fixtures.leak import MASKED_ENTRIES, mask_file
from tests.helpers import plant
from themask.detect.pipeline import CombinedText, analyze
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.errors import ProtectedFileError, UnsupportedFileError
from themask.leakcheck import (
    BINARY_PART,
    FILE_NAME,
    PART_NAME,
    LeakHit,
    rescan_detection,
    scan_package,
    unverifiable,
)
from themask.model import KeyEntry, PlaceholderType
from themask.placeholders import find_placeholders
from themask.textnorm import normalize

if TYPE_CHECKING:
    from themask.detect.engine import Engine
    from themask.detect.lists import UserLists

AMOUNT = PlaceholderType.AMOUNT
COMPANY = PlaceholderType.COMPANY
CUSTOM = PlaceholderType.CUSTOM
EMAIL = PlaceholderType.EMAIL
IBAN = PlaceholderType.IBAN
ID = PlaceholderType.ID
PERCENT = PlaceholderType.PERCENT
PERSON = PlaceholderType.PERSON

E = MASKED_ENTRIES
HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


def para(text: str) -> str:
    """A paragraph of one run holding ``text``."""
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def hyperlink_rels(target: str) -> bytes:
    """A document.xml.rels relating rId1 to ``target`` as an external hyperlink."""
    row = f'<Relationship Id="rId1" Type="{HYPERLINK}" Target="{target}" TargetMode="External"/>'
    xml = f'<Relationships xmlns="{PACKAGE_RELS}">{row}</Relationships>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml).encode()


def assert_nothing_shown(hits: list[LeakHit], entries: list[KeyEntry]) -> None:
    """No hit shows a value or a variant that the leak check looks for, however it is written."""
    keys = {normalize(form) for entry in entries for form in (entry.value, *entry.variants)}
    for hit in hits:
        for key in (key for key in keys if len(key) >= 4):
            assert key not in normalize(hit.context), (hit, key)
            assert key not in normalize(hit.part), (hit, key)


# ---- the brief ----------------------------------------------------------------------------------


def test_clean_file_has_no_hits(masked_docx: Path) -> None:
    assert scan_package(masked_docx, E) == []


def test_the_file_before_masking_has_hits(corpus: Path) -> None:
    # The check that finds nothing in the masked copy finds both values all over the original.
    hits = scan_package(corpus / "supply-01.docx", E)
    assert {hit.placeholder for hit in hits} == {"[COMPANY_1]", "[IBAN_1]"}
    assert {"word/document.xml", "word/header1.xml"} <= {hit.part for hit in hits}
    assert_nothing_shown(hits, E)


def test_planted_in_header_rels_and_props(masked_docx: Path, tmp_path: Path) -> None:
    for part, payload in [
        ("word/header1.xml", b"<w:t>northwind</w:t>"),
        ("word/_rels/document.xml.rels", b'Target="mailto:x@northwind.example"'),
        ("docProps/core.xml", b"<dc:creator>NL91ABNA0417164300</dc:creator>"),
    ]:
        p = plant(masked_docx, part, payload, tmp_path / f"{part.replace('/', '_')}.docx")
        hits = scan_package(p, E)
        assert hits and hits[0].part == part
        assert "Northwind" not in hits[0].context and "NL91" not in hits[0].context
        assert_nothing_shown(hits, E)


def test_spacing_case_punct_variants(masked_docx: Path, tmp_path: Path) -> None:
    p = plant(masked_docx, "word/document.xml", b"<w:t>1.250.000</w:t>", tmp_path / "v.docx")
    assert scan_package(p, [KeyEntry("[AMOUNT_1]", AMOUNT, "1,250,000", [])])


def test_file_name_is_checked(tmp_path: Path, masked_docx: Path) -> None:
    p = tmp_path / "Northwind-contract.docx"
    p.write_bytes(masked_docx.read_bytes())
    hits = scan_package(p, E)
    assert any(h.part == "<file name>" for h in hits)
    assert [h.context for h in hits if h.part == FILE_NAME] == ["[COMPANY_1]-contract.docx"]


def test_rescan_finds_unmarked(
    engine: Engine, lists: UserLists, tmp_path: Path, masked_docx: Path
) -> None:
    p = plant(
        masked_docx, "word/document.xml", b"<w:t>Signed: Dr Jane Smith</w:t>", tmp_path / "u.docx"
    )
    assert any(g.type == PlaceholderType.PERSON for g in rescan_detection(p, engine, lists, E))


# ---- the digit and length rules (ruling R14) ----------------------------------------------------


def test_digits_count_only_where_no_digit_touches_them(make_docx: MakeDocx) -> None:
    entries = [KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 1,250", ["1,250"])]
    quiet = make_docx(para("Invoice 11250 of 2025 for 12500 units and 1,2500 kg."))
    assert scan_package(quiet, entries) == []
    loud = make_docx(para("Pay 1.250 by Friday.") + para("Reference AB1250CD."))
    hits = scan_package(loud, entries)
    assert [hit.context for hit in hits] == [
        "Pay [AMOUNT_1] by Friday.",
        "Reference AB[AMOUNT_1]CD.",
    ]
    assert_nothing_shown(hits, entries)


def test_short_values_are_not_checkable(make_docx: MakeDocx) -> None:
    entries = [
        KeyEntry("[PERCENT_1]", PERCENT, "5%", []),
        KeyEntry("[ID_1]", ID, "AB1", ["A B 1"]),
        KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 7.40", []),  # "eur740": six characters
        KeyEntry("[COMPANY_1]", COMPANY, "3M", ["3M Company"]),  # its variant can be checked
    ]
    assert unverifiable(entries) == ["[PERCENT_1]", "[ID_1]"]
    path = make_docx(para("Dated 5 May 2025: a 5% rebate on AB1 and on 3M goods."))
    assert scan_package(path, entries) == []


# ---- where values hide --------------------------------------------------------------------------


def test_a_value_split_across_runs_is_found(make_docx: MakeDocx) -> None:
    amount = KeyEntry("[AMOUNT_1]", AMOUNT, "1,250,000", [])
    body = (
        '<w:p><w:r><w:t xml:space="preserve">Paid by North</w:t></w:r>'
        "<w:r><w:rPr><w:b/></w:rPr><w:t>wind</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> today</w:t></w:r></w:p>'
        # Paragraphs are not one text: neither of these is a value.
        + para("Not North")
        + para("wind either, and the total is 3")
        + para("1250000 units")
    )
    hits = scan_package(make_docx(body), [*E, amount])
    assert [(hit.placeholder, hit.context) for hit in hits] == [
        ("[COMPANY_1]", "Paid by [COMPANY_1] today"),
        ("[AMOUNT_1]", "[AMOUNT_1] units"),
    ]


def test_percent_escaped_target_and_instruction(make_docx: MakeDocx) -> None:
    jane = KeyEntry("[EMAIL_1]", EMAIL, "jane@northwind.example", [])
    body = (
        '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>write to us</w:t></w:r></w:hyperlink></w:p>'
        '<w:p><w:fldSimple w:instr=" HYPERLINK &quot;mailto:jane%40northwind.example&quot; ">'
        "<w:r><w:t>or here</w:t></w:r></w:fldSimple></w:p>"
    )
    rels = hyperlink_rels("mailto:jane%40northwind.example")
    hits = scan_package(make_docx(body, raw={"word/_rels/document.xml.rels": rels}), [jane])
    assert [(hit.part, hit.context) for hit in hits] == [
        ("word/document.xml", 'instr="HYPERLINK "mailto:[EMAIL_1]""'),
        ("word/_rels/document.xml.rels", 'Target="mailto:[EMAIL_1]"'),
    ]


def test_text_kept_in_attributes(make_docx: MakeDocx) -> None:
    body = (
        '<w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="Picture 1"'
        ' descr="Logo of Northwind Trading"/></wp:inline></w:drawing></w:r></w:p>'
        '<w:p><w:hyperlink w:tooltip="Visit northwind"><w:r><w:t>our portal</w:t></w:r>'
        "</w:hyperlink></w:p>"
    )
    hits = scan_package(make_docx(body), E)
    assert [(hit.part, hit.placeholder, hit.context) for hit in hits] == [
        ("word/document.xml", "[COMPANY_1]", 'descr="Logo of [COMPANY_1]"'),
        ("word/document.xml", "[COMPANY_1]", 'tooltip="Visit [COMPANY_1]"'),
    ]


def test_field_names_and_format_keywords_are_no_hits(make_docx: MakeDocx) -> None:
    fields = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>2</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        '<w:p><w:fldSimple w:instr=" PAGE \\* MERGEFORMAT "><w:r><w:t>2</w:t></w:r>'
        "</w:fldSimple></w:p>"
    )
    words = [
        KeyEntry("[CUSTOM_1]", CUSTOM, "Page", []),
        KeyEntry("[CUSTOM_2]", CUSTOM, "Merge-Format", []),
    ]
    assert scan_package(make_docx(fields), words) == []


def test_values_in_field_instructions_are_hits(make_docx: MakeDocx) -> None:
    entries = [
        KeyEntry("[COMPANY_1]", COMPANY, "Page Industries Ltd", ["Page Industries"]),
        KeyEntry("[COMPANY_2]", COMPANY, "Acme Holdings Ltd", ["Acme Holdings", "Acme"]),
    ]
    body = (
        # A value of several words, one of them a field's name, and a path led by a backslash.
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> QUOTE Page Industries </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        r'<w:p><w:fldSimple w:instr=" INCLUDETEXT \\Acme-NAS\share\terms.docx "/></w:p>'
    )
    hits = scan_package(make_docx(body), entries)
    assert [hit.placeholder for hit in hits] == ["[COMPANY_1]", "[COMPANY_2]"]
    assert hits[0].context == "QUOTE [COMPANY_1]"
    assert hits[1].context.startswith(r'instr="INCLUDETEXT \\[COMPANY_2]-NAS\share')
    assert_nothing_shown(hits, entries)


def test_a_bare_surname_counts_where_it_stands_as_a_name(make_docx: MakeDocx) -> None:
    tom = KeyEntry("[PERSON_1]", PERSON, "Tom Price", ["T. Price"])
    jane = KeyEntry("[PERSON_2]", PERSON, "Jane Smith", ["J. Smith"])
    body = (
        para("The Buyer pays the Price in full.")  # a word of the contract, after "the"
        + para("Price shall attend.")
        + para("Price and Smith sign below.")  # two names, not one title-case phrase
    )
    path = make_docx(body, parts={"word/header1.xml": para("Attention: Price")})
    hits = scan_package(path, [tom, jane])
    assert [(hit.part, hit.placeholder, hit.context) for hit in hits] == [
        ("word/document.xml", "[PERSON_1]", "[PERSON_1] shall attend."),
        ("word/document.xml", "[PERSON_1]", "[PERSON_1] and [PERSON_2] sign below."),
        ("word/document.xml", "[PERSON_2]", "[PERSON_1] and [PERSON_2] sign below."),
        ("word/header1.xml", "[PERSON_1]", "Attention: [PERSON_1]"),
    ]


def test_xml_comments_and_processing_instructions_are_read(make_docx: MakeDocx) -> None:
    settings = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<!-- drafted for Northwind -->"
        b'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<?note made by northwind?><w:zoom w:percent="100"/></w:settings>'
    )
    # A comment inside a text does not part the text around it.
    body = '<w:p><w:r><w:t xml:space="preserve">Paid by North<!-- x -->wind today</w:t></w:r></w:p>'
    hits = scan_package(make_docx(body, raw={"word/settings.xml": settings}), E)
    assert [(hit.part, hit.context) for hit in hits] == [
        ("word/document.xml", "Paid by [COMPANY_1] today"),
        ("word/settings.xml", "drafted for [COMPANY_1]"),
        ("word/settings.xml", "note made by [COMPANY_1]"),
    ]


def test_the_bytes_of_parts_that_are_not_xml(make_docx: MakeDocx) -> None:
    short_name = "G\N{LATIN SMALL LETTER DOTLESS I}da Sanayi"
    gida = KeyEntry(
        "[COMPANY_1]",
        COMPANY,
        f"{short_name} A.\N{LATIN CAPITAL LETTER S WITH CEDILLA}.",
        [short_name],
    )
    iban = KeyEntry("[IBAN_1]", IBAN, "NL91 ABNA 0417 1643 00", [])
    amount = KeyEntry("[AMOUNT_1]", AMOUNT, "1,250,000", [])
    name = short_name.encode("utf-16-le")
    path = make_docx(
        para("Nothing to see."),
        raw={
            # UTF-16 at an even and at an odd offset; read as UTF-8 neither shows the name.
            "word/embeddings/oleObject1.bin": b"\xd0\xcf\x11\xe0" + name + b"\x00\x07",
            "word/embeddings/oleObject2.bin": b"\x01" + name,
            "word/media/notes.txt": b"Bank: NL91 ABNA 0417 1643 00, thanks",
            "customXml/item9.xml": b"<data>Paid into NL91 ABNA 0417 1643 00",  # not valid XML
            # Digits only are never looked for in bytes (ruling R14 b).
            "word/embeddings/oleObject3.bin": "1250000".encode("utf-16-le"),
        },
    )
    hits = scan_package(path, [gida, iban, amount])
    assert [(hit.part, hit.placeholder, hit.context) for hit in hits] == [
        ("word/embeddings/oleObject1.bin", "[COMPANY_1]", BINARY_PART),  # stray bytes round it
        ("word/embeddings/oleObject2.bin", "[COMPANY_1]", "[COMPANY_1]"),  # nothing else there
        ("word/media/notes.txt", "[IBAN_1]", "Bank: [IBAN_1], thanks"),
        ("customXml/item9.xml", "[IBAN_1]", "<data>Paid into [IBAN_1]"),
    ]


def test_part_names_are_checked(make_docx: MakeDocx) -> None:
    path = make_docx(
        para("Clean."), raw={"customXml/northwind.xml": b"<data><owner>Northwind</owner></data>"}
    )
    hits = scan_package(path, E)
    assert [(hit.part, hit.context) for hit in hits] == [
        (PART_NAME, "customXml/[COMPANY_1].xml"),
        ("customXml/[COMPANY_1].xml", "[COMPANY_1]"),  # the part's name is hidden as well
    ]


# ---- what a hit shows ---------------------------------------------------------------------------


def test_no_hit_shows_a_value(masked_docx: Path, tmp_path: Path) -> None:
    text = (
        "Northwind Trading B.V. (Northwind) pays into NL91 ABNA 0417 1643 00, also written "
        "NL91ABNA0417164300, for NORTHWIND TRADING and nobody else."
    )
    path = plant(masked_docx, "word/document.xml", para(text).encode(), tmp_path / "many.docx")
    hits = scan_package(path, E)
    assert [hit.placeholder for hit in hits] == [
        "[COMPANY_1]",
        "[COMPANY_1]",
        "[IBAN_1]",
        "[IBAN_1]",
        "[COMPANY_1]",
    ]
    assert all(hit.part == "word/document.xml" for hit in hits)
    assert_nothing_shown(hits, E)


def test_accents_written_apart_are_found_and_hidden(make_docx: MakeDocx) -> None:
    together = "Caf\N{LATIN SMALL LETTER E WITH ACUTE} No\N{LATIN SMALL LETTER E WITH DIAERESIS}l"
    cafe = KeyEntry("[COMPANY_1]", COMPANY, f"{together} SARL", [together])
    apart = "Cafe\N{COMBINING ACUTE ACCENT} Noe\N{COMBINING DIAERESIS}l"
    ligature = "\N{LATIN SMALL LIGATURE FI}nance"
    hits = scan_package(make_docx(para(f"Signed for {apart} by its {ligature} team.")), [cafe])
    assert [hit.context for hit in hits] == [f"Signed for [COMPANY_1] by its {ligature} team."]


def test_a_long_text_is_cut_round_the_hit(make_docx: MakeDocx) -> None:
    cut = "\N{HORIZONTAL ELLIPSIS}"
    text = "The parties agree that " + "x" * 60 + " Northwind " + "y" * 60 + " shall apply."
    hits = scan_package(make_docx(para(text)), E)
    assert [hit.context for hit in hits] == [f"{cut}{'x' * 19} [COMPANY_1] {'y' * 19}{cut}"]
    # A word the cut falls in is shown whole when its end is near.
    text = "Payment is due to Northwind within thirty calendar days of invoice."
    hits = scan_package(make_docx(para(text)), E)
    assert [hit.context for hit in hits] == [
        f"Payment is due to [COMPANY_1] within thirty calendar{cut}"
    ]


def test_what_is_not_a_word_file_is_refused(fixtures: Path) -> None:
    with pytest.raises(UnsupportedFileError):
        scan_package(fixtures / "not-a-docx.doc", E)
    with pytest.raises(UnsupportedFileError):
        scan_package(fixtures / "corrupt.docx", E)
    with pytest.raises(ProtectedFileError):
        scan_package(fixtures / "encrypted.docx", E)


# ---- what detection finds again ----------------------------------------------------------------


def test_rescan_leaves_out_the_banner_and_the_marked_values(
    engine: Engine, lists: UserLists, tmp_path: Path, masked_docx: Path
) -> None:
    payload = para("Signed: Dr Jane Smith") + para("Northwind Trading B.V.")
    path = plant(masked_docx, "word/document.xml", payload.encode(), tmp_path / "again.docx")
    keys = {normalize(form) for entry in E for form in (entry.value, *entry.variants)}
    text = extract_text(DocxPackage.open(path)).text
    found = analyze(CombinedText.join([(path.name, text)]), engine, lists).groups
    assert any(normalize(group.canonical) in keys for group in found)  # found again, but marked

    unmarked = rescan_detection(path, engine, lists, E)
    assert any(g.type is PERSON and "Jane Smith" in g.canonical for g in unmarked)
    assert not any({normalize(g.canonical), *map(normalize, g.variants)} & keys for g in unmarked)
    assert not any(find_placeholders(g.canonical) for g in unmarked)


# ---- speed --------------------------------------------------------------------------------------


def test_thirty_pages_are_scanned_in_under_two_seconds(corpus: Path, tmp_path: Path) -> None:
    truth = json.loads((corpus / "supply-10.truth.json").read_text(encoding="utf-8"))
    numbers: dict[str, int] = {}
    entries = []
    for item in truth:
        numbers[item["type"]] = numbers.get(item["type"], 0) + 1
        placeholder = f"[{item['type']}_{numbers[item['type']]}]"
        entries.append(
            KeyEntry(placeholder, PlaceholderType(item["type"]), item["value"], item["variants"])
        )
    masked = mask_file(corpus / "supply-10.docx", entries, tmp_path / "MASKED-TENS.docx")
    # Values the file never held bring the key to sixty entries, digits only among them.
    entries += [
        KeyEntry(f"[CUSTOM_{n}]", CUSTOM, f"Zephyrine Holdings {n} Ltd", [f"Zephyrine {n}"])
        for n in range(1, 9)
    ]
    entries += [KeyEntry(f"[ID_{n}]", ID, f"{7319946 + 7_777 * n}", []) for n in range(4, 13)]
    assert len(entries) >= 60

    start = time.perf_counter()
    hits = scan_package(masked, entries)
    elapsed = time.perf_counter() - start
    assert hits == []
    assert elapsed < 2.0, elapsed
