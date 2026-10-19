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
4. Fields (ruling R22) whose result is the author, user, file name or template, or comes from a
   property or document variable that is removed (DOCPROPERTY, INFO, TITLE, SUBJECT, KEYWORDS,
   COMMENTS, DOCVARIABLE ...), turn into the plain text of their current result, so that
   updating the file cannot replace it by an error. Everything in their instruction, a field
   inside it too, goes.
5. Text kept in attributes (ruling R19): text watermarks, smart tags, custom XML tags, the items
   of list content controls, the title and tag of a content control, form field data, link
   tooltips, descriptions of tables and the hidden copy of a VML text box.
6. Hidden text: every run with ``w:vanish`` or ``w:specVanish``, and the hyperlink or simple field
   it leaves without a run (its target or instruction would stay behind).
6a. Links to the outside (ruling R112): the AI reads text, not links, and an address behind
   "click here" reaches no review. Every ``w:hyperlink`` with a target outside the file is
   unwrapped (its text stays; a link to a place in the file stays whole), the links on shapes
   (``a:hlinkClick`` and its kin, a VML shape's ``href``) go, and so do the editing permissions
   (``w:permStart``, ``w:permEnd``, whose editor is an address), every ``w:fldData`` (field data
   Word regenerates) and, last, every ``w:author``, ``w:ed`` and ``w:edGrp`` attribute left in
   the part. The HYPERLINK, INCLUDE, INCLUDEPICTURE, INCLUDETEXT, IMPORT and LINK fields are
   flattened with step 4: their result stays, their address or path goes.
7. Pictures, charts (Word 2016's too), diagrams, ink and embedded objects become a note and their
   parts go. A drawing that holds a text box as well (ruling R28: a group of a picture and a text
   box, a text box filled with a picture) loses only the picture and the note stands beside it.
   Equations (ruling R17) and embedded documents (``w:altChunk``) become a note too. A note is a
   run of its own, with a space before it where the text before it does not end in one and a
   space after it where the text after it does not start with one (ruling R113): "Acme Supplies
   Ltd [image removed]", never "Acme Supplies Ltd[image removed]", which reads as one name. Then the
   drawings that are left lose their descriptions and titles, in a group's shapes and in VML
   shapes too, and get the names Shape1, Shape2 ... (ruling R19), numbered after the pictures so
   that a picture, which is gone, takes no number. What binds a control to custom XML and what
   names the printer settings goes as well, with the parts they name.
8. The second copy of each drawing (ruling R16): every ``mc:Fallback`` is deleted and the
   ``mc:Choice`` takes its place, so that the text of a text box exists once.

And last, the package:

9. File properties, custom XML, the glossary, the picture of the first page, printer settings and
   digital signatures; then the settings: document variables, the attached template and its
   link, mail merge, ``w:rsids`` and ``w:trackRevisions``; and the names of the theme and its
   colour, font and format schemes go back to the ones Word gives its own ("Office Theme",
   "Office"), as a template may name them after its company (ruling R66).
10. The pictures the text does not show (ruling R101): the page background, picture bullets, the
    theme's images, VML picture fills and any image left in a shape, in every XML part that
    relates to one; then every picture and media part (``word/media/``, any part whose content
    type is an image, a sound, a video or a 3D model) with every relationship to it, whatever
    still points at it. The leak check cannot read pixels, and a logo is the company's name:
    the export refuses a file in which a picture is left (``leakcheck.media_left``).
11. The namespace declarations nothing in a part uses (ruling R102): a document-assembly schema
    may be named after a party. Every prefix ``mc:Ignorable``, ``mc:MustUnderstand`` or
    ``mc:ProcessContent`` names stays declared, used or not, as Word refuses the file otherwise,
    and so does every prefix of the package's own.
12. What is left of the folders of charts, diagrams and embedded files.

A part that goes takes everything that only it used: the relationships that point at it, its own,
its Override, and the parts it relates to. A relationship goes when nothing in its part refers to
it any more. A part that the XML of some part still names by relationship id is never removed
by its folder or its relationship type, a picture or media part aside: the file must stay whole.
The result is a package that python-docx and ``DocxPackage.open`` read as before.

Not touched, because the plan does not name them and each is rarely there: text hidden by a
style (only the run's own properties are read), ActiveX controls, embedded fonts and the
document protection in the settings.
"""

from __future__ import annotations

import copy
import itertools
import posixpath
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import unquote

from lxml import etree

from themask.docx.package import CONTENT_TYPES, DOCUMENT, NS, RELS_NS, TYPES_NS, DocxPackage
from themask.errors import UnsupportedFileError
from themask.instruction import ALTCHUNK_NOTE, EQUATION_NOTE, IMAGE_NOTE, OBJECT_NOTE

__all__ = ["ALTCHUNK_NOTE", "EQUATION_NOTE", "CleanReport", "clean", "comment_parts"]

# The prefixes used in find() and xpath(), with the two the package leaves out.
_NAMESPACES = {
    **NS,
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "o": "urn:schemas-microsoft-com:office:office",
    "cx": "http://schemas.microsoft.com/office/drawing/2014/chartex",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "am3d": "http://schemas.microsoft.com/office/drawing/2017/model3d",
}


def _q(prefix: str, name: str) -> str:
    return f"{{{_NAMESPACES[prefix]}}}{name}"


# WordprocessingML.
_P, _R, _T, _RPR = _q("w", "p"), _q("w", "r"), _q("w", "t"), _q("w", "rPr")
_XML_SPACE = _q("xml", "space")
# What a paragraph shows, for the spacing of a note: its texts, and these characters.
_SHOWN_TEXTS = frozenset({_T, _q("w", "instrText")})
_SHOWN_CHARACTERS = {
    _q("w", "tab"): "\t",
    _q("w", "ptab"): "\t",
    _q("w", "br"): "\n",
    _q("w", "cr"): "\n",
    _q("w", "noBreakHyphen"): "\N{NON-BREAKING HYPHEN}",
}
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
_PERM_START, _PERM_END = _q("w", "permStart"), _q("w", "permEnd")
_AUTHOR, _ED, _ED_GRP = _q("w", "author"), _q("w", "ed"), _q("w", "edGrp")
_SHAPE_LINKS = tuple(_q("a", name) for name in ("hlinkClick", "hlinkHover", "hlinkMouseOver"))
_VML_LINKS = ("href", _q("o", "href"), _q("o", "hrlabel"))
_TBL_CAPTION, _TBL_DESCRIPTION = _q("w", "tblCaption"), _q("w", "tblDescription")
_DATA_BINDING, _W15_DATA_BINDING = _q("w", "dataBinding"), _q("w15", "dataBinding")
_PRINTER_SETTINGS = _q("w", "printerSettings")
_ALIAS, _TAG = _q("w", "alias"), _q("w", "tag")
_DOC_VARS, _ATTACHED_TEMPLATE = _q("w", "docVars"), _q("w", "attachedTemplate")
_RSID, _RSIDS, _TRACK_REVISIONS = _q("w", "rsid"), _q("w", "rsids"), _q("w", "trackRevisions")
_MAIL_MERGE = _q("w", "mailMerge")
_RSID_PREFIX = _q("w", "rsid")  # w:rsidR, w:rsidRPr, w:rsidP, ...: every attribute starting so
# Drawings, VML, math and markup compatibility.
_DOC_PR, _BLIP = _q("wp", "docPr"), _q("a", "blip")
_PIC, _BLIP_FILL, _NO_FILL = _q("pic", "pic"), _q("a", "blipFill"), _q("a", "noFill")
_CHART, _DIAGRAM_IDS = _q("c", "chart"), _q("dgm", "relIds")
_CHART_EX, _INK, _MODEL3D = _q("cx", "chart"), _q("w14", "contentPart"), _q("am3d", "model3d")
# What makes a drawing a picture: a picture or a picture fill, a chart (Word 2016's too), a
# diagram, a stroke of ink, a 3D model.
_DRAWING_PIECES = (_BLIP, _CHART, _CHART_EX, _DIAGRAM_IDS, _INK, _MODEL3D)
_IMAGE_DATA, _TEXT_PATH, _SHAPE_TYPE = (
    _q("v", "imagedata"),
    _q("v", "textpath"),
    _q("v", "shapetype"),
)
_TEXTBOX = _q("v", "textbox")
_O_MATH, _O_MATH_PARA = _q("m", "oMath"), _q("m", "oMathPara")
_ALTERNATE, _CHOICE, _FALLBACK = (
    _q("mc", "AlternateContent"),
    _q("mc", "Choice"),
    _q("mc", "Fallback"),
)
_MC_WRAPPERS = frozenset({_ALTERNATE, _CHOICE, _FALLBACK})
_GFX_DATA = _q("o", "gfxdata")

# R22: the fields that show who or where the file is from (author, user, file name, template) and
# those that read a property or a document variable the cleaner removes. Updating one in the
# masked file would put an error or nothing where the masked result stands, so each becomes the
# plain text of its result. And the fields whose instruction is an address or a path outside
# the file (ruling R112): their result stays, the address goes. Word ignores case in a field's
# name.
_FLATTENED_FIELDS = frozenset(
    {
        "AUTHOR",
        "USERNAME",
        "USERINITIALS",
        "USERADDRESS",
        "LASTSAVEDBY",
        "FILENAME",
        "TEMPLATE",
        "DOCPROPERTY",
        "INFO",
        "TITLE",
        "SUBJECT",
        "KEYWORDS",
        "COMMENTS",
        "DOCVARIABLE",
        "HYPERLINK",
        "INCLUDEPICTURE",
        "INCLUDETEXT",
        "INCLUDE",
        "IMPORT",
        "LINK",
    }
)
_FIELD_NAME = re.compile(r"\s*([A-Za-z]+)\b")
# Where a drawing keeps its description, title and name: wp:docPr, and cNvPr in a group's shapes.
_SHAPE_PROPERTIES = "//wp:docPr | //*[local-name()='cNvPr']"

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
    "dc:identifier",
    "cp:version",
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

# Folders whose parts only the charts, diagrams and objects in the text use, so what no replaced
# element needs any more goes. Not a part the XML still refers to, though (the file must stay
# whole). The pictures go whatever refers to them (ruling R101).
_ALWAYS_GONE = ("word/charts/", "word/diagrams/", "word/embeddings/")
_MEDIA = "word/media/"


@dataclass
class CleanReport:
    """What ``clean`` found and took out.

    ``comments`` is the number of comments, ``images`` the pictures, charts, diagrams and 3D
    models that became a note and the pictures taken out where the text does not show them (the
    page background, picture bullets, the theme's images, VML picture fills; ruling R101),
    ``objects`` the embedded objects, ``hidden_runs`` the runs of hidden text.
    ``properties_cleared`` names the file properties that held something, as ``dc:creator``,
    ``Company`` or ``custom:<name>``, and ``parts_removed`` the parts taken out of the package, in
    the order of the zip. ``fields_flattened`` counts the fields turned into plain text,
    ``links_removed`` the links to the outside taken out, a link round text, a link on a shape
    or a VML shape's link (ruling R112), ``fallbacks_removed`` the second copies of drawings,
    ``equations_removed`` and
    ``altchunks_removed`` the notes put in place of equations and embedded documents, and
    ``attributes_cleared`` the pieces of text kept in attributes that were removed: a tooltip, a
    description, a title, the name of a shape, a text watermark, a smart tag, the items of a
    list, the title or tag of a content control, the data of a form field or the description of a
    table (also the alt text of the shapes of a group and of VML shapes), or the name of the
    theme or of one of its schemes, given back Word's own. ``stray_runs_removed`` counts the runs
    that were in no paragraph (ruling R24).
    """

    comments: int = 0
    images: int = 0
    objects: int = 0
    hidden_runs: int = 0
    properties_cleared: list[str] = field(default_factory=list)
    parts_removed: list[str] = field(default_factory=list)
    fields_flattened: int = 0
    links_removed: int = 0
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
        report.links_removed += _remove_external_links(root)
        report.attributes_cleared += _remove_editing_marks(root)
        _replace_pictures(root, report)
        _replace_equations(root, report)
        _replace_embedded_documents(root, report)
        # After the pictures: a picture's own name is gone and does not take a number.
        report.attributes_cleared += _anonymise_shapes(root, shape_numbers)
        _remove_links_to_parts(root)
        report.fallbacks_removed += _remove_fallbacks(root)
        _release(pkg, name, used[name] - _references(root))

    _clean_properties(pkg, _w3c(now), report)
    _remove_hidden_parts(pkg, main)
    _clean_settings(pkg, main)
    report.attributes_cleared += _reset_theme_names(pkg, main)
    _remove_media(pkg, main, texts, report)
    _strip_unused_namespaces(pkg)
    _sweep(pkg)
    remaining = set(pkg.names())
    report.parts_removed = [n for n in names_before if n not in remaining]
    return report


# ---- comments ------------------------------------------------------------------------------------


def _remove_comments(pkg: DocxPackage, main: str, texts: list[str], report: CleanReport) -> None:
    """Takes out the parts of the comments and their markers; counts the comments."""
    parts = comment_parts(pkg, main)
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


def comment_parts(pkg: DocxPackage, main: str) -> list[str]:
    """The comments, their extensions and the people, by name, content type or relationship.

    ``main`` is the main document, whose relationships lead to them. The restore walks the same
    parts as the cleaner removes.
    """
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


# ---- revision traces -----------------------------------------------------------------------------


def _strip_rsids(pkg: DocxPackage, texts: list[str]) -> None:
    """Takes every ``w:rsid*`` attribute, and the ``w:rsid`` and ``w:rsids`` elements, out.

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


def _remove_links_to_parts(root: etree._Element) -> None:
    """Removes what binds a control to custom XML and what names the printer settings.

    Their parts go too, and an element that names a part that is gone would be left dangling.
    """
    for element in list(root.iter(_DATA_BINDING, _W15_DATA_BINDING, _PRINTER_SETTINGS)):
        _remove(element)


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


# ---- fields (ruling R22) -------------------------------------------------------------------------


@dataclass
class _Field:
    """A complex field being read: the elements that mark it and hold its instruction."""

    begin: etree._Element
    in_instruction: bool  # begun inside the instruction of another field
    code: list[etree._Element] = field(default_factory=list)  # its w:instrText elements
    separate: etree._Element | None = None


def _is_flattened(instruction: str) -> bool:
    name = _FIELD_NAME.match(instruction)
    return name is not None and name.group(1).upper() in _FLATTENED_FIELDS


def _flatten_fields(root: etree._Element) -> int:
    """Turns the fields listed in ``_FLATTENED_FIELDS`` into their result as plain text.

    The result stays; the markers and the whole instruction go.
    """
    count = 0
    for simple in _live(root, _FLD_SIMPLE):
        if _is_flattened(simple.get(_INSTR, "")):
            _unwrap(simple, drop=(_FLD_DATA,))
            count += 1
    runs = list(_live(root, _R))
    position = {run: index for index, run in enumerate(runs)}
    stack: list[_Field] = []
    finished: list[tuple[_Field, etree._Element]] = []  # each with the element that ended it
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
            finished.append((stack.pop(), element))
    # A field never closed is left as it is. So is one inside the instruction of another: its
    # result would become text in the middle of an instruction, which Word reads as code.
    for ended, end in finished:
        if ended.in_instruction or not _is_flattened("".join(t.text or "" for t in ended.code)):
            continue
        # The instruction is everything from begin to separate (to end, if there is no result):
        # a field in it, with its result, goes too instead of turning into text of the paragraph.
        stop = end if ended.separate is None else ended.separate
        first, last = position.get(ended.begin.getparent()), position.get(stop.getparent())
        if first is not None and last is not None:
            for run in runs[first + 1 : last]:
                _remove(run)
        for marker in (ended.begin, *ended.code, ended.separate, end):
            if marker is not None:
                _remove_from_run(marker)
        count += 1
    return count


# ---- text kept in attributes (ruling R19) --------------------------------------------------------


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
    # The title and the tag of a content control are free text: a system that assembles the
    # contract may fill them with a value. The control, its id and its content stay.
    for label in _live(root, _ALIAS, _TAG):  # w:alias and w:tag exist in w:sdtPr only
        _remove(label)
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
    """Clears the description and title of each drawing and names it Shape<N> in reading order.

    The properties of a drawing are ``wp:docPr``, and for the shapes of a group ``wps:cNvPr`` and
    its like; a VML shape keeps its alt text and title in its own attributes.
    """
    count = 0
    for properties in _only_live(root, root.xpath(_SHAPE_PROPERTIES, namespaces=_NAMESPACES)):
        for attribute in ("descr", "title"):
            count += properties.attrib.pop(attribute, None) is not None
        name = f"Shape{next(numbers)}"
        if properties.get("name") != name:
            properties.set("name", name)
            count += 1
    for shape in _only_live(root, root.xpath("//v:*[@alt or @title]", namespaces=_NAMESPACES)):
        for attribute in ("alt", "title"):
            count += shape.attrib.pop(attribute, None) is not None
    return count


# ---- hidden text ---------------------------------------------------------------------------------


def _remove_hidden_runs(root: etree._Element) -> int:
    """Removes the runs whose own properties hide them; a toggle set to off hides nothing."""
    count = 0
    for run in _live(root, _R):
        properties = run.find(_RPR)
        flags = (
            [] if properties is None else [properties.find(_VANISH), properties.find(_SPEC_VANISH)]
        )
        if any(flag is not None and _is_on(flag) for flag in flags):
            parent = run.getparent()
            _remove(run)
            count += 1
            _unwrap_emptied_links(parent)
    return count


def _unwrap_emptied_links(element: etree._Element | None) -> None:
    """Unwraps the hyperlinks and simple fields that no longer hold a run, from ``element`` up.

    Their target or instruction would stay: a hidden address is a link in Word, and the link
    outlives the hidden text it was made of.
    """
    while (
        element is not None
        and element.tag in (_HYPERLINK, _FLD_SIMPLE)
        and next(element.iter(_R), None) is None
    ):
        parent = element.getparent()
        _unwrap(element, drop=(_FLD_DATA,))
        element = parent


def _is_on(toggle: etree._Element) -> bool:
    """Whether a property such as ``w:vanish`` is switched on: it is, unless w:val says off."""
    return toggle.get(_VAL, "true").casefold() not in {"0", "false", "off"}


# ---- links to the outside (ruling R112) ----------------------------------------------------------


def _remove_external_links(root: etree._Element) -> int:
    """Takes out every link to the outside; returns how many. The text of a link stays.

    A ``w:hyperlink`` with a relationship (a web page, an e-mail address, a file) is unwrapped;
    one that only leads to a place in the file (``w:anchor``) stays as it is. The links on
    drawings (``a:hlinkClick``, ``a:hlinkHover``, ``a:hlinkMouseOver``) go, and a VML shape
    loses its ``href`` and its label. The relationships they named are released afterwards,
    once nothing in the part refers to them.
    """
    count = 0
    for link in _live(root, _HYPERLINK):
        if _R_ID in link.attrib:
            _unwrap(link)
            count += 1
    for shape_link in _live(root, *_SHAPE_LINKS):
        _remove(shape_link)
        count += 1
    linked = root.xpath("//v:*[@href or @o:href or @o:hrlabel]", namespaces=_NAMESPACES)
    for shape in _only_live(root, linked):
        for attribute in _VML_LINKS:
            shape.attrib.pop(attribute, None)
        count += 1
    return count


def _remove_editing_marks(root: etree._Element) -> int:
    """Takes out the editing permissions, the field data and every author left in the part;
    returns how many pieces of text kept in attributes went.

    A permission range (``w:permStart``/``w:permEnd``, Word's "Restrict Editing") names its
    editor, an e-mail address; ``w:fldData`` is field data in base64, which Word regenerates;
    and a ``w:author``, ``w:ed`` or ``w:edGrp`` attribute on anything left names a person: the
    tracked changes are resolved by now, so one left is a co-authoring mark or something Word
    adds next year.
    """
    count = 0
    for mark in _live(root, _PERM_START, _PERM_END):
        count += mark.get(_ED) is not None
        _remove(mark)
    for data in _live(root, _FLD_DATA):
        _remove(data)
    marked = root.xpath("//*[@w:author or @w:ed or @w:edGrp]", namespaces=_NAMESPACES)
    for element in _only_live(root, marked):
        for attribute in (_AUTHOR, _ED, _ED_GRP):
            count += element.attrib.pop(attribute, None) is not None
    return count


# ---- pictures, objects, equations and embedded documents (ruling R17) ----------------------------


def _replace_pictures(root: etree._Element, report: CleanReport) -> None:
    """Replaces each picture, chart, diagram, ink drawing and object by a note.

    Objects go first, so that the preview image in one is not counted twice. A drawing is a picture
    when its own graphic holds a picture, a chart or a diagram, and a VML drawing when it holds an
    image; what a text box of it holds is looked at in its turn.
    """
    for obj in _live(root, _OBJECT):
        _replace_with_note(obj, OBJECT_NOTE)
        report.objects += 1
    for drawing in _live(root, _DRAWING):
        if _holds(drawing, *_DRAWING_PIECES):
            _replace_picture(drawing, _DRAWING_PIECES, _strip_drawing_picture)
            report.images += 1
    for pict in _live(root, _PICT):
        if _holds(pict, _IMAGE_DATA):
            _replace_picture(pict, (_IMAGE_DATA,), _strip_vml_picture)
            report.images += 1


def _replace_picture(
    shape: etree._Element, pieces: tuple[str, ...], strip: Callable[[etree._Element], None]
) -> None:
    """Puts a note for the picture in ``shape``.

    A drawing that is only a picture is replaced whole. One that holds a text box as well (a group
    of a picture and a text box, a text box filled with a picture) loses only the picture and the
    note stands beside it: the text in the box is visible text, to be read and masked.
    """
    if _holds(shape, _TXBX_CONTENT):
        strip(shape)
        if not _holds(shape, *pieces):
            _add_note_after(shape, IMAGE_NOTE)
            return
    # Nothing but the picture, or a kind of picture that cannot be taken out of the drawing.
    _replace_with_note(shape, IMAGE_NOTE)


def _strip_drawing_picture(drawing: etree._Element) -> None:
    """Takes the pictures out of a drawing: ``pic:pic`` goes, a picture fill becomes no fill."""
    for picture in list(_own(drawing, _PIC)):
        _remove(picture)
    for fill in list(_own(drawing, _BLIP_FILL)):
        fill.getparent().replace(fill, fill.makeelement(_NO_FILL, {}))


def _strip_vml_picture(pict: etree._Element) -> None:
    """Takes the images out of a VML drawing: each image's shape, or just the image of a box."""
    for data in list(_own(pict, _IMAGE_DATA)):
        shape = data.getparent()
        if shape is pict or shape.find(_TEXTBOX) is not None:
            _remove(data)
        else:
            _remove(shape)


def _own(shape: etree._Element, *tags: str) -> Iterator[etree._Element]:
    """The descendants of ``shape`` with one of these tags that are not in a text box of it."""
    for element in shape.iter(*tags):
        ancestor = element.getparent()
        while ancestor is not shape and ancestor.tag != _TXBX_CONTENT:
            ancestor = ancestor.getparent()
        if ancestor is shape:
            yield element


def _holds(shape: etree._Element, *tags: str) -> bool:
    return next(_own(shape, *tags), None) is not None


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
    """Puts a note where ``element`` was: a run of its own (a paragraph of its own if asked)."""
    if paragraph:
        wrapper = element.makeelement(_P, {})
        wrapper.append(_note(element, text))
        element.getparent().replace(element, wrapper)
        return
    _put_note(element, _note(element, text), keep=False)


def _add_note_after(element: etree._Element, text: str) -> None:
    """Puts a note beside ``element``, which stays."""
    _put_note(element, _note(element, text), keep=True)


def _note(element: etree._Element, text: str) -> etree._Element:
    """A run holding the note ``text``, with a space before it where the paragraph's text before
    ``element`` does not end in one and a space after it where the text after ``element`` does
    not start with one (ruling R113)."""
    before, after = _text_around(element)
    run = element.makeelement(_R, {})
    if before and not before[-1].isspace():
        _add_text(run, " ")
    _add_text(run, text)
    if after and not after[0].isspace():
        _add_text(run, " ")
    return run


def _add_text(run: etree._Element, text: str) -> None:
    node = etree.SubElement(run, _T)
    node.text = text
    if text != text.strip():
        node.set(_XML_SPACE, "preserve")


def _put_note(element: etree._Element, note: etree._Element, *, keep: bool) -> None:
    """Puts the run ``note`` right after ``element``'s place, as a run of its own, and takes
    ``element`` out unless ``keep``.

    When ``element`` is content of a run (through an ``mc:AlternateContent`` or not), the run is
    cut there: what follows ``element`` in it goes into a run of its own with the same
    properties, and a run left with nothing but its properties goes. An ``mc:AlternateContent``
    stays for ``_remove_fallbacks``, which counts its second copy.
    """
    run = _run_of(element)
    if run is None:
        if keep:
            element.addnext(note)
        else:
            element.getparent().replace(element, note)
        return
    top = element
    while top.getparent() is not run:
        top = top.getparent()
    following = [child for child in run if run.index(child) > run.index(top)]
    run.addnext(note)
    if following:
        tail = run.makeelement(_R, {})
        properties = run.find(_RPR)
        if properties is not None:
            tail.append(copy.deepcopy(properties))
        tail.extend(following)
        note.addnext(tail)
    if not keep:
        element.getparent().remove(element)
        if _is_empty_run(run):
            _remove(run)


def _run_of(element: etree._Element) -> etree._Element | None:
    """The run ``element`` is content of, possibly through an ``mc:AlternateContent``."""
    parent = element.getparent()
    while parent is not None and parent.tag in _MC_WRAPPERS:
        parent = parent.getparent()
    return parent if parent is not None and parent.tag == _R else None


def _text_around(element: etree._Element) -> tuple[str, str]:
    """The text of ``element``'s paragraph before it and after it, as the reader shows it;
    nothing on either side when it is in no paragraph."""
    paragraph = next(element.iterancestors(_P), None)
    if paragraph is None:
        return "", ""
    before: list[str] = []
    after: list[str] = []
    pieces = before
    for node in paragraph.iter():
        if node is element:
            pieces = after
            continue
        if node.tag not in _SHOWN_TEXTS and node.tag not in _SHOWN_CHARACTERS:
            continue
        ancestors = list(node.iterancestors())
        # What is inside the element goes with it; a fallback copy and the paragraphs of a text
        # box are not this paragraph's text, as the reader reads it.
        if (pieces is after and element in ancestors) or any(
            a.tag == _FALLBACK or (a.tag == _P and a is not paragraph) for a in ancestors
        ):
            continue
        pieces.append(node.text or "" if node.tag in _SHOWN_TEXTS else _SHOWN_CHARACTERS[node.tag])
    return "".join(before), "".join(after)


# ---- the second copy of each drawing (ruling R16) ------------------------------------------------


def _remove_fallbacks(root: etree._Element) -> int:
    """Deletes every ``mc:Fallback``; the first ``mc:Choice`` takes the place of its container."""
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


# ---- file properties, custom XML, the glossary and the settings ----------------------------------


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
    """Blanks every property ``tag`` and what is in it; lists it if it held something."""
    held = False
    for element in root.findall(tag, _NAMESPACES):
        held = held or bool("".join(element.itertext()).strip())
        for child in list(element):  # keywords may hold cp:value elements
            element.remove(child)
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
    """Removes custom XML, the glossary, the picture of page one, printer settings, signatures.

    Not a part the XML of some part still names by relationship id: the file must stay whole.
    """
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
    named = _xml_references(pkg)
    for name in doomed:
        if name in pkg.names() and not _named_by_xml(pkg, name, named):
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


# The names Word gives its own theme and its schemes (ruling R66).
_THEME, _THEME_NAME = _q("a", "theme"), "Office Theme"
_SCHEMES = tuple(_q("a", name) for name in ("clrScheme", "fontScheme", "fmtScheme"))
_SCHEME_NAME = "Office"


def _reset_theme_names(pkg: DocxPackage, main: str) -> int:
    """Gives the document's theme and its colour, font and format schemes the names Word gives
    its own; returns how many names changed."""
    theme = _find_part(pkg, main, "/theme", "word/theme/theme1.xml")
    if theme is None:
        return 0
    root = pkg.xml(theme)
    if root.tag != _THEME:
        return 0
    changed = 0
    for element, name in [(root, _THEME_NAME), *((s, _SCHEME_NAME) for s in root.iter(*_SCHEMES))]:
        if element.get("name") not in (None, name):
            element.set("name", name)
            changed += 1
    return changed


def _sweep(pkg: DocxPackage) -> None:
    """Takes out what is left of the folders of charts, diagrams and embedded files, and of the
    pictures' folder (``_remove_media`` emptied it already)."""
    named = _xml_references(pkg)
    for name in pkg.names():
        key = name.casefold()
        if name not in pkg.names() or _is_rels(name):  # a dependent that went already
            continue
        swept = key.startswith(_ALWAYS_GONE) and not _named_by_xml(pkg, name, named)
        if swept or key.startswith(_MEDIA):
            _discard(pkg, name)
    for name in pkg.names():  # relationships parts that nothing is left in
        if _is_rels(name) and name != "_rels/.rels" and _is_empty_rels(pkg, name):
            pkg.remove_part(name)


# ---- pictures that are not in the text (ruling R101) ---------------------------------------------

# The relationship types and the content types of pictures and media, compared without case: what
# the leak check cannot read, so none may be left in a masked copy.
MEDIA_RELATIONSHIPS = ("/image", "/audio", "/video", "/media", "/model", "/model3d")
MEDIA_TYPES = ("image/", "audio/", "video/", "model/")
_BACKGROUND = _q("w", "background")
_NUM_PIC_BULLET, _LVL_PIC_BULLET_ID = _q("w", "numPicBullet"), _q("w", "lvlPicBulletId")
_V_FILL, _R_ID = _q("v", "fill"), _q("r", "id")
_SOLID_FILL, _SCHEME_CLR = _q("a", "solidFill"), _q("a", "schemeClr")


def _remove_media(pkg: DocxPackage, main: str, texts: list[str], report: CleanReport) -> None:
    """Takes the pictures the text does not show out of the XML, then every picture and media
    part out of the package, with every relationship to it, whatever still points at it.

    The pictures in the text became notes already. Here every XML part that relates to a
    picture (and the text parts, the numbering and the theme in any case) loses the page
    background, its picture bullets, the theme's images, its VML picture fills and any image
    left in a shape; what those referred to is released, so that no reference dangles. Then the
    parts go: the parts under ``word/media/`` and every part whose content type is an image, a
    sound, a video or a 3D model.
    """
    types = _content_types(pkg)
    always = [
        *texts,
        _find_part(pkg, main, "/numbering", "word/numbering.xml"),
        _find_part(pkg, main, "/theme", "word/theme/theme1.xml"),
    ]
    for name in pkg.names():
        if not _is_xml_part(name) or not (name in always or _relates_to_media(pkg, name)):
            continue
        root = pkg.xml(name)
        used = _references(root)
        report.images += _strip_pictures(root, in_theme=root.tag == _THEME)
        _release(pkg, name, used - _references(root))
    for name in pkg.names():
        if name.casefold().startswith(_MEDIA) or types.get(name, "").startswith(MEDIA_TYPES):
            _discard(pkg, name)


def _is_xml_part(name: str) -> bool:
    return name.casefold().endswith(".xml") and name != CONTENT_TYPES


def _relates_to_media(pkg: DocxPackage, name: str) -> bool:
    """Whether part ``name`` has a relationship to a picture or a media file."""
    return any(
        rel.type.casefold().endswith(MEDIA_RELATIONSHIPS) for rel in _relationships(pkg, name)
    )


def _strip_pictures(root: etree._Element, *, in_theme: bool) -> int:
    """Takes out of ``root`` what shows a picture outside the text; returns how many pictures.

    The page background goes whole (a picture or a colour, it is the page's, not the text's);
    a picture bullet goes with the levels that use it; a VML fill loses its picture and is a
    plain fill; an image left in a VML shape goes with the shape (with the image alone when the
    shape is a text box); a picture fill becomes no fill, or in the theme a solid fill in the
    placeholder colour, which the theme's fill style lists need three of.
    """
    count = 0
    for background in list(root.iter(_BACKGROUND)):
        count += bool(_references(background))
        _remove(background)
    for bullet in list(root.iter(_NUM_PIC_BULLET)):
        _remove(bullet)
        count += 1
    for level in list(root.iter(_LVL_PIC_BULLET_ID)):
        _remove(level)
    for fill in root.iter(_V_FILL):
        count += fill.attrib.pop(_R_ID, None) is not None
    for data in list(root.iter(_IMAGE_DATA)):
        shape = data.getparent()
        _remove(data if shape.find(_TEXTBOX) is not None else shape)
        count += 1
    for blip in list(root.iter(_BLIP)):
        holder = blip.getparent()
        if holder.tag.endswith("}blipFill"):
            picture = holder.getparent()
            if picture.tag == _PIC:
                _remove(picture)
            else:
                picture.replace(holder, _plain_fill(holder, in_theme))
        else:  # a:buBlip, the picture of a DrawingML bullet
            _remove(holder)
        count += 1
    return count


def _plain_fill(fill: etree._Element, in_theme: bool) -> etree._Element:
    if not in_theme:
        return fill.makeelement(_NO_FILL, {})
    solid = fill.makeelement(_SOLID_FILL, {})
    etree.SubElement(solid, _SCHEME_CLR, {"val": "phClr"})
    return solid


# ---- namespace declarations (ruling R102) --------------------------------------------------------

# The markup-compatibility attributes that name prefixes, which must stay declared.
_MC_PREFIX_LISTS = tuple(
    _q("mc", name) for name in ("Ignorable", "MustUnderstand", "ProcessContent")
)


def _strip_unused_namespaces(pkg: DocxPackage) -> None:
    """Takes the namespace declarations nothing uses out of every XML part.

    Kept whether used or not: the prefixes any ``mc:Ignorable``, ``mc:MustUnderstand`` or
    ``mc:ProcessContent`` attribute of the part names (Word and python-docx write
    ``mc:Ignorable="w14 wp14"``, and Word refuses a file whose ignorable prefix is undeclared),
    and the prefixes of the package's own namespaces.
    """
    for name in pkg.names():
        if not _is_xml_part(name) or _is_rels(name):
            continue
        root = pkg.xml(name)
        keep = set(NS)
        for element in root.iter(etree.Element):
            for attribute in _MC_PREFIX_LISTS:
                for item in element.get(attribute, "").split():
                    keep.add(item.partition(":")[0])
        etree.cleanup_namespaces(root, keep_ns_prefixes=sorted(keep))


# ---- the package: relationships and parts --------------------------------------------------------


@dataclass(frozen=True)
class _Rel:
    """A relationship: its element, id and type, and the part it leads to if the package has it."""

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
    """The part a .rels part belongs to: word/document.xml for word/_rels/document.xml.rels."""
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


def _xml_references(pkg: DocxPackage) -> dict[str, set[str]]:
    """For each XML part that has relationships: the relationship ids its XML names."""
    named: dict[str, set[str]] = {}
    for rels in pkg.names():
        source = _source_of(rels) if _is_rels(rels) else ""
        if source in pkg.names() and source.casefold().endswith(".xml"):
            try:
                named[source] = _references(pkg.xml(source))
            except UnsupportedFileError:
                continue  # damaged: it names nothing that can be read
    return named


def _named_by_xml(pkg: DocxPackage, name: str, named: dict[str, set[str]]) -> bool:
    """Whether the XML of some part refers, by relationship id, to part ``name``."""
    for rels in pkg.names():
        if _is_rels(rels):
            source = _source_of(rels)
            if any(
                r.part == name and r.id in named.get(source, ())
                for r in _relationships(pkg, source)
            ):
                return True
    return False


def _find_part(pkg: DocxPackage, source: str, suffix: str, default: str) -> str | None:
    """The part ``source`` relates to by a type ending in ``suffix``, else ``default`` if any."""
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


# ---- the XML: finding, unwrapping and removing ---------------------------------------------------


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
    """Removes ``element`` from its parent; one already taken out (with what held it) is left."""
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _remove_from_run(element: etree._Element) -> None:
    """Removes ``element``, and the run it was in if nothing but its properties is left of it."""
    parent = element.getparent()
    if parent is None:
        return
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
