"""The cleaner: takes the hidden places out of a Word file, where a value can leave unseen.

The owner reviews the text of a contract, but a .docx holds much more than the text: comments,
file properties, hidden text, pictures and embedded objects, custom XML, the path of the template,
revision traces, and text that Word keeps in attributes. A value left in any of them is a leak the
owner cannot see. ``clean`` removes them from the package in memory, so that what is left is the
visible text, which the masker then changes value by value.

It runs on the copy that is going to be masked, after the tracked changes are resolved and before
the text is read for review, because it changes the text: hidden runs go, a picture, an equation
or an embedded document becomes a visible note, and a field that shows a person's name becomes
plain text. The steps, in this order:

1. Comments: the parts (found by name, content type and relationship), the markers in the text.
2. Revision traces: every ``w:rsid*`` attribute.

Then each text part (the document, the headers, the footers, the notes), in reading order:

3. Runs that are in no paragraph (ruling R24), which the text map cannot see: what accepting or
   rejecting a block-level tracked change leaves behind.
4. Fields (ruling R22) whose result is the author, user, file name, template or a property turn
   into the plain text of their current result, so that updating the file cannot overwrite it.
5. Text kept in attributes (ruling R19): text watermarks, smart tags, custom XML tags, the items
   of list content controls, form field data, link tooltips, descriptions of tables and the
   hidden copy of a VML text box.
6. Hidden text: every run with ``w:vanish`` or ``w:specVanish``.
7. Pictures, charts, diagrams and embedded objects become a note and their parts go; equations
   (ruling R17) and embedded documents (``w:altChunk``) become a note too. Then the drawings
   that are left lose their descriptions and titles and get the names Shape1, Shape2 ... (ruling
   R19), numbered after the pictures so that a picture, which is gone, takes no number.
8. The second copy of each drawing (ruling R16): every ``mc:Fallback`` is deleted and the
   ``mc:Choice`` takes its place, so that the text of a text box exists once.

And last, the package:

9. File properties, custom XML, the glossary, the picture of the first page, printer settings and
   digital signatures; then the settings: document variables, the attached template and its
   link, mail merge, ``w:rsids`` and ``w:trackRevisions``.
10. What is left of the folders of pictures, charts, diagrams and embedded files.

A part that goes takes everything that only it used: the relationships that point at it, its own,
its Override, and the parts it relates to. A relationship goes when nothing in its part refers to
it any more. The result is a package that python-docx and ``DocxPackage.open`` read as before.

Not touched, because the plan does not name them and each is rarely there: text hidden by a
style (only the run's own properties are read), pictures that are not in the text (a page
background, a picture bullet, a theme), ActiveX controls, embedded fonts and the document
protection in the settings. A picture of those kinds that something still uses stays with its
link; one that nothing uses goes.
"""

from __future__ import annotations

import itertools
import posixpath
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import unquote

from lxml import etree

from themask.docx.package import CONTENT_TYPES, DOCUMENT, NS, RELS_NS, TYPES_NS, DocxPackage
from themask.errors import UnsupportedFileError
from themask.instruction import IMAGE_NOTE, OBJECT_NOTE

# What stands in for an equation and for an embedded document: the reader does not read the
# first (``m:t``) and cannot read the second, so neither can be masked, and both are removed.
EQUATION_NOTE = "[equation removed]"
ALTCHUNK_NOTE = "[embedded content removed]"

# The prefixes used in find() and xpath(), with the two the package leaves out.
_NAMESPACES = {
    **NS,
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "o": "urn:schemas-microsoft-com:office:office",
}


def _q(prefix: str, name: str) -> str:
    return f"{{{_NAMESPACES[prefix]}}}{name}"


