"""The made-up contract corpus: counts, ground truth, real features and determinism.

Every later task tests against these files, so besides the checks from the plan these tests pin
the promises the corpus makes: the fixed feature assignments, values written verbatim in the text,
the ``only_in_deletion`` and ``hidden`` flags, no number or contact detail left out of the truth,
and no placeholder-like token where none is meant to be.
"""

from __future__ import annotations

import json
import re
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import phonenumbers
from lxml import etree
from schwifty import BIC, IBAN
from stdnum.eu import vat

from themask.placeholders import find_placeholders
from themask.textnorm import flexible_pattern, normalize
from tools.make_corpus import generate, main

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {
    "w": W,
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "v": "urn:schemas-microsoft-com:vml",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
ALL_TYPES = {"PERSON", "COMPANY", "AMOUNT", "PERCENT", "QUANTITY", "EMAIL", "PHONE", "ADDRESS"}
ALL_TYPES |= {"IBAN", "ID", "URL"}

# The fixed assignments later tasks rely on: each of these files has exactly these features
# besides "header_footer" and "table", which every file has.
FIXED = {
    "supply-01.docx": set(),
    "supply-02.docx": {"comments"},
    "supply-03.docx": {"tracked_changes", "secret_only_in_deletion"},
    "supply-04.docx": {"properties"},
    "supply-05.docx": {"image"},
    "supply-06.docx": {"footnotes"},
    "supply-07.docx": {"annex"},
    "supply-08.docx": {"shared_surname"},
    "supply-09.docx": {"existing_placeholders"},
    "supply-10.docx": {"thirty_pages"},
    "services-01.docx": {"hyperlinks"},
    "services-02.docx": {"hidden_text"},
    "services-03.docx": {"textbox"},
    "services-04.docx": {"nbsp_numbers"},
}
FREE = ["services-05.docx", *(f"nda-0{i}.docx" for i in range(1, 6))]
FREE += [f"dpa-0{i}.docx" for i in range(1, 6)]
FEATURES = {
    "header_footer",
    "table",
    "comments",
    "tracked_changes",
    "secret_only_in_deletion",
    "image",
    "footnotes",
    "hidden_text",
    "textbox",
    "properties",
    "hyperlinks",
    "shared_surname",
    "existing_placeholders",
    "nbsp_numbers",
    "annex",
    "thirty_pages",
}

# --------------------------------------------------------------------------------------------
# The plan's tests
# --------------------------------------------------------------------------------------------


def test_corpus_counts(corpus: Path) -> None:
    assert len(list(corpus.glob("*.docx"))) >= 20 and len(list(corpus.glob("*.truth.json"))) >= 20


def test_truth_covers_every_type(corpus: Path) -> None:
    types = {t["type"] for p in corpus.glob("*.truth.json") for t in json.loads(p.read_text())}
    assert ALL_TYPES <= types


def test_features_are_real(corpus: Path) -> None:
    man = json.loads((corpus / "manifest.json").read_text())
    for doc in man:
        with zipfile.ZipFile(corpus / doc["file"]) as package:
            names = set(package.namelist())
            xml = package.read("word/document.xml").decode()
            core = package.read("docProps/core.xml").decode()
        if "comments" in doc["features"]:
            assert "word/comments.xml" in names
        if "tracked_changes" in doc["features"]:
            assert "<w:ins " in xml and "<w:del " in xml
        if "image" in doc["features"]:
            assert any(n.startswith("word/media/") for n in names)
        if "properties" in doc["features"]:
            assert "<dc:creator>" in core


def test_every_truth_value_is_in_the_file(corpus: Path) -> None:
    for p in corpus.glob("*.truth.json"):
        with zipfile.ZipFile(p.with_suffix("").with_suffix(".docx")) as package:
            names = [n for n in package.namelist() if n.endswith(".xml")]
            blob = normalize("".join(package.read(n).decode("utf-8", "ignore") for n in names))
        for t in json.loads(p.read_text()):
            assert normalize(t["value"]) in blob, (p.name, t["value"])


def test_deterministic(tmp_path: Path) -> None:
    a = generate(tmp_path / "a")
    b = generate(tmp_path / "b")
    assert a == b
    assert (tmp_path / "a" / "supply-01.truth.json").read_bytes() == (
        tmp_path / "b" / "supply-01.truth.json"
    ).read_bytes()
    # Not only the truth: every file, Word files included, comes out byte for byte the same.
    files_a = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert files_a == sorted(p.name for p in (tmp_path / "b").iterdir())
    for name in files_a:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


# --------------------------------------------------------------------------------------------
# Reading a generated file back, independently of the generator
# --------------------------------------------------------------------------------------------

_TEXT_PART = re.compile(r"word/(document|header\d+|footer\d+|footnotes)\.xml")


@dataclass(frozen=True)
class Para:
    """One ``w:p`` of a text part, split by what a reader of the file sees."""

    part: str
    visible: str  # the text with every change accepted: no deleted and no hidden text
    deleted: str  # the text inside w:delText
    hidden: str  # the text of runs marked w:vanish
    runs: tuple[tuple[str, bool], ...]  # (text, bold) of each run holding w:t, in order


@cache
def paras(path: Path) -> tuple[Para, ...]:
    out = []
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            if not _TEXT_PART.fullmatch(name):
                continue
            root = etree.fromstring(package.read(name))
            for p in root.iter(f"{{{W}}}p"):
                visible: list[str] = []
                deleted: list[str] = []
                hidden: list[str] = []
                runs: list[tuple[str, bool]] = []
                for r in p.iter(f"{{{W}}}r"):
                    if next(r.iterancestors(f"{{{W}}}p")) is not p:
                        continue  # a run of a paragraph nested in a text box
                    is_hidden = r.find("w:rPr/w:vanish", NS) is not None
                    bold = r.find("w:rPr/w:b", NS) is not None
                    for child in r:
                        if child.tag == f"{{{W}}}t":
                            (hidden if is_hidden else visible).append(child.text or "")
                            runs.append((child.text or "", bold))
                        elif child.tag == f"{{{W}}}delText":
                            deleted.append(child.text or "")
                out.append(
                    Para(name, "".join(visible), "".join(deleted), "".join(hidden), tuple(runs))
                )
    return tuple(out)


def manifest(corpus: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = json.loads((corpus / "manifest.json").read_text())
    return result


def truth_of(corpus: Path, file: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = json.loads(
        (corpus / file.replace(".docx", ".truth.json")).read_text(encoding="utf-8")
    )
    return result


def part_text(path: Path, part: str) -> str:
    return "\n".join(p.visible for p in paras(path) if p.part == part)


def words(text: str) -> int:
    return len(re.findall(r"\w+", text))


# --------------------------------------------------------------------------------------------
# The manifest and the fixed assignments
# --------------------------------------------------------------------------------------------


def test_fixed_assignments(corpus: Path) -> None:
    features = {d["file"]: set(d["features"]) for d in manifest(corpus)}
    for file, extra in FIXED.items():
        assert features[file] == {"header_footer", "table"} | extra, file
    for file in FREE:
        assert {"header_footer", "table"} <= features[file], file


def test_manifest_entries(corpus: Path) -> None:
    man = manifest(corpus)
    assert [d["file"] for d in man if "annex_of" not in d] == [*FIXED, *FREE]
    for d in man:
        assert d["format"] == "docx" and (corpus / d["file"]).is_file()
        assert d["truth"] == d["file"].replace(".docx", ".truth.json")
        assert (corpus / d["truth"]).is_file()
        assert set(d["features"]) <= FEATURES and d["features"] == sorted(d["features"])


def test_every_feature_in_at_least_three_documents(corpus: Path) -> None:
    main_docs = [d for d in manifest(corpus) if "annex_of" not in d]
    count = Counter(f for d in main_docs for f in d["features"])
    assert all(count[f] >= 3 for f in FEATURES), count
    # The named documents are 25 contracts: supply-01 to -10 and five each of the other kinds.
    assert count["header_footer"] == count["table"] == len(main_docs) == 25


def test_annexes_belong_to_their_contract(corpus: Path) -> None:
    man = manifest(corpus)
    annexes = {d["annex_of"]: d["file"] for d in man if "annex_of" in d}
    with_annex = {d["file"] for d in man if "annex" in d["features"]}
    assert set(annexes) == with_annex
    assert annexes["supply-07.docx"] == "supply-07-annex.docx"
    for contract, annex in annexes.items():
        # The annex names both parties in full, so the same company gets the same placeholder.
        companies = [t["value"] for t in truth_of(corpus, contract) if t["type"] == "COMPANY"]
        annex_text = "\n".join(p.visible for p in paras(corpus / annex))
        assert companies[0] in annex_text and companies[1] in annex_text, annex


# --------------------------------------------------------------------------------------------
# Each feature is really in the file
# --------------------------------------------------------------------------------------------


def _read(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as package:
        return package.read(name).decode("utf-8")


def _names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as package:
        return set(package.namelist())


def _check_feature(corpus: Path, doc: dict[str, Any], feature: str) -> None:
    path = corpus / doc["file"]
    names = _names(path)
    xml = _read(path, "word/document.xml")
    truth = truth_of(corpus, doc["file"])
    people = [t["value"] for t in truth if t["type"] == "PERSON"]
    text = "\n".join(p.visible for p in paras(path) if p.part == "word/document.xml")
    if feature == "header_footer":
        assert {"word/header1.xml", "word/footer1.xml"} <= names
        assert " / " in part_text(path, "word/header1.xml")
        assert "Confidential" in part_text(path, "word/footer1.xml")
        assert '<w:fldSimple w:instr="PAGE">' in _read(path, "word/footer1.xml")
    elif feature == "table":
        assert "<w:tbl>" in xml
    elif feature == "comments":
        comments = _read(path, "word/comments.xml")
        assert "<w:comment " in comments and "commentReference" in xml
        assert any(person in comments for person in people)
    elif feature == "tracked_changes":
        assert "<w:ins " in xml and "<w:del " in xml and "<w:delText" in xml
        assert "<w:trackRevisions/>" in _read(path, "word/settings.xml")
    elif feature == "secret_only_in_deletion":
        assert any(t.get("only_in_deletion") for t in truth)
    elif feature == "image":
        assert any(n.startswith("word/media/") for n in names) and "<a:blip " in xml
    elif feature == "footnotes":
        footnotes = paras(path)
        assert "<w:footnoteReference " in xml
        assert any(p.part == "word/footnotes.xml" and p.visible.strip() for p in footnotes)
    elif feature == "hidden_text":
        assert "<w:vanish/>" in xml and any(t.get("hidden") for t in truth)
    elif feature == "textbox":
        assert "<wps:txbx>" in xml and "<v:textbox" in xml and "Text box note" in text
    elif feature == "properties":
        core = etree.fromstring(_read(path, "docProps/core.xml").encode())
        app = etree.fromstring(_read(path, "docProps/app.xml").encode())
        for tag in ("dc:creator", "cp:lastModifiedBy", "dc:title", "cp:keywords"):
            assert (core.findtext(tag, namespaces=NS) or "").strip(), tag
        for tag in ("ep:Company", "ep:Manager"):
            assert (app.findtext(tag, namespaces=NS) or "").strip(), tag
        assert "TitlesOfParts" in _read(path, "docProps/app.xml")
        assert "docProps/custom.xml" in names and "<vt:lpwstr>" in _read(
            path, "docProps/custom.xml"
        )
    elif feature == "hyperlinks":
        rels = _read(path, "word/_rels/document.xml.rels")
        assert 'Target="mailto:' in rels and 'Target="https://' in rels
        assert "<w:hyperlink " in xml
    elif feature == "shared_surname":
        surnames = Counter(person.split()[-1] for person in people)
        shared = [s for s, n in surnames.items() if n >= 2]
        assert shared and any(f"Mr {s}" in text for s in shared)
    elif feature == "existing_placeholders":
        assert "[PERSON_1]" in text and "[Name]" in text
    elif feature == "nbsp_numbers":
        assert re.search("[0-9][\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}][0-9]", text)
    elif feature == "annex":
        assert (corpus / doc["file"].replace(".docx", "-annex.docx")).is_file()
    elif feature == "thirty_pages":
        assert words(text) >= 12_000
    else:
        raise AssertionError(f"no check for feature {feature!r}")


def test_every_feature_is_really_there(corpus: Path) -> None:
    for doc in manifest(corpus):
        for feature in doc["features"]:
            _check_feature(corpus, doc, feature)


def test_features_not_claimed_are_absent(corpus: Path) -> None:
    for doc in manifest(corpus):
        path = corpus / doc["file"]
        names = _names(path)
        xml = _read(path, "word/document.xml")
        absent = FEATURES - set(doc["features"])
        if "comments" in absent:
            assert "word/comments.xml" not in names, doc["file"]
        if "tracked_changes" in absent:
            assert "<w:ins " not in xml and "<w:del " not in xml, doc["file"]
        if "image" in absent:
            assert not any(n.startswith("word/media/") for n in names), doc["file"]
        if "footnotes" in absent:
            assert "word/footnotes.xml" not in names, doc["file"]
        if "hidden_text" in absent:
            assert "<w:vanish/>" not in xml, doc["file"]
        if "textbox" in absent:
            assert "<wps:txbx>" not in xml, doc["file"]
        if "properties" in absent:
            assert "docProps/custom.xml" not in names, doc["file"]
        if "hyperlinks" in absent:
            assert "<w:hyperlink " not in xml, doc["file"]


# --------------------------------------------------------------------------------------------
# What the truth files promise
# --------------------------------------------------------------------------------------------


def test_truth_items_are_well_formed(corpus: Path) -> None:
    for doc in manifest(corpus):
        seen = set()
        for t in truth_of(corpus, doc["file"]):
            assert set(t) <= {"type", "value", "variants", "only_in_deletion", "hidden"}, t
            assert t["type"] in ALL_TYPES and t["value"].strip() == t["value"], t
            assert t.get("only_in_deletion", True) is True and t.get("hidden", True) is True, t
            assert t["value"] not in t["variants"] and len(set(t["variants"])) == len(t["variants"])
            assert (t["type"], t["value"]) not in seen, t
            seen.add((t["type"], t["value"]))


_BIC_SHAPE = re.compile(r"[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?")


def test_numbers_pass_their_own_checks(corpus: Path) -> None:
    """IBANs, BICs, VAT and telephone numbers are valid, by the libraries that check them."""
    checked: Counter[str] = Counter()
    for p in corpus.glob("*.truth.json"):
        truth = json.loads(p.read_text(encoding="utf-8"))
        ibans = [IBAN(t["value"]) for t in truth if t["type"] == "IBAN"]  # raises if not valid
        banks = {str(iban.bic).removesuffix("XXX") for iban in ibans}
        for t in truth:
            value, variants = t["value"], t["variants"]
            if t["type"] == "IBAN":
                assert all(IBAN(v).compact == IBAN(value).compact for v in variants), t
                checked["IBAN"] += 1
            elif t["type"] == "ID" and _BIC_SHAPE.fullmatch(value):
                assert str(BIC(value)) == value and value in banks, (p.name, value)  # the IBAN's
                checked["BIC"] += 1
            elif (
                t["type"] == "ID" and value[:2].lower() in vat.MEMBER_STATES and value[2].isdigit()
            ):
                assert vat.is_valid(value), (p.name, value)
                checked["VAT"] += 1
            elif t["type"] == "PHONE":
                number = phonenumbers.parse(value, None)
                region = phonenumbers.region_code_for_number(number)
                assert phonenumbers.is_valid_number(number), (p.name, value)
                assert all(phonenumbers.parse(v, region) == number for v in variants), t
                checked["PHONE"] += 1
    assert min(checked[kind] for kind in ("IBAN", "BIC", "VAT", "PHONE")) > 0, checked


def test_truth_files_are_ascii(corpus: Path) -> None:
    # Plain ASCII JSON reads the same whatever the platform's default encoding.
    for p in corpus.glob("*.truth.json"):
        p.read_bytes().decode("ascii")


def test_values_and_variants_are_written_verbatim_where_the_flags_say(corpus: Path) -> None:
    for doc in manifest(corpus):
        ps = paras(corpus / doc["file"])
        visible = "\n".join(p.visible for p in ps)
        deleted = "\n".join(p.deleted for p in ps)
        hidden = "\n".join(p.hidden for p in ps)
        for t in truth_of(corpus, doc["file"]):
            where = (doc["file"], t["value"])
            if t.get("only_in_deletion"):
                assert t["value"] in deleted and t["value"] not in visible + hidden, where
                home = deleted
            elif t.get("hidden"):
                assert t["value"] in hidden and t["value"] not in visible + deleted, where
                home = hidden
            else:
                assert t["value"] in visible, where
                home = visible
            for variant in t["variants"]:
                assert variant in home, (*where, variant)


def test_flagged_items_where_later_tasks_look_for_them(corpus: Path) -> None:
    assert any(t.get("only_in_deletion") for t in truth_of(corpus, "supply-03.docx"))
    assert any(t.get("hidden") for t in truth_of(corpus, "services-02.docx"))
    for doc in manifest(corpus):
        truth = truth_of(corpus, doc["file"])
        if "secret_only_in_deletion" not in doc["features"]:
            assert not any(t.get("only_in_deletion") for t in truth), doc["file"]
        if "hidden_text" not in doc["features"]:
            assert not any(t.get("hidden") for t in truth), doc["file"]


_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\d{{1,2}} ({_MONTHS}) \d{{4}}")
_DURATION = re.compile(r"\d+ (Business )?(days?|weeks?|months?|years?|hours?)", re.IGNORECASE)
_NEVER = {
    "england and wales",
    "the netherlands",
    "netherlands",
    "germany",
    "ireland",
    "united kingdom",
    "eur",
    "gbp",
    "€",
    "£",
    "agreement",
    "supplier",
    "buyer",
    "service provider",
    "customer",
    "discloser",
    "recipient",
    "controller",
    "processor",
    "goods",
    "services",
    "price",
    "charges",
    "party",
    "parties",
}


def test_dates_durations_jurisdictions_and_defined_terms_are_never_truth(corpus: Path) -> None:
    for p in corpus.glob("*.truth.json"):
        for t in json.loads(p.read_text(encoding="utf-8")):
            for form in [t["value"], *t["variants"]]:
                assert not _DATE.fullmatch(form) and not _DURATION.fullmatch(form), (p.name, form)
                assert form.casefold() not in _NEVER, (p.name, form)


# Everything that looks like a number or a contact detail. A plain number counts from four digits
# (shorter ones are clause numbers and durations), and a four-digit year is a date, not a secret.
_SUSPECT = re.compile(
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|https?://[^\s,;)]+|www\.[^\s,;)]+"
    r"|\bBIC:?\s*[A-Z0-9]{8,11}"
    r"|\b[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){2,}(?: ?[A-Z0-9]{1,4})?"
    r"|(?:EUR|GBP|€|£)\s?[0-9][0-9.,\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE} ]*"
    r"|[0-9][0-9.,\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}]*\s?(?:%|per cent|percent)"
    r"|[0-9][0-9.,\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE} ]*"
)


def _uncovered(text: str, forms: list[str]) -> list[str]:
    spans = [(m.start(), m.end()) for f in forms for m in re.finditer(re.escape(f), text)]
    missing = []
    for m in _SUSPECT.finditer(text):
        token = m.group().rstrip(".,; \N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}")
        start, end = m.start(), m.start() + len(token)
        if token[0].isdigit() and not re.search(r"%|per ?cent", token):
            digits = re.sub(r"\D", "", token)
            if len(digits) < 4 or (len(digits) == 4 and 1900 <= int(digits) <= 2099):
                continue
        if token.startswith("BIC"):
            start = end - len(token.split()[-1].removeprefix("BIC:"))
        if not any(a <= start and end <= b for a, b in spans):
            missing.append(token)
    return missing


def test_no_number_or_contact_detail_is_left_out_of_the_truth(corpus: Path) -> None:
    for doc in manifest(corpus):
        forms = [f for t in truth_of(corpus, doc["file"]) for f in [t["value"], *t["variants"]]]
        for p in paras(corpus / doc["file"]):
            for text in (p.visible, p.deleted, p.hidden):
                assert not _uncovered(text, forms), (doc["file"], _uncovered(text, forms), text)


def test_amounts_without_a_currency_are_few_and_in_price_context(corpus: Path) -> None:
    # Ruling R5: table amounts carry a currency; two or three bare amounts appear in running text
    # ("a total price of 48,000 per year") and are listed as AMOUNT like any other amount.
    bare = []
    for doc in manifest(corpus):
        text = "\n".join(p.visible for p in paras(corpus / doc["file"]))
        for t in truth_of(corpus, doc["file"]):
            if t["type"] == "AMOUNT" and re.fullmatch(r"[0-9][0-9.,]*", t["value"]):
                assert f"of {t['value']} per year" in text, (doc["file"], t["value"])
                bare.append(t["value"])
    assert 2 <= len(bare) <= 3, bare


def test_no_placeholder_lookalikes_except_where_meant(corpus: Path) -> None:
    for doc in manifest(corpus):
        ps = paras(corpus / doc["file"])
        text = "\n".join(f"{p.visible}\n{p.deleted}\n{p.hidden}" for p in ps)
        found = find_placeholders(text)
        if "existing_placeholders" in doc["features"]:
            assert {m.raw for m in found} == {"[PERSON_1]"}, doc["file"]
        else:
            assert found == [], (doc["file"], [m.raw for m in found])


# --------------------------------------------------------------------------------------------
# The particular values later tasks use
# --------------------------------------------------------------------------------------------


def test_party_names_are_bold_and_split_across_three_runs(corpus: Path) -> None:
    for doc in manifest(corpus):
        companies = [t["value"] for t in truth_of(corpus, doc["file"]) if t["type"] == "COMPANY"]
        parties = [p for p in paras(corpus / doc["file"]) if re.match(r"\(\d\) ", p.visible)]
        assert len(parties) == 2, doc["file"]
        for p, name in zip(parties, companies[:2]):
            start = p.visible.index(name)
            covering, pos = [], 0
            for run_text, bold in p.runs:
                if pos < start + len(name) and pos + len(run_text) > start:
                    covering.append(bold)
                pos += len(run_text)
            assert len(covering) >= 3 and all(covering), (doc["file"], name)


def test_supply_01_northwind_runs(corpus: Path) -> None:
    path = corpus / "supply-01.docx"
    text = part_text(path, "word/document.xml")
    assert text.count("Northwind Trading B.V.") >= 3
    first = next(p for p in paras(path) if "Northwind Trading B.V." in p.visible)
    assert first.visible.startswith("(1) ")  # the first mention is the bold one, in the parties
    assert ("Northwind ", True) in first.runs and ("Trading ", True) in first.runs
    assert ("B.V.", True) in first.runs


def test_supply_06_acme_in_header_footer_and_footnotes(corpus: Path) -> None:
    path = corpus / "supply-06.docx"
    for part in ("word/header1.xml", "word/footer1.xml", "word/footnotes.xml"):
        assert "Acme" in part_text(path, part), part


def test_supply_08_project_falcon_twice(corpus: Path) -> None:
    # Plain text, not a secret of the truth: later tasks hide it by hand as a user-added term.
    path = corpus / "supply-08.docx"
    assert "\n".join(p.visible for p in paras(path)).count("Project Falcon") == 2
    truth = truth_of(corpus, "supply-08.docx")
    assert not any("Falcon" in form for t in truth for form in [t["value"], *t["variants"]])


def test_services_01_first_email_is_a_mailto_link(corpus: Path) -> None:
    path = corpus / "services-01.docx"
    email = next(t["value"] for t in truth_of(corpus, "services-01.docx") if t["type"] == "EMAIL")
    assert f'Target="mailto:{email}"' in _read(path, "word/_rels/document.xml.rels")


def test_supply_01_leaves_nothing_once_its_truth_is_masked(corpus: Path) -> None:
    """Mask every truth value and variant of supply-01 in its text and nothing is left anywhere.

    The export and logging tests of later tasks search a whole package (or the log) for each
    normalised truth value of supply-01, so none of its values may also hide in the file's
    scaffolding (styles, theme, settings, numbers in attributes) or in the ordinary text.
    """
    truth = truth_of(corpus, "supply-01.docx")
    forms = sorted({f for t in truth for f in [t["value"], *t["variants"]]}, key=len, reverse=True)
    patterns = [flexible_pattern(f) for f in forms]
    blob = []
    with zipfile.ZipFile(corpus / "supply-01.docx") as package:
        for name in package.namelist():
            data = package.read(name)
            if name.endswith((".xml", ".rels")):
                root = etree.fromstring(data)
                for node in root.iter(f"{{{W}}}t", f"{{{W}}}delText"):
                    node_text = node.text or ""
                    for pattern in patterns:
                        node_text = pattern.sub("[MASKED]", node_text)
                    node.text = node_text
                data = etree.tostring(root)
            blob.append(data.decode("utf-8", "ignore"))
    flat = normalize("".join(blob))
    for t in truth:
        assert normalize(t["value"]) not in flat, t["value"]


# --------------------------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------------------------


def test_command_line_writes_the_same_corpus_quickly(corpus: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    started = time.perf_counter()
    assert main([str(out)]) == 0
    assert time.perf_counter() - started < 30
    assert sorted(p.name for p in out.iterdir()) == sorted(p.name for p in corpus.iterdir())
    for p in out.iterdir():
        assert p.read_bytes() == (corpus / p.name).read_bytes(), p.name
