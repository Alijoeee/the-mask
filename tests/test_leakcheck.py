"""The leak check: nothing marked may be left anywhere in a masked Word file.

The brief's tests run on supply-01 masked for the brief's two values (``masked_docx``), with
values planted into its parts afterwards (``tests.helpers.plant``). Small made-up files cover the
rest: the digit and length rules (ruling R14), %-escaped link targets and instructions (R26),
text kept in attributes (R19), field names in instructions (R31), a person's bare surname (R52),
names by their whole words (R63), the file format's own vocabulary (R64), a value split across
runs, XML comments, the bytes of parts that are not XML, part names, and what a hit shows. Five
corpus files go through the whole pipeline. No hit may show a value: every test that gets hits
checks them.
"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

import pytest

from tests.fixtures.docx import PACKAGE_RELS, MakeDocx
from tests.fixtures.leak import MASKED_ENTRIES, mask_file
from tests.helpers import plant
from themask import leakcheck
from themask.detect.grouping import PersonName
from themask.detect.pipeline import CombinedText, analyze
from themask.detect.sweep import is_bare_name
from themask.docx.cleaner import clean
from themask.docx.masker import apply_mask, insert_banner
from themask.docx.package import DocxPackage
from themask.docx.reader import extract_text
from themask.docx.revisions import accept_all
from themask.errors import ProtectedFileError, UnsupportedFileError
from themask.leakcheck import (
    BINARY_PART,
    FILE_NAME,
    PART_NAME,
    LeakHit,
    hits_by_placeholder,
    rescan_detection,
    scan_package,
    unverifiable,
)
from themask.model import Group, KeyEntry, MaskPlan, PlaceholderType, Replacement
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
PHONE = PlaceholderType.PHONE
QUANTITY = PlaceholderType.QUANTITY
# The types whose values are names, compared by their words (ruling R63).
NAME_TYPES = {
    PERSON,
    COMPANY,
    PlaceholderType.ADDRESS,
    CUSTOM,
    EMAIL,
    PlaceholderType.URL,
}

E = MASKED_ENTRIES
HYPERLINK = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def para(text: str) -> str:
    """A paragraph of one run holding ``text``."""
    return f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def hyperlink_rels(target: str) -> bytes:
    """A document.xml.rels relating rId1 to ``target`` as an external hyperlink."""
    row = f'<Relationship Id="rId1" Type="{HYPERLINK}" Target="{target}" TargetMode="External"/>'
    xml = f'<Relationships xmlns="{PACKAGE_RELS}">{row}</Relationships>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml).encode()


def assert_nothing_shown(hits: list[LeakHit], entries: list[KeyEntry]) -> None:
    """No hit holds anything that normalises to a value, a variant or a person's surname that
    the leak check looks for, glued to other letters or not (ruling R69)."""
    forms = [form for entry in entries for form in (entry.value, *entry.variants)]
    forms += [
        surname
        for entry in entries
        if entry.type is PERSON
        for surname in PersonName.of(entry.value).surnames()
    ]
    keys = {normalize(form) for form in forms if len(normalize(form)) >= 4}
    for hit in hits:
        for key in keys:
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


# ---- names by their words (ruling R63) ----------------------------------------------------------


def test_names_count_only_as_whole_words(make_docx: MakeDocx) -> None:
    assert leakcheck.NAME_TYPES == NAME_TYPES  # the others are compared by letters and digits
    sarah = KeyEntry("[PERSON_1]", PERSON, "Sarah Hall", ["S. Hall"])
    bob = KeyEntry("[PERSON_2]", PERSON, "Bob Lee", ["B. Lee"])
    quiet = para("The Supplier shall deliver the Goods.") + para(
        "Each party shall use reasonable endeavours."
    )
    assert scan_package(make_docx(quiet), [sarah, bob]) == []
    hits = scan_package(make_docx(quiet + para("Signed by S. Hall.")), [sarah, bob])
    assert [(hit.placeholder, hit.context) for hit in hits] == [
        ("[PERSON_1]", "Signed by [PERSON_1].")
    ]


def test_a_tab_parts_two_words_and_a_drawing_joins_none(make_docx: MakeDocx) -> None:
    northwind = KeyEntry("[COMPANY_1]", COMPANY, "Northwind Trading B.V.", [])
    body = (
        "<w:p><w:r><w:t>Northwind</w:t><w:tab/><w:t>Trading B.V.</w:t></w:r></w:p>"
        # A drawing's position is a text of its own, not part of what the paragraph shows.
        "<w:p><w:r><w:t>Paid by Northwind Trading</w:t></w:r><w:r><w:drawing><wp:anchor>"
        '<wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>'
        '</wp:anchor></w:drawing></w:r><w:r><w:t xml:space="preserve"> B.V. today</w:t></w:r></w:p>'
    )
    hits = scan_package(make_docx(body), [northwind])
    # The full stop that ends "B.V." is no letter of the value, so it stays.
    assert [hit.context for hit in hits] == ["[COMPANY_1].", "Paid by [COMPANY_1]. today"]


# ---- the file format's own vocabulary (ruling R64) ----------------------------------------------


def xml(text: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + text).encode()


def test_sizes_colours_and_ids_are_no_amounts(make_docx: MakeDocx) -> None:
    fee = KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 35.000", ["35.000"])
    cap = KeyEntry("[AMOUNT_2]", AMOUNT, "EUR 800.000,00", ["800.000,00"])  # 80000000
    theme = xml(
        f'<a:theme xmlns:a="{A_NS}" name="Office Theme"><a:themeElements>'
        '<a:fmtScheme name="Office"><a:fillStyleLst><a:gradFill><a:gsLst><a:gs pos="35000">'
        '<a:schemeClr val="phClr">'
        '<a:tint val="35000"/><a:satMod val="350000"/></a:schemeClr></a:gs></a:gsLst></a:gradFill>'
        "</a:fillStyleLst></a:fmtScheme></a:themeElements></a:theme>"
    )
    fonts = xml(
        f'<w:fonts xmlns:w="{W_NS}"><w:font w:name="Calibri">'
        '<w:sig w:usb0="E0002AFF" w:csb0="80000000"/></w:font></w:fonts>'
    )
    raw = {"word/theme/theme1.xml": theme, "word/fontTable.xml": fonts}
    body = '<w:p><w:pPr><w:ind w:left="35000"/></w:pPr><w:r><w:t>Clean.</w:t></w:r></w:p>'
    assert scan_package(make_docx(body, raw=raw), [fee, cap]) == []
    hits = scan_package(make_docx(body + para("The fee is 35.000 a year."), raw=raw), [fee, cap])
    assert [(hit.part, hit.context) for hit in hits] == [
        ("word/document.xml", "The fee is [AMOUNT_1] a year.")
    ]


def test_a_party_named_like_the_file_format_counts_in_content_only(
    make_docx: MakeDocx, masked_docx: Path
) -> None:
    microsoft = KeyEntry(
        "[COMPANY_1]",
        COMPANY,
        "Microsoft Ireland Operations Limited",
        ["Microsoft Ireland Operations", "Microsoft"],
    )
    styles_type = "http://schemas.microsoft.com/office/2007/relationships/stylesWithEffects"
    raw = {
        "word/_rels/document.xml.rels": xml(
            f'<Relationships xmlns="{PACKAGE_RELS}"><Relationship Id="rId1" Type="{styles_type}"'
            ' Target="stylesWithEffects.xml"/></Relationships>'
        ),
        "word/settings.xml": xml(
            f'<w:settings xmlns:w="{W_NS}"><w:compat>'
            '<w:compatSetting w:name="mode" w:uri="http://schemas.microsoft.com/office/word"/>'
            '<w:compatSetting w:name="vml" w:uri="urn:schemas-microsoft-com:office:word"/>'
            '<w:compatSetting w:name="mathml" w:uri="http://www.w3.org/Microsoft/MathML"/>'
            "</w:compat></w:settings>"
        ),
        "word/fontTable.xml": xml(
            f'<w:fonts xmlns:w="{W_NS}"><w:font w:name="Microsoft YaHei"/></w:fonts>'
        ),
        "word/theme/theme1.xml": xml(
            f'<a:theme xmlns:a="{A_NS}" name="Office Theme"><a:themeElements>'
            '<a:fontScheme name="Office"><a:majorFont><a:latin typeface="Microsoft Sans Serif"/>'
            '<a:ea typeface="Microsoft YaHei"/><a:cs typeface="Microsoft Uighur"/>'
            '<a:font script="Tibt" typeface="Microsoft Himalaya"/></a:majorFont></a:fontScheme>'
            "</a:themeElements></a:theme>"
        ),
        "docProps/app.xml": xml(
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            'extended-properties"><Template>Microsoft Normal.dotm</Template>'
            "<Application>Microsoft Office Word</Application><AppVersion>16.0000</AppVersion>"
            "</Properties>"
        ),
    }
    body = (
        '<w:p><w:r><w:rPr><w:rFonts w:ascii="Microsoft Sans Serif" w:cs="Microsoft Sans Serif"/>'
        "</w:rPr><w:t>Plain text.</w:t></w:r></w:p>"
    )
    assert scan_package(make_docx(body, raw=raw), [microsoft]) == []
    # Word's own copy of the same vocabulary, in the masked corpus file, is no hit either.
    with zipfile.ZipFile(masked_docx) as archive:
        assert b"Microsoft" in archive.read("word/theme/theme1.xml")
        assert b"Microsoft" in archive.read("docProps/app.xml")
    assert scan_package(masked_docx, [microsoft]) == []

    tooltip = (
        '<w:p><w:hyperlink w:tooltip="Microsoft portal"><w:r><w:t>portal</w:t></w:r>'
        "</w:hyperlink></w:p>"
    )
    hits = scan_package(make_docx(body + tooltip, raw=raw), [microsoft])
    assert [(hit.part, hit.context) for hit in hits] == [
        ("word/document.xml", 'tooltip="[COMPANY_1] portal"')
    ]


def test_the_names_of_standard_parts_are_no_names(masked_docx: Path, tmp_path: Path) -> None:
    core = KeyEntry("[COMPANY_1]", COMPANY, "Core Systems Ltd", ["Core Systems", "Core"])
    with zipfile.ZipFile(masked_docx) as archive:  # "core" is in names, a content type, a target
        assert "docProps/core.xml" in archive.namelist()
        assert b"core-properties" in archive.read("[Content_Types].xml")
        assert b"docProps/core.xml" in archive.read("_rels/.rels")
    assert scan_package(masked_docx, [core]) == []
    planted = para("Core shall deliver.").encode()
    hits = scan_package(
        plant(masked_docx, "word/document.xml", planted, tmp_path / "c.docx"), [core]
    )
    assert [(hit.part, hit.context) for hit in hits] == [
        ("word/document.xml", "[COMPANY_1] shall deliver.")
    ]
    # Any other part's name, and the file's own name, are names like any text.
    logo = plant(masked_docx, "word/media/core-logo.png", b"\x89PNG", tmp_path / "Core-deal.docx")
    hits = scan_package(logo, [core])
    assert [(hit.part, hit.context) for hit in hits] == [
        (FILE_NAME, "[COMPANY_1]-deal.docx"),
        (PART_NAME, "word/media/[COMPANY_1]-logo.png"),
    ]


def test_counts_of_the_extended_properties_are_no_amounts(make_docx: MakeDocx) -> None:
    fee = KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 1,250", ["1,250"])
    app = xml(
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        'extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/'
        'docPropsVTypes"><TotalTime>1250</TotalTime><Pages>1250</Pages><Words>1250</Words>'
        "<Characters>1250</Characters><Lines>1250</Lines><DocSecurity>1250</DocSecurity>"
        '<HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>Title'
        "</vt:lpstr></vt:variant><vt:variant><vt:i4>1250</vt:i4></vt:variant></vt:vector>"
        "</HeadingPairs></Properties>"
    )
    raw = {"docProps/app.xml": app}
    assert scan_package(make_docx(para("Clean."), raw=raw), [fee]) == []
    # A bare number that the document shows is a value all the same.
    hits = scan_package(make_docx(para("1250"), raw=raw), [fee])
    assert [(hit.part, hit.context) for hit in hits] == [("word/document.xml", "[AMOUNT_1]")]


def test_a_drawings_geometry_holds_no_amounts(make_docx: MakeDocx) -> None:
    entries = [
        KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 1,828,800", ["1,828,800"]),
        KeyEntry("[AMOUNT_2]", AMOUNT, "EUR 21,600", ["21,600"]),
    ]
    body = (
        '<w:p><w:r><w:drawing><wp:anchor distL="114300" relativeHeight="251659264">'
        '<wp:positionH relativeFrom="column"><wp:posOffset>1828800</wp:posOffset></wp:positionH>'
        '<wp:extent cx="1828800" cy="21600"/><a:graphic><a:graphicData><a:prstGeom prst="rect">'
        '<a:avLst><a:gd name="adj" fmla="val 21600"/></a:avLst></a:prstGeom></a:graphicData>'
        "</a:graphic></wp:anchor></w:drawing></w:r></w:p>"
        '<w:p><w:r><w:pict><v:shapetype coordsize="21600,21600" path="m,l,21600r21600,l21600,xe"/>'
        '<v:shape style="position:absolute;width:1828800pt;height:21600pt"/></w:pict></w:r></w:p>'
    )
    assert scan_package(make_docx(body), entries) == []
    hits = scan_package(make_docx(body + para("Paid 1,828,800 for 21,600 units.")), entries)
    assert [(hit.placeholder, hit.context) for hit in hits] == [
        ("[AMOUNT_1]", "Paid [AMOUNT_1] for [AMOUNT_2] units."),
        ("[AMOUNT_2]", "Paid [AMOUNT_1] for [AMOUNT_2] units."),
    ]


def test_theme_and_scheme_names_are_no_names(make_docx: MakeDocx, masked_docx: Path) -> None:
    office = KeyEntry("[COMPANY_1]", COMPANY, "Office Supplies Ltd", ["Office Supplies", "Office"])
    theme = xml(
        f'<a:theme xmlns:a="{A_NS}" name="Office Theme"><a:themeElements>'
        '<a:clrScheme name="Office"/><a:fontScheme name="Office"/><a:fmtScheme name="Office"/>'
        "</a:themeElements></a:theme>"
    )
    raw = {"word/theme/theme1.xml": theme}
    assert scan_package(make_docx(para("Clean."), raw=raw), [office]) == []
    tooltip = (
        '<w:p><w:hyperlink w:tooltip="Office portal"><w:r><w:t>portal</w:t></w:r>'
        "</w:hyperlink></w:p>"
    )
    hits = scan_package(make_docx(para("Clean.") + tooltip, raw=raw), [office])
    assert [(hit.part, hit.context) for hit in hits] == [
        ("word/document.xml", 'tooltip="[COMPANY_1] portal"')
    ]
    # Word's own theme in the masked corpus file is named "Office" too.
    with zipfile.ZipFile(masked_docx) as archive:
        assert b'name="Office' in archive.read("word/theme/theme1.xml")
    assert all(hit.part != "word/theme/theme1.xml" for hit in scan_package(masked_docx, [office]))


# ---- numbers beside numbers (ruling R65) -------------------------------------------------------


def tab_row(*cells: str) -> str:
    """A paragraph of texts parted by tabs, as a schedule writes them."""
    texts = (f'<w:t xml:space="preserve">{escape(cell)}</w:t>' for cell in cells)
    return f"<w:p><w:r>{'<w:tab/>'.join(texts)}</w:r></w:p>"


def test_a_tab_or_a_line_break_parts_two_numbers(make_docx: MakeDocx) -> None:
    fee = KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 125,000", ["125,000"])
    units = KeyEntry("[QUANTITY_1]", QUANTITY, "1,250 units", ["1,250"])
    body = (
        tab_row("Instalment 1", "125,000", "on signing")
        + tab_row("Instalment 2", "125,000", "on delivery")
        + tab_row("Instalment 3", "125,000", "on acceptance")
        + tab_row("2025", "1,250")  # a year column
        + "<w:p><w:r><w:t>2026</w:t><w:br/><w:t>1,250</w:t></w:r></w:p>"
        + tab_row("1.", "125,000 payable on signing")
    )
    hits = scan_package(make_docx(body), [fee, units])
    assert [hit.context for hit in hits] == [
        "Instalment 1 [AMOUNT_1] on signing",
        "Instalment 2 [AMOUNT_1] on delivery",
        "Instalment 3 [AMOUNT_1] on acceptance",
        "2025 [QUANTITY_1]",
        "2026 [QUANTITY_1]",
        "1. [AMOUNT_1] payable on signing",
    ]


def test_what_parts_a_number_from_a_number(make_docx: MakeDocx) -> None:
    tel = KeyEntry("[PHONE_1]", PHONE, "+31 20 123 4567", [])
    fee = KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 125,000", ["125,000"])
    deposit = KeyEntry("[AMOUNT_2]", AMOUNT, "EUR 1,250", [])
    shown = (
        para("Tel. 2: +31 20 123 4567")
        + para("Fee 125,000.00 per year.")  # cents are no other number
        + para("Fee 125,000\N{SUPERSCRIPT ONE} payable.")  # nor is a footnote mark
        + para("A fee of EUR 1,250.50 applies.")
    )
    hits = scan_package(make_docx(shown), [tel, fee, deposit])
    assert [hit.context for hit in hits] == [
        "Tel. 2: +[PHONE_1]",
        "Fee [AMOUNT_1] per year.",
        "Fee [AMOUNT_1]\N{SUPERSCRIPT ONE} payable.",
        "A fee of [AMOUNT_2].50 applies.",
    ]
    # A number with more digits round it is another number.
    other = para("A deposit of EUR 12,500 applies.") + para("A cap of EUR 1,250,000 applies.")
    assert scan_package(make_docx(other), [deposit]) == []


def test_a_plain_space_parts_numbers_unless_a_thousands_group_follows(make_docx: MakeDocx) -> None:
    units = KeyEntry("[QUANTITY_1]", QUANTITY, "1 250 units", ["1 250"])
    register = KeyEntry("[ID_1]", ID, "12345678", [])
    # Beyond a plain space, three digits continue the number (ruling R70).
    inside = para("A cap of 1 250 000 applies.") + para("A cap of 1250 000 applies.")
    assert scan_package(make_docx(inside), [units, register]) == []
    # Any other run of digits beyond it is another number.
    apart = para("In 2025 1,250 units shall be delivered.") + para("Article 4 12345678 applies.")
    hits = scan_package(make_docx(apart), [units, register])
    assert [hit.context for hit in hits] == [
        "In 2025 [QUANTITY_1] shall be delivered.",  # the value, "1,250 units", whole
        "Article 4 [ID_1] applies.",
    ]


def test_a_thin_space_and_a_curly_apostrophe_group_thousands(make_docx: MakeDocx) -> None:
    thin, curly = "\N{THIN SPACE}", "\N{RIGHT SINGLE QUOTATION MARK}"
    units = KeyEntry("[QUANTITY_1]", QUANTITY, f"1{thin}250 units", [f"1{thin}250"])
    # Like a no-break space, they join the groups of one number (ruling R72).
    inside = para(f"A cap of 1{thin}250{thin}000 applies.") + para(
        f"A cap of 1{curly}250{curly}000 applies."
    )
    assert scan_package(make_docx(inside), [units]) == []
    hits = scan_package(make_docx(para(f"In 2025 1{thin}250 units shall be delivered.")), [units])
    assert [hit.context for hit in hits] == ["In 2025 [QUANTITY_1] shall be delivered."]


def test_a_decimal_part_stays_apart(make_docx: MakeDocx) -> None:
    big = KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 125,000", ["125,000"])
    small = KeyEntry("[AMOUNT_2]", AMOUNT, "EUR 1,250", ["1,250"])
    million = KeyEntry("[AMOUNT_3]", AMOUNT, "EUR 1,250,000", ["1,250,000"])
    # 1,250.00 is 1250 with cents, not 125000 (ruling R71); its zeros fold away (ruling R72).
    assert scan_package(make_docx(para("A fee of EUR 1,250.00 applies.")), [big]) == []
    shown = para("A fee of EUR 1,250.00 applies.") + para("A cap of 1.250.000,00 applies.")
    hits = scan_package(make_docx(shown), [small, million])
    assert [hit.context for hit in hits] == [
        "A fee of [AMOUNT_2] applies.",
        "A cap of [AMOUNT_3] applies.",
    ]
    # Three digits after the last separator are a group of thousands, not decimals: 1,250.125 is
    # the number 1250125, and holds no 1,250.
    assert scan_package(make_docx(para("A rate of 1,250.125 applies.")), [small]) == []


def test_a_decimal_point_is_unlike_the_separators_before_it(make_docx: MakeDocx) -> None:
    tel = KeyEntry("[PHONE_1]", PHONE, "08 123 456 78", [])
    register = KeyEntry("[ID_1]", ID, "123.456.78", [])
    # A full stop that also parts the groups before it is no decimal point (ruling R72): these
    # are the same digits, grouped another way.
    shown = para("Tel. 08.123.456.78") + para("Register 123 456 78.")
    hits = scan_package(make_docx(shown), [tel, register])
    assert [hit.context for hit in hits] == ["Tel. [PHONE_1]", "Register [ID_1]."]
    assert_nothing_shown(hits, [tel, register])


def test_the_zeros_that_end_a_decimal_part_fold_away(make_docx: MakeDocx) -> None:
    written = KeyEntry("[AMOUNT_1]", AMOUNT, "EUR 1,250.50", [])
    short = KeyEntry("[AMOUNT_2]", AMOUNT, "EUR 1,250.5", [])
    # 1,250.50 and 1,250.5 are one amount, however it is written (ruling R72).
    for entry, text in ((written, "EUR 1,250.5"), (short, "EUR 1,250.50")):
        hits = scan_package(make_docx(para(f"A fee of {text} applies.")), [entry])
        assert [hit.context for hit in hits] == [f"A fee of {entry.placeholder} applies."]
    # 1,250.00 is 1,250, written with its zeros or not, and still no 125,000.
    even = KeyEntry("[AMOUNT_3]", AMOUNT, "EUR 1,250.00", ["1,250.00"])
    shown = para("A fee of EUR 1,250 applies.") + para("A deposit of EUR 1,250.0 applies.")
    hits = scan_package(make_docx(shown), [even])
    assert [hit.context for hit in hits] == [
        "A fee of [AMOUNT_3] applies.",
        "A deposit of [AMOUNT_3] applies.",
    ]
    assert_nothing_shown(hits, [even])
    assert scan_package(make_docx(para("A cap of EUR 125,000 applies.")), [even]) == []


def test_a_number_counts_only_where_written_with_four_letters_and_digits(
    make_docx: MakeDocx,
) -> None:
    # 10.00% is the number 10 (ruling R72), which would be found everywhere: it counts where the
    # text writes it with its zeros, as the key does, and never as a bare 10 (ruling R14 c).
    rate = KeyEntry("[PERCENT_1]", PERCENT, "10.00%", [])
    fee = KeyEntry("[AMOUNT_1]", AMOUNT, "\N{EURO SIGN}159.00", ["159.00"])
    assert unverifiable([rate, fee]) == []
    quiet = para("Clause 10 applies for 10 days.") + para("See page 159.")
    assert scan_package(make_docx(quiet), [rate, fee]) == []
    shown = para("Interest of 10,00% applies.") + para("A fee of 159.00 applies.")
    hits = scan_package(make_docx(shown), [rate, fee])
    assert [hit.context for hit in hits] == [
        "Interest of [PERCENT_1]% applies.",
        "A fee of [AMOUNT_1] applies.",
    ]


# ---- the file format's names, and those it was given (rulings R66, R67) --------------------------


def branded(src: Path, out: Path) -> Path:
    """A copy of the Word file ``src`` whose theme, colour scheme and fonts are named after the
    company Northwind."""
    with zipfile.ZipFile(src) as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for info, data in entries:
            if info.filename == "word/theme/theme1.xml":
                data = data.replace(b'name="Office Theme"', b'name="Northwind Trading"')
                data = data.replace(b'<a:clrScheme name="Office"', b'<a:clrScheme name="Northwind"')
                data = data.replace(
                    b'<a:latin typeface="Cambria"', b'<a:latin typeface="Northwind Sans"'
                )
            if info.filename == "word/fontTable.xml":
                font = b'<w:font w:name="Northwind Sans"><w:family w:val="swiss"/></w:font>'
                data = data.replace(b"</w:fonts>", font + b"</w:fonts>")
            if info.filename == "word/styles.xml":
                data = data.replace(b"<w:rFonts ", b'<w:rFonts w:ascii="Northwind Sans" ', 1)
            archive.writestr(info, data)
    return out


def test_a_theme_named_after_the_company_is_renamed_and_its_font_found(
    corpus: Path, tmp_path: Path
) -> None:
    source = branded(corpus / "supply-01.docx", tmp_path / "branded.docx")
    with zipfile.ZipFile(source) as archive:
        assert archive.read("word/theme/theme1.xml").count(b"Northwind") == 3
    masked = mask_file(source, E, tmp_path / "MASKED-BRND.docx")
    with zipfile.ZipFile(masked) as archive:  # the cleaner gave the theme Word's own names
        theme = archive.read("word/theme/theme1.xml")
        assert b'name="Office Theme"' in theme and b'clrScheme name="Office"' in theme
    hits = scan_package(masked, E)
    assert [(hit.part, hit.context) for hit in hits] == [
        ("word/styles.xml", 'ascii="[COMPANY_1] Sans"'),
        ("word/fontTable.xml", 'name="[COMPANY_1] Sans"'),
        ("word/theme/theme1.xml", 'typeface="[COMPANY_1] Sans"'),
    ]


def styles_part(*styles: str) -> bytes:
    content = "".join(styles)
    return xml(
        f'<w:styles xmlns:w="{W_NS}"><w:latentStyles>'
        '<w:lsdException w:name="Light Shading Accent 1"/></w:latentStyles>'
        f"{content}</w:styles>"
    )


def test_built_in_styles_are_no_names_but_custom_ones_are(make_docx: MakeDocx) -> None:
    title = KeyEntry("[COMPANY_1]", COMPANY, "Title Insurance Ltd", ["Title Insurance", "Title"])
    accent = KeyEntry("[COMPANY_2]", COMPANY, "Accent Housing Ltd", ["Accent Housing", "Accent"])
    built_in = styles_part(
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>',
        '<w:style w:type="character" w:styleId="TitleChar"><w:name w:val="Title Char"/>'
        '<w:link w:val="Title"/></w:style>',
    )
    body = '<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Agreement</w:t></w:r></w:p>'
    path = make_docx(body, raw={"word/styles.xml": built_in})
    assert scan_package(path, [title, accent]) == []
    # A style of the template's own, named after the company, is a name like any text.
    northwind = KeyEntry("[COMPANY_3]", COMPANY, "Northwind Trading B.V.", ["Northwind"])
    custom = styles_part(
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="Northwind">'
        '<w:name w:val="Northwind Heading"/><w:basedOn w:val="Title"/></w:style>'
    )
    body = '<w:p><w:pPr><w:pStyle w:val="Northwind"/></w:pPr><w:r><w:t>Agreement</w:t></w:r></w:p>'
    hits = scan_package(make_docx(body, raw={"word/styles.xml": custom}), [northwind])
    assert [(hit.part, hit.context) for hit in hits] == [
        ("word/document.xml", 'val="[COMPANY_3]"'),
        ("word/styles.xml", 'styleId="[COMPANY_3]"'),
        ("word/styles.xml", 'val="[COMPANY_3] Heading"'),
    ]


def test_word_s_own_styles_in_the_corpus_are_no_names(masked_docx: Path) -> None:
    accent = KeyEntry("[COMPANY_1]", COMPANY, "Accent Housing Ltd", ["Accent Housing", "Accent"])
    with zipfile.ZipFile(masked_docx) as archive:
        assert b"Light Shading Accent 1" in archive.read("word/styles.xml")
    assert scan_package(masked_docx, [accent]) == []


# ---- names however they are punctuated (ruling R68) ----------------------------------------------


def test_names_are_found_however_they_are_punctuated(make_docx: MakeDocx) -> None:
    northwind = KeyEntry(
        "[COMPANY_1]", COMPANY, "Northwind Trading B.V.", ["Northwind Trading", "Northwind"]
    )
    north_wind = KeyEntry(
        "[COMPANY_2]", COMPANY, "North-Wind Logistics GmbH", ["North-Wind Logistics"]
    )
    acme = KeyEntry("[COMPANY_3]", COMPANY, "Acme B.V.", [])
    body = (
        para("North-wind shall pay.")
        + para("Northwind Logistics shall pay.")
        + para("Acme BV signs.")
    )
    hits = scan_package(make_docx(body), [northwind, north_wind, acme])
    assert [(hit.placeholder, hit.context) for hit in hits] == [
        ("[COMPANY_1]", "[COMPANY_1] shall pay."),
        ("[COMPANY_2]", "[COMPANY_2] shall pay."),
        ("[COMPANY_3]", "[COMPANY_3] signs."),
    ]
    # An initial's full stop before a word still parts them: "S.Hall" makes no "shall".
    sarah = KeyEntry("[PERSON_1]", PERSON, "Sarah Hall", ["S.Hall", "S. Hall"])
    assert scan_package(make_docx(para("The Supplier shall deliver.")), [sarah]) == []
    # So does a slash: "and/or" makes no "Andor" (ruling R72).
    andor = KeyEntry("[COMPANY_4]", COMPANY, "Andor Technology Ltd", ["Andor"])
    assert scan_package(make_docx(para("The Supplier and/or the Buyer shall pay.")), [andor]) == []


# ---- what a hit shows, and how many it is (ruling R69) -------------------------------------------


def test_a_context_hides_every_spelling_of_a_value(make_docx: MakeDocx) -> None:
    acme = KeyEntry("[COMPANY_2]", COMPANY, "Acme Holdings Ltd", ["Acme Holdings", "Acme"])
    jane = KeyEntry("[PERSON_1]", PERSON, "Jane Smith", ["J. Smith"])
    body = (
        para("Acme2 and 2Acme and Acme_X.")
        + para("Acme and AcmeHoldings sign.")
        + para("Acme BV pays; Acme B.V. signs.")
        + para("Jane Smith and SmithCo sign.")
    )
    hits = scan_package(make_docx(body), [acme, jane])
    assert [(hit.context, hit.count) for hit in hits] == [
        ("[COMPANY_2]2 and 2[COMPANY_2] and [COMPANY_2]_X.", 1),
        ("[COMPANY_2] and [COMPANY_2] sign.", 1),
        ("[COMPANY_2] BV pays; [COMPANY_2] B.V. signs.", 2),
        ("[PERSON_1] and [PERSON_1]Co sign.", 1),
    ]
    assert_nothing_shown(hits, [acme, jane])


def test_each_place_is_counted(make_docx: MakeDocx) -> None:
    body = para("Signed for Northwind.") * 3
    hits = scan_package(make_docx(body), E)
    assert hits == [LeakHit("word/document.xml", "[COMPANY_1]", "Signed for [COMPANY_1].", 3)]
    assert hits_by_placeholder(hits) == {"[COMPANY_1]": 3}
    # A value shown as it is, and %-escaped in the link beside it, is in two places.
    body = (
        '<w:p><w:r><w:t xml:space="preserve">Northwind </w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve">'
        ' HYPERLINK "https://x.example/North%77ind" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    hits = scan_package(make_docx(body), E)
    assert hits_by_placeholder(hits) == {"[COMPANY_1]": 2}
    assert_nothing_shown(hits, E)
    # The same bytes read two ways are one place.
    blob = "NL91ABNA0417164300".encode("utf-16-le")
    hits = scan_package(make_docx(para("Clean."), raw={"word/embeddings/x.bin": blob}), E)
    assert hits_by_placeholder(hits) == {"[IBAN_1]": 1}


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
        # A name is never part of a longer word either (ruling R63).
        '<w:p><w:fldSimple w:instr=" PAGEREF _Ref1 \\h "><w:r><w:t>3</w:t></w:r></w:fldSimple>'
        '<w:fldSimple w:instr=" NUMPAGES "><w:r><w:t>9</w:t></w:r></w:fldSimple></w:p>'
    )
    words = [
        KeyEntry("[CUSTOM_1]", CUSTOM, "Page", []),
        KeyEntry("[CUSTOM_2]", CUSTOM, "MergeFormat", []),
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


# ---- the whole pipeline -------------------------------------------------------------------------


def key_of(group: Group) -> KeyEntry:
    """A group's line of the key, as the review gives it: a person's bare surname is no variant
    (ruling R52)."""
    variants = sorted(
        v for v in group.variants if v != group.canonical and not is_bare_name(group.type, v)
    )
    return KeyEntry(group.placeholder, group.type, group.canonical, variants)


@pytest.mark.parametrize("name", ["supply-01", "supply-04", "nda-02", "dpa-01", "services-03"])
def test_corpus_files_masked_by_the_pipeline_have_no_hits(
    name: str, corpus: Path, engine: Engine, lists: UserLists, tmp_path: Path
) -> None:
    # Analysed, every group's findings masked, then scanned for the key the groups make.
    pkg = DocxPackage.open(corpus / f"{name}.docx")
    accept_all(pkg)
    clean(pkg)
    doc_text = extract_text(pkg)
    groups = analyze(CombinedText.join([(f"{name}.docx", doc_text.text)]), engine, lists).groups
    marked = [group for group in groups if group.enabled]
    plan = MaskPlan(
        [Replacement(f.start, f.end, g.placeholder) for g in marked for f in g.active_findings()]
    )
    apply_mask(pkg, doc_text, plan)
    insert_banner(pkg)
    masked = tmp_path / "MASKED-CORP.docx"
    pkg.save(masked)
    assert scan_package(masked, [key_of(group) for group in marked]) == []


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