# WordprocessingML.
_P, _R, _T, _RPR = _q("w", "p"), _q("w", "r"), _q("w", "t"), _q("w", "rPr")
_ID, _VAL = _q("w", "id"), _q("w", "val")
_VANISH, _SPEC_VANISH = _q("w", "vanish"), _q("w", "specVanish")
_COMMENT, _COMMENT_REFERENCE = _q("w", "comment"), _q("w", "commentReference")
_COMMENT_RANGE_START, _COMMENT_RANGE_END = _q("w", "commentRangeStart"), _q("w", "commentRangeEnd")
_FLD_SIMPLE, _FLD_CHAR, _FLD_DATA = _q("w", "fldSimple"), _q("w", "fldChar"), _q("w", "fldData")
_INSTR, _INSTR_TEXT, _FLD_CHAR_TYPE = _q("w", "instr"), _q("w", "instrText"), _q("w", "fldCharType")
_DRAWING, _PICT, _OBJECT = _q("w", "drawing"), _q("w", "pict"), _q("w", "object")
_ALT_CHUNK, _TXBX_CONTENT = _q("w", "altChunk"), _q("w", "txbxContent")
_SMART_TAG, _SMART_TAG_PR = _q("w", "smartTag"), _q("w", "smartTagPr")
_CUSTOM_XML, _CUSTOM_XML_PR = _q("w", "customXml"), _q("w", "customXmlPr")
_COMBO_BOX, _DROP_DOWN_LIST = _q("w", "comboBox"), _q("w", "dropDownList")
_LAST_VALUE, _FF_DATA = _q("w", "lastValue"), _q("w", "ffData")
_HYPERLINK, _TOOLTIP = _q("w", "hyperlink"), _q("w", "tooltip")
_TBL_CAPTION, _TBL_DESCRIPTION = _q("w", "tblCaption"), _q("w", "tblDescription")
_DATA_BINDING = _q("w", "dataBinding")
_DOC_VARS, _ATTACHED_TEMPLATE = _q("w", "docVars"), _q("w", "attachedTemplate")
_RSID, _RSIDS, _TRACK_REVISIONS = _q("w", "rsid"), _q("w", "rsids"), _q("w", "trackRevisions")
_MAIL_MERGE = _q("w", "mailMerge")
_RSID_PREFIX = _q("w", "rsid")  # w:rsidR, w:rsidRPr, w:rsidP, ...: every attribute starting so
# Drawings, VML, math and markup compatibility.
_DOC_PR, _BLIP = _q("wp", "docPr"), _q("a", "blip")
_CHART, _DIAGRAM_IDS = _q("c", "chart"), _q("dgm", "relIds")
_IMAGE_DATA, _TEXT_PATH, _SHAPE_TYPE = (
    _q("v", "imagedata"),
    _q("v", "textpath"),
    _q("v", "shapetype"),
)
_O_MATH, _O_MATH_PARA = _q("m", "oMath"), _q("m", "oMathPara")
_ALTERNATE, _CHOICE, _FALLBACK = (
    _q("mc", "AlternateContent"),
    _q("mc", "Choice"),
    _q("mc", "Fallback"),
)
_MC_WRAPPERS = frozenset({_ALTERNATE, _CHOICE, _FALLBACK})
_GFX_DATA = _q("o", "gfxdata")

# R22: the fields that show who or where the file is from. Word ignores case in a field's name.
_PERSONAL_FIELDS = frozenset(
    {
        "AUTHOR",
        "USERNAME",
        "USERINITIALS",
        "LASTSAVEDBY",
        "FILENAME",
        "TEMPLATE",
        "DOCPROPERTY",
        "INFO",
    }
)
_FIELD_NAME = re.compile(r"\s*([A-Za-z]+)\b")

# File properties (properties_cleared names them as the plan does).
_CORE_CLEARED = (
    "dc:creator",
    "cp:lastModifiedBy",
    "dc:title",
    "dc:subject",
    "cp:keywords",
    "dc:description",
    "cp:category",
    "cp:contentStatus",
)
_CORE_DATES = ("dcterms:created", "dcterms:modified")
_APP_CLEARED = ("Company", "Manager", "HyperlinkBase")
_APP_SET = (("Template", "Normal.dotm"), ("TotalTime", "0"))
# Lists in app.xml that spell out the title, the headings or the links of the file.
_APP_REMOVED = ("TitlesOfParts", "HeadingPairs", "HLinks")

# The parts of a comment: content type and relationship type end in these (without case), and
# Word names the parts word/<kind>.xml.
_COMMENT_KINDS = ("comments", "commentsExtended", "commentsIds", "commentsExtensible", "people")
_COMMENT_TYPES = tuple(f".{kind.casefold()}+xml" for kind in _COMMENT_KINDS)
_COMMENT_RELATIONSHIPS = tuple(f"/{kind.casefold()}" for kind in _COMMENT_KINDS)
_COMMENT_NAMES = frozenset(f"word/{kind.casefold()}.xml" for kind in _COMMENT_KINDS)

# Folders whose parts only the pictures, charts, diagrams and objects in the text use, so what
# no replaced element needs any more goes (media only if no relationship leads to it: a picture
# bullet or a theme may still use one).
_ALWAYS_GONE = ("word/charts/", "word/diagrams/", "word/embeddings/")
_MEDIA = "word/media/"


@dataclass
class CleanReport:
    """What ``clean`` found and took out.

    ``comments`` is the number of comments, ``images`` the pictures, charts and diagrams that
    became a note, ``objects`` the embedded objects, ``hidden_runs`` the runs of hidden text.
    ``properties_cleared`` names the file properties that held something, as ``dc:creator``,
    ``Company`` or ``custom:<name>``, and ``parts_removed`` the parts taken out of the package, in
    the order of the zip. ``fields_flattened`` counts the fields turned into plain text,
    ``fallbacks_removed`` the second copies of drawings, ``equations_removed`` and
    ``altchunks_removed`` the notes put in place of equations and embedded documents, and
    ``attributes_cleared`` the pieces of text kept in attributes that were removed: a tooltip, a
    description, a title, the name of a shape, a text watermark, a smart tag, the items of a
    list, the data of a form field or the description of a table. ``stray_runs_removed`` counts
    the runs that were in no paragraph (ruling R24).
    """

    comments: int = 0
    images: int = 0
    objects: int = 0
    hidden_runs: int = 0
    properties_cleared: list[str] = field(default_factory=list)
    parts_removed: list[str] = field(default_factory=list)
    fields_flattened: int = 0
    fallbacks_removed: int = 0
    equations_removed: int = 0
    altchunks_removed: int = 0
    attributes_cleared: int = 0
    stray_runs_removed: int = 0


def clean(pkg: DocxPackage, now: datetime | None = None) -> CleanReport:
    """Takes the hidden places out of ``pkg``, changing it, and reports what was removed.

    ``now`` is the time the file's creation and modification dates are set to, in UTC (a time
    without a zone is taken as UTC); the default is the present. A part this has to read that is
    not valid XML raises UnsupportedFileError, as asking ``pkg`` for it does: a file that cannot
    be cleaned is not passed on as clean.
    """
    report = CleanReport()
    names_before = pkg.names()
    texts = pkg.TEXT_PARTS
    main = texts[0] if texts else DOCUMENT
    used = {name: _references(pkg.xml(name)) for name in texts}  # the relationships each uses

    _remove_comments(pkg, main, texts, report)
    _strip_rsids(pkg, texts)
    shape_numbers = itertools.count(1)
    for name in texts:
        root = pkg.xml(name)
        report.stray_runs_removed += _remove_stray_runs(root)
        report.fields_flattened += _flatten_fields(root)
        report.attributes_cleared += _clear_attribute_text(root)
        report.hidden_runs += _remove_hidden_runs(root)
        _replace_pictures(root, report)
        _replace_equations(root, report)
        _replace_embedded_documents(root, report)
        # After the pictures: a picture's own name is gone and does not take a number.
        report.attributes_cleared += _anonymise_shapes(root, shape_numbers)
        for binding in list(root.iter(_DATA_BINDING)):
            _remove(binding)
        report.fallbacks_removed += _remove_fallbacks(root)
        _release(pkg, name, used[name] - _references(root))

    _clean_properties(pkg, _w3c(now), report)
    _remove_hidden_parts(pkg, main)
    _clean_settings(pkg, main)
    _sweep(pkg)
    remaining = set(pkg.names())
    report.parts_removed = [n for n in names_before if n not in remaining]
    return report


# ---- comments ---------------------------------------------------------------------------------


def _remove_comments(pkg: DocxPackage, main: str, texts: list[str], report: CleanReport) -> None:
    """Takes out the parts of the comments and their markers; counts the comments."""
    parts = _comment_parts(pkg, main)
    ids: set[str] = set()
    for name in parts:
        try:
            ids.update(c.get(_ID) for c in pkg.xml(name).iter(_COMMENT) if c.get(_ID) is not None)
        except UnsupportedFileError:
            continue  # a damaged part is going anyway; it only had the count to give
    for name in texts:
        markers = pkg.xml(name).iter(_COMMENT_RANGE_START, _COMMENT_RANGE_END, _COMMENT_REFERENCE)
        for marker in list(markers):
            if marker.get(_ID) is not None:
                ids.add(marker.get(_ID))
            parent = marker.getparent()
            parent.remove(marker)
            # The run that holds the reference is only that; if it holds text too, the text stays.
            if marker.tag == _COMMENT_REFERENCE and parent.tag == _R and _is_empty_run(parent):
                _remove(parent)
    for name in parts:
        _discard(pkg, name)
    report.comments = len(ids)


def _comment_parts(pkg: DocxPackage, main: str) -> list[str]:
    """The comments, their extensions and the people, by name, content type or relationship."""
    types = _content_types(pkg)
    related = {
        rel.part
        for rel in _relationships(pkg, main)
        if rel.part is not None and rel.type.casefold().endswith(_COMMENT_RELATIONSHIPS)
    }
    return [
        name
        for name in pkg.names()
        if name.casefold() in _COMMENT_NAMES
        or types.get(name, "").endswith(_COMMENT_TYPES)
        or name in related
    ]


# ---- revision traces ----------------------------------------------------------------------------


def _strip_rsids(pkg: DocxPackage, texts: list[str]) -> None:
    """Takes every ``w:rsid*`` attribute, and the ``w:rsid`` and ``w:rsids`` elements, out of the XML.

    They tell which editing session wrote which run: a trace of who worked on the file and when.
    The text parts are read anyway; any other XML part under word/ only when its bytes mention one.
    """
    for name in pkg.names():
        if name not in texts and not (_is_word_xml(name) and b"rsid" in pkg.raw(name)):
            continue
        root = pkg.xml(name)
        for element in root.xpath("//*[@*[starts-with(local-name(), 'rsid')]]"):
            for attribute in [a for a in element.attrib if a.startswith(_RSID_PREFIX)]:
                del element.attrib[attribute]
        for element in list(root.iter(_RSID, _RSIDS)):
            _remove(element)


def _is_word_xml(name: str) -> bool:
    """Whether ``name`` is an XML part under word/, not in the glossary, which is going."""
    key = name.casefold()
    return key.startswith("word/") and key.endswith(".xml") and not key.startswith("word/glossary/")


# ---- runs outside any paragraph (ruling R24) -----------------------------------------------------


def _remove_stray_runs(root: etree._Element) -> int:
    """Removes the runs that are not in a paragraph; returns how many.

    A block-level ``w:ins`` or ``w:del`` may hold runs straight in the body, a table, a row or a
    cell, and once the change is accepted or rejected they stay there as bare runs. The text map
    reads paragraphs only, so nobody would see such a run and nothing would mask what it says.
    This comes first, so that what a stray run holds (a picture, a field) is not counted.
    """
    count = 0
    for run in _only_live(root, root.xpath("//w:r[not(ancestor::w:p)]", namespaces=_NAMESPACES)):
        _remove(run)
        count += 1
    return count


# ---- fields (ruling R22) --------------------------------------------------------------------------


@dataclass
class _Field:
    """A complex field being read: the elements that mark it and hold its instruction."""

    begin: etree._Element
    in_instruction: bool  # begun inside the instruction of another field
    code: list[etree._Element] = field(default_factory=list)  # its w:instrText elements
    separate: etree._Element | None = None
    end: etree._Element | None = None


def _is_personal(instruction: str) -> bool:
    name = _FIELD_NAME.match(instruction)
    return name is not None and name.group(1).upper() in _PERSONAL_FIELDS


def _flatten_fields(root: etree._Element) -> int:
    """Turns the personal fields into plain text: the result stays, the field around it goes."""
    count = 0
    for simple in _live(root, _FLD_SIMPLE):
        if _is_personal(simple.get(_INSTR, "")):
            _unwrap(simple, drop=(_FLD_DATA,))
            count += 1
    stack: list[_Field] = []
    finished: list[_Field] = []
    for element in _live(root, _FLD_CHAR, _INSTR_TEXT):  # in document order
        if element.tag == _INSTR_TEXT:
            if stack and stack[-1].separate is None:
                stack[-1].code.append(element)
            continue
        kind = element.get(_FLD_CHAR_TYPE)
        if kind == "begin":
            stack.append(_Field(element, bool(stack) and stack[-1].separate is None))
        elif kind == "separate" and stack and stack[-1].separate is None:
            stack[-1].separate = element
        elif kind == "end" and stack:
            ended = stack.pop()
            ended.end = element
            finished.append(ended)
    # A field never closed is left as it is. So is one inside the instruction of another: its
    # result would become text in the middle of an instruction, which Word reads as code.
    for ended in finished:
        if ended.in_instruction or not _is_personal("".join(t.text or "" for t in ended.code)):
            continue
        for marker in (ended.begin, *ended.code, ended.separate, ended.end):
            if marker is not None:
                _remove_from_run(marker)
        count += 1
    return count


# ---- text kept in attributes (ruling R19) -----------------------------------------------------------


def _clear_attribute_text(root: etree._Element) -> int:
    """Removes the text Word keeps in attributes; returns how many pieces it removed."""
    count = _remove_text_watermarks(root)
    for wrapper in _live(root, _SMART_TAG, _CUSTOM_XML):
        _unwrap(wrapper, drop=(_SMART_TAG_PR, _CUSTOM_XML_PR))  # the attributes are in the Pr
        count += 1
    for control in _live(root, _COMBO_BOX, _DROP_DOWN_LIST):
        count += len(control) > 0 or _LAST_VALUE in control.attrib
        for item in list(control):
            control.remove(item)
        control.attrib.pop(_LAST_VALUE, None)
    for data in _live(root, _FF_DATA):
        _remove(data)
        count += 1
    for link in _live(root, _HYPERLINK):
        count += link.attrib.pop(_TOOLTIP, None) is not None
    for text in _live(root, _TBL_CAPTION, _TBL_DESCRIPTION):
        _remove(text)
        count += 1
    # Word 2007 keeps a base64 copy of a VML shape, its text included, in o:gfxdata.
    for shape in _only_live(root, root.xpath("//*[@o:gfxdata]", namespaces=_NAMESPACES)):
        del shape.attrib[_GFX_DATA]
        count += 1
    return count


def _remove_text_watermarks(root: etree._Element) -> int:
    """Removes the VML shapes that draw text from an attribute: watermarks and WordArt. No note."""
    count = 0
    for path in _live(root, _TEXT_PATH):
        shape = path.getparent()
        if shape.tag == _SHAPE_TYPE:  # the definition of a shape type draws nothing
            continue
        pict = next(shape.iterancestors(_PICT), None)
        _remove_from_run(shape if pict is None else pict)
        count += 1
    return count


def _anonymise_shapes(root: etree._Element, numbers: Iterator[int]) -> int:
    """Clears the description and title of each drawing and names it Shape<N> in reading order."""
    count = 0
    for doc_pr in _live(root, _DOC_PR):
        for attribute in ("descr", "title"):
            count += doc_pr.attrib.pop(attribute, None) is not None
        name = f"Shape{next(numbers)}"
        if doc_pr.get("name") != name:
            doc_pr.set("name", name)
            count += 1
    return count


# ---- hidden text -------------------------------------------------------------------------------------


def _remove_hidden_runs(root: etree._Element) -> int:
    """Removes the runs whose own properties hide them; a toggle set to off hides nothing."""
    count = 0
    for run in _live(root, _R):
        properties = run.find(_RPR)
        flags = (
            [] if properties is None else [properties.find(_VANISH), properties.find(_SPEC_VANISH)]
        )
        if any(flag is not None and _is_on(flag) for flag in flags):
            _remove(run)
            count += 1
    return count


def _is_on(toggle: etree._Element) -> bool:
    """Whether a property such as ``w:vanish`` is switched on: it is, unless w:val says off."""
    return toggle.get(_VAL, "true").casefold() not in {"0", "false", "off"}


# ---- pictures, objects, equations and embedded documents (ruling R17) -----------------------------------


def _replace_pictures(root: etree._Element, report: CleanReport) -> None:
    """Replaces each picture, chart, diagram and object by a note in the run it was in.

    A drawing is a picture when its own graphic holds a picture, a chart or a diagram, and a VML
    picture when it holds an image: a text box is neither, and a picture inside a text box is
    replaced alone. Objects go first, so that the preview image in one is not counted twice.
    """
    for obj in _live(root, _OBJECT):
        _replace_with_note(obj, OBJECT_NOTE)
        report.objects += 1
    for drawing in _live(root, _DRAWING):
        if _holds(drawing, _BLIP, _CHART, _DIAGRAM_IDS):
            _replace_with_note(drawing, IMAGE_NOTE)
            report.images += 1
    for pict in _live(root, _PICT):
        if _holds(pict, _IMAGE_DATA):
            _replace_with_note(pict, IMAGE_NOTE)
            report.images += 1


def _holds(shape: etree._Element, *tags: str) -> bool:
    """Whether ``shape`` has a descendant with one of these tags that is not in a text box of it."""
    for element in shape.iter(*tags):
        ancestor = element.getparent()
        while ancestor is not shape and ancestor.tag != _TXBX_CONTENT:
            ancestor = ancestor.getparent()
        if ancestor is shape:
            return True
    return False


def _replace_equations(root: etree._Element, report: CleanReport) -> None:
    """Replaces each equation (a display one, or an inline one outside it) by a note."""
    for equation in _live(root, _O_MATH_PARA, _O_MATH):  # a display equation's own ones are gone
        _replace_with_note(equation, EQUATION_NOTE)
        report.equations_removed += 1


def _replace_embedded_documents(root: etree._Element, report: CleanReport) -> None:
    """Replaces each ``w:altChunk``, which stands between paragraphs, by a paragraph with a note."""
    for chunk in _live(root, _ALT_CHUNK):
        _replace_with_note(chunk, ALTCHUNK_NOTE, paragraph=chunk.getparent().tag != _P)
        report.altchunks_removed += 1


def _replace_with_note(element: etree._Element, text: str, *, paragraph: bool = False) -> None:
    """Puts a note where ``element`` was: a ``w:t`` in the run it is in, else a new run."""
    note = element.makeelement(_T, {})
    note.text = text
    if paragraph or not _in_run(element):
        run = element.makeelement(_R, {})
        run.append(note)
        note = run
    if paragraph:
        wrapper = element.makeelement(_P, {})
        wrapper.append(note)
        note = wrapper
    element.getparent().replace(element, note)


def _in_run(element: etree._Element) -> bool:
    """Whether ``element`` is content of a run, possibly through an ``mc:AlternateContent``."""
    parent = element.getparent()
    while parent is not None and parent.tag in _MC_WRAPPERS:
        parent = parent.getparent()
    return parent is not None and parent.tag == _R


# ---- the second copy of each drawing (ruling R16) -----------------------------------------------------------


def _remove_fallbacks(root: etree._Element) -> int:
    """Deletes every ``mc:Fallback`` and puts the content of the first ``mc:Choice`` in its place."""
    removed = 0
    for alternate in list(root.iter(_ALTERNATE)):
        if not _in_tree(alternate, root):  # it was in a fallback that is gone
            continue
        for fallback in alternate.findall(_FALLBACK):
            alternate.remove(fallback)
            removed += 1
        choices = alternate.findall(_CHOICE)
        parent = alternate.getparent()
        position = parent.index(alternate)
        for child in list(choices[0]) if choices else []:  # the first is Word's first pick
            parent.insert(position, child)
            position += 1
        parent.remove(alternate)
    for stray in list(root.iter(_FALLBACK)):  # one outside an mc:AlternateContent
        _remove(stray)
        removed += 1
    return removed


# ---- file properties, custom XML, the glossary and the settings -------------------------------------------------


def _clean_properties(pkg: DocxPackage, stamp: str, report: CleanReport) -> None:
    """Empties the core and extended properties, dates them now, and removes the custom ones."""
    core = _find_part(pkg, "", "/metadata/core-properties", "docProps/core.xml")
    if core is not None:
        root = pkg.xml(core)
        for tag in _CORE_CLEARED:
            _clear(root, tag, report)
        for tag in _CORE_DATES:
            _set(root, tag, stamp, report)
    app = _find_part(pkg, "", "/extended-properties", "docProps/app.xml")
    if app is not None:
        root = pkg.xml(app)
        for tag in _APP_CLEARED:
            _clear(root, f"ep:{tag}", report, as_name=tag)
        for tag, value in _APP_SET:
            _set(root, f"ep:{tag}", value, report, as_name=tag)
        for tag in _APP_REMOVED:
            element = root.find(f"ep:{tag}", _NAMESPACES)
            if element is not None:
                _remove(element)
                report.properties_cleared.append(tag)
    custom = _find_part(pkg, "", "/custom-properties", "docProps/custom.xml")
    if custom is not None:
        try:
            names = [p.get("name") for p in pkg.xml(custom) if p.get("name")]
        except UnsupportedFileError:
            names = []  # damaged: it goes without being listed
        report.properties_cleared.extend(f"custom:{name}" for name in names)
        _discard(pkg, custom)


def _clear(
    root: etree._Element, tag: str, report: CleanReport, *, as_name: str | None = None
) -> None:
    """Empties the property ``tag``, and lists it if it held something."""
    element = root.find(tag, _NAMESPACES)
    if element is not None and element.text is not None:
        held = bool(element.text.strip())
        element.text = None
        if held:
            report.properties_cleared.append(as_name or tag)


def _set(
    root: etree._Element, tag: str, value: str, report: CleanReport, *, as_name: str | None = None
) -> None:
    """Gives the property ``tag`` this text, and lists it if that changed it."""
    element = root.find(tag, _NAMESPACES)
    if element is not None and element.text != value:
        element.text = value
        report.properties_cleared.append(as_name or tag)


def _remove_hidden_parts(pkg: DocxPackage, main: str) -> None:
    """Removes custom XML, the glossary, the picture of page one, printer settings, signatures."""
    folders = ("customxml/", "word/glossary/", "word/printersettings/", "_xmlsignatures/")
    related = (
        ("", ("/metadata/thumbnail", "/digital-signature/origin")),
        (main, ("/customxml", "/glossarydocument", "/printersettings")),
    )
    doomed = [n for n in pkg.names() if n.casefold().startswith(folders)]
    for source, suffixes in related:
        doomed += [
            rel.part
            for rel in _relationships(pkg, source)
            if rel.part is not None and rel.type.casefold().endswith(suffixes)
        ]
    for name in doomed:
        if name in pkg.names():  # it may have gone with another part
            _discard(pkg, name)


def _clean_settings(pkg: DocxPackage, main: str) -> None:
    """Removes document variables, the attached template and its link, mail merge and the rsids."""
    settings = _find_part(pkg, main, "/settings", "word/settings.xml")
    if settings is None:
        return
    root = pkg.xml(settings)
    used = _references(root)
    removed = (_DOC_VARS, _ATTACHED_TEMPLATE, _MAIL_MERGE, _RSIDS, _TRACK_REVISIONS)
    for element in list(root.iter(*removed)):
        _remove(element)
    _release(pkg, settings, used - _references(root))


def _sweep(pkg: DocxPackage) -> None:
    """Takes out what is left of the folders of pictures, charts, diagrams and embedded files."""
    for name in pkg.names():
        key = name.casefold()
        if name not in pkg.names() or _is_rels(name):  # a dependent that went already
            continue
        if key.startswith(_ALWAYS_GONE) or (key.startswith(_MEDIA) and not _referenced(pkg, name)):
            _discard(pkg, name)
    for name in pkg.names():  # relationships parts that nothing is left in
        if _is_rels(name) and name != "_rels/.rels" and _is_empty_rels(pkg, name):
            pkg.remove_part(name)


# ---- the package: relationships and parts ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Rel:
    """A relationship: its element, its id and type, and the part it leads to if the package has it."""

    element: etree._Element
    id: str
    type: str
    part: str | None


def _relationships(pkg: DocxPackage, source: str) -> list[_Rel]:
    """The relationships of part ``source`` (``""`` for the package); none if it has no .rels."""
    try:
        rels = pkg.rels_of(source)
    except KeyError:
        return []
    by_name = _by_name(pkg)
    found = []
    for element in rels.iterchildren(f"{{{RELS_NS}}}Relationship"):
        part = None
        if element.get("TargetMode") != "External":
            path = _target_path(source, element.get("Target", ""))
            part = None if path is None else by_name.get(unquote(path).casefold())
        found.append(_Rel(element, element.get("Id", ""), element.get("Type", ""), part))
    return found


def _target_path(source: str, target: str) -> str | None:
    """The name a relationship target gives, read from part ``source``; None if it names none."""
    if not target:
        return None
    path = (
        target.lstrip("/")
        if target.startswith("/")
        else posixpath.join(posixpath.dirname(source), target)
    )
    path = posixpath.normpath(path)
    return None if path in {".", ".."} or path.startswith("../") else path


def _by_name(pkg: DocxPackage) -> dict[str, str]:
    """The parts by name without case and with %-escapes decoded, as targets are matched."""
    return {unquote(name).casefold(): name for name in pkg.names()}


def _is_rels(name: str) -> bool:
    return name.endswith(".rels") and posixpath.basename(posixpath.dirname(name)) == "_rels"


def _source_of(rels_name: str) -> str:
    """The part a .rels part belongs to: ``word/document.xml`` for ``word/_rels/document.xml.rels``."""
    folder = posixpath.dirname(posixpath.dirname(rels_name))
    return posixpath.join(folder, posixpath.basename(rels_name)[: -len(".rels")])


def _is_empty_rels(pkg: DocxPackage, rels_name: str) -> bool:
    return next(pkg.xml(rels_name).iterchildren(f"{{{RELS_NS}}}Relationship"), None) is None


def _referenced(pkg: DocxPackage, name: str) -> bool:
    """Whether any relationship of any part leads to part ``name``."""
    return any(
        rel.part == name
        for rels in pkg.names()
        if _is_rels(rels)
        for rel in _relationships(pkg, _source_of(rels))
    )


def _find_part(pkg: DocxPackage, source: str, suffix: str, default: str) -> str | None:
    """The part ``source`` relates to with a type ending in ``suffix``, else ``default`` if there."""
    for rel in _relationships(pkg, source):
        if rel.part is not None and rel.type.casefold().endswith(suffix):
            return rel.part
    return default if default in pkg.names() else None


def _content_types(pkg: DocxPackage) -> dict[str, str]:
    """The content type of each part that has one, in lower case: its Override, else its Default."""
    if CONTENT_TYPES not in pkg.names():
        return {}
    table = pkg.xml(CONTENT_TYPES)
    overrides = {
        unquote(o.get("PartName", "").lstrip("/")).casefold(): o.get("ContentType", "")
        for o in table.iterchildren(f"{{{TYPES_NS}}}Override")
    }
    defaults = {
        d.get("Extension", "").casefold(): d.get("ContentType", "")
        for d in table.iterchildren(f"{{{TYPES_NS}}}Default")
    }
    types = {}
    for name in pkg.names():
        found = overrides.get(unquote(name).casefold())
        if found is None:
            extension = posixpath.basename(name).rpartition(".")[2].casefold()
            found = defaults.get(extension) if "." in posixpath.basename(name) else None
        if found is not None:
            types[name] = found.strip().casefold()
    return types


def _discard(pkg: DocxPackage, name: str) -> None:
    """Removes part ``name``, and the parts it related to that nothing else leads to.

    Worked through with a list, not by calling itself: a file may chain thousands of parts.
    """
    pending = [name]
    while pending:
        part = pending.pop()
        if part not in pkg.names():  # it went with another part
            continue
        dependents = [rel.part for rel in _relationships(pkg, part) if rel.part is not None]
        pkg.remove_part(part)
        pending += [d for d in dependents if d in pkg.names() and not _referenced(pkg, d)]


def _release(pkg: DocxPackage, part: str, ids: set[str]) -> None:
    """Drops the relationships of ``part`` named by ``ids``, and the parts left without one."""
    if not ids:
        return
    for rel in _relationships(pkg, part):
        parent = rel.element.getparent()
        if rel.id in ids and parent is not None:  # None: a part that went took it along
            parent.remove(rel.element)
            if rel.part is not None and not _referenced(pkg, rel.part):
                _discard(pkg, rel.part)


def _references(root: etree._Element) -> set[str]:
    """The relationship ids the XML refers to: r:id, r:embed, r:link, r:dm ... and o:relid."""
    ids = {str(v) for v in root.xpath("//@*[namespace-uri()=$r]", r=NS["r"])}
    return ids | {str(v) for v in root.xpath("//@o:relid", namespaces=_NAMESPACES)}


def _w3c(now: datetime | None) -> str:
    """``now`` as Word writes a date in the core properties: UTC, to the second, ending in Z."""
    moment = datetime.now(UTC) if now is None else now
    moment = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- the XML: finding, unwrapping and removing ------------------------------------------------------------------


def _live(root: etree._Element, *tags: str) -> Iterator[etree._Element]:
    """The elements with these tags that are still in ``root`` and not in a fallback copy.

    Looked at one by one, so that when the body removes one the ones inside it are not met.
    """
    return _only_live(root, root.iter(*tags))


def _only_live(
    root: etree._Element, elements: Iterable[etree._Element]
) -> Iterator[etree._Element]:
    for element in list(elements):
        if _is_live(element, root):
            yield element


def _is_live(element: etree._Element, root: etree._Element) -> bool:
    """Whether ``element`` is below ``root`` and not inside an ``mc:Fallback``."""
    for ancestor in element.iterancestors():
        if ancestor.tag == _FALLBACK:
            return False  # the copy, which is deleted whole at the end
        if ancestor is root:
            return True
    return False


def _in_tree(element: etree._Element, root: etree._Element) -> bool:
    return any(ancestor is root for ancestor in element.iterancestors())


def _is_empty_run(run: etree._Element) -> bool:
    return all(child.tag == _RPR for child in run)


def _remove(element: etree._Element) -> None:
    element.getparent().remove(element)


def _remove_from_run(element: etree._Element) -> None:
    """Removes ``element``, and the run it was in if nothing but its properties is left of it."""
    parent = element.getparent()
    parent.remove(element)
    if parent.tag == _R and _is_empty_run(parent):
        _remove(parent)


def _unwrap(element: etree._Element, drop: tuple[str, ...] = ()) -> None:
    """Replaces ``element`` by its children, except those with a tag in ``drop``."""
    parent = element.getparent()
    position = parent.index(element)
    for child in list(element):
        if child.tag not in drop:
            parent.insert(position, child)
            position += 1
    parent.remove(element)
