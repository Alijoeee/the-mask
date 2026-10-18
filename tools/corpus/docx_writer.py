"""Writing a contract as a Word file, with the features real Word files have.

python-docx makes the package: styles, the section, headers and footers, pictures, comments and
the core properties. What it has no API for is written as WordprocessingML with lxml, the way Word
itself writes it: tracked insertions and deletions, footnotes, a text box (with Word's VML
fallback), the PAGE field, hyperlinks, lettered lists, custom properties, and the attached
template and document variables in the settings. The zip is written with fixed timestamps, so the
same contract always gives the same bytes.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from xml.sax.saxutils import escape

import docx
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part, XmlPart
from docx.oxml.ns import nsdecls, qn
from docx.oxml.parser import OxmlElement, parse_xml
from docx.shared import Cm, Emu, Pt, RGBColor
from docx.text.paragraph import Paragraph as DocxParagraph
from docx.text.run import Run
from lxml import etree

from tools.corpus.long import word_count
from tools.corpus.model import (
    Block,
    ContractSpec,
    FootnoteRef,
    Image,
    Inline,
    PageBreak,
    Paragraph,
    Span,
    Table,
    TextBox,
)

_ATTACHED_TEMPLATE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate"
)
_ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_LETTERED_LIST_ID = "90"  # the abstract numbering this writer adds for (a), (b), (c) lists
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)  # the date Word itself gives every entry of a .docx
_TWIPS_PER_CM = 567

_LETTERED_LIST = (
    f'<w:abstractNum {nsdecls("w")} w:abstractNumId="{_LETTERED_LIST_ID}">'
    '<w:multiLevelType w:val="singleLevel"/>'
    '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/>'
    '<w:lvlText w:val="(%1)"/><w:lvlJc w:val="left"/>'
    '<w:pPr><w:ind w:left="1418" w:hanging="425"/></w:pPr></w:lvl>'
    "</w:abstractNum>"
)
_FOOTNOTES = (
    f"<w:footnotes {nsdecls('w', 'r')}>"
    '<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr>'
    '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
    "<w:r><w:separator/></w:r></w:p></w:footnote>"
    '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr>'
    '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
    "<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>"
    "</w:footnotes>"
)
# The namespaces of a text box that python-docx has no prefix for.
_BOX_NAMESPACES = " ".join(
    f'xmlns:{prefix}="{uri}"'
    for prefix, uri in (
        ("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006"),
        ("wps", "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"),
        ("v", "urn:schemas-microsoft-com:vml"),
        ("o", "urn:schemas-microsoft-com:office:office"),
        ("w10", "urn:schemas-microsoft-com:office:word"),
    )
)
# A text box as Word 2010 and later save it: DrawingML for current Word, VML for older readers.
_TEXT_BOX = (
    f"<mc:AlternateContent {nsdecls('w', 'wp', 'a')} {_BOX_NAMESPACES}>"
    '<mc:Choice Requires="wps"><w:drawing>'
    '<wp:anchor distT="45720" distB="45720" distL="114300" distR="114300" simplePos="0"'
    ' relativeHeight="251659264" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
    '<wp:simplePos x="0" y="0"/>'
    '<wp:positionH relativeFrom="margin"><wp:align>right</wp:align></wp:positionH>'
    '<wp:positionV relativeFrom="paragraph"><wp:posOffset>45720</wp:posOffset></wp:positionV>'
    '<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
    '<wp:wrapSquare wrapText="bothSides"/><wp:docPr id="{id}" name="Text Box {id}"/>'
    "<wp:cNvGraphicFramePr/>"
    "<a:graphic>"
    '<a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
    '<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr>'
    '<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
    '<a:solidFill><a:srgbClr val="F2F2F2"/></a:solidFill>'
    '<a:ln w="9525"><a:solidFill><a:srgbClr val="7F7F7F"/></a:solidFill></a:ln>'
    "</wps:spPr><wps:txbx><w:txbxContent/></wps:txbx>"
    '<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="91440" tIns="45720" rIns="91440"'
    ' bIns="45720" anchor="t" anchorCtr="0"><a:spAutoFit/></wps:bodyPr>'
    "</wps:wsp></a:graphicData></a:graphic>"
    "</wp:anchor></w:drawing></mc:Choice>"
    "<mc:Fallback><w:pict>"
    '<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202"'
    ' path="m,l,21600r21600,l21600,xe"><v:stroke joinstyle="miter"/>'
    '<v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>'
    '<v:shape id="Text Box {id}" o:spid="_x0000_s{spid}" type="#_x0000_t202"'
    ' style="position:absolute;margin-left:0;margin-top:3.6pt;width:{width}pt;height:{height}pt;'
    "z-index:251659264;visibility:visible;mso-wrap-style:square;mso-position-horizontal:right;"
    "mso-position-horizontal-relative:margin;mso-position-vertical:absolute;"
    'mso-position-vertical-relative:text;v-text-anchor:top" fillcolor="#f2f2f2"'
    ' strokecolor="#7f7f7f"><v:textbox style="mso-fit-shape-to-text:t"><w:txbxContent/>'
    '</v:textbox><w10:wrap type="square" anchorx="margin"/></v:shape>'
    "</w:pict></mc:Fallback></mc:AlternateContent>"
)


def write_docx(spec: ContractSpec, path: Path) -> None:
    """Write ``spec`` as a Word file at ``path``."""
    path.write_bytes(_Writer(spec).build())


def _w3c(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Writer:
    def __init__(self, spec: ContractSpec) -> None:
        self.spec = spec
        self.doc = docx.Document()
        self.part = self.doc.part
        self.body = self.doc.element.body
        self._revisions = 100  # revision ids, apart from the comment ids python-docx gives out
        self._list_numbers: dict[int, int] = {}
        self._comment_runs: dict[int, list[Run]] = {}

    def build(self) -> bytes:
        self._set_up()
        for block in self.spec.body:
            self._block(block, self.body)
        self._header_and_footer()
        self._footnotes()
        self._comments()
        self._core_properties()
        self._custom_properties()
        self._settings()
        self._drop_thumbnail()
        buffer = io.BytesIO()
        self.doc.save(buffer)
        return _reproducible_zip(buffer.getvalue(), {"docProps/app.xml": self._app_xml()})

    # ---- page and styles ---------------------------------------------------------------------

    def _set_up(self) -> None:
        section = self.doc.sections[0]
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.left_margin = section.right_margin = Cm(2.5)
        section.top_margin = section.bottom_margin = Cm(2.5)
        section.header_distance = section.footer_distance = Cm(1.25)
        styles = self.doc.styles
        normal = styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(10.5)
        normal.paragraph_format.space_after = Pt(6)
        for name, size in (("Title", 16), ("Heading 1", 11), ("Heading 2", 10.5)):
            style = styles[name]
            style.font.name = "Calibri"
            style.font.size = Pt(size)
            style.font.bold = True
            style.font.color.rgb = RGBColor(0, 0, 0)
        footnote_text = styles.add_style("Footnote Text", WD_STYLE_TYPE.PARAGRAPH)
        footnote_text.base_style = normal
        footnote_text.font.size = Pt(8.5)
        footnote_text.paragraph_format.space_after = Pt(0)
        styles.add_style("Footnote Reference", WD_STYLE_TYPE.CHARACTER).font.superscript = True
        link = styles.add_style("Hyperlink", WD_STYLE_TYPE.CHARACTER)
        link.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
        link.font.underline = True
        numbering = self.part.numbering_part.element
        numbering.find(qn("w:num")).addprevious(parse_xml(_LETTERED_LIST))

    # ---- blocks ------------------------------------------------------------------------------

    def _place(self, container: etree._Element, element: etree._Element) -> None:
        if container is self.body:
            self.body.sectPr.addprevious(element)  # the body ends with its section properties
        else:
            container.append(element)

    def _block(self, block: Block, container: etree._Element) -> None:
        if isinstance(block, Paragraph):
            self._paragraph(block, container)
        elif isinstance(block, Table):
            self._table(block, container)
        elif isinstance(block, Image):
            self._image(block, container)
        elif isinstance(block, TextBox):
            self._text_box(block, container)
        elif isinstance(block, PageBreak):
            p = OxmlElement("w:p")
            self._place(container, p)
            etree.SubElement(etree.SubElement(p, qn("w:r")), qn("w:br")).set(qn("w:type"), "page")

    def _paragraph(self, paragraph: Paragraph, container: etree._Element) -> etree._Element:
        p = OxmlElement("w:p")
        self._place(container, p)  # in the tree first, so new children find its namespaces
        proxy = DocxParagraph(p, self.doc)
        if paragraph.style != "Normal":
            proxy.style = paragraph.style
        proxy.alignment = _ALIGN[paragraph.align]
        layout = proxy.paragraph_format
        if paragraph.indent:
            layout.left_indent = Cm(paragraph.indent)
        if paragraph.hanging:
            layout.first_line_indent = Cm(-paragraph.hanging)
        if paragraph.keep_with_next:
            layout.keep_with_next = True
        if paragraph.list_id is not None:
            self._number(p, paragraph.list_id)
        self._inlines(paragraph.inlines, p, proxy)
        return p

    def _number(self, p: etree._Element, list_id: int) -> None:
        """Make ``p`` an item of lettered list ``list_id``; each list starts again at (a)."""
        number = self._list_numbers.get(list_id)
        if number is None:
            num = self.part.numbering_part.element.add_num(int(_LETTERED_LIST_ID))
            num.add_lvlOverride(ilvl=0).add_startOverride(1)
            number = self._list_numbers[list_id] = int(num.numId)
        numbering = p.get_or_add_pPr().get_or_add_numPr()
        numbering.get_or_add_ilvl().val = 0
        numbering.get_or_add_numId().val = number

    def _inlines(
        self, inlines: tuple[Inline, ...], p: etree._Element, proxy: DocxParagraph
    ) -> None:
        """Runs for ``inlines``; neighbouring spans with the same change or link share a wrapper."""
        wrapper: etree._Element | None = None
        key: tuple[str | None, str | None] | None = None
        for inline in inlines:
            if not isinstance(inline, Span):
                wrapper, key = None, None
                p.append(
                    self._footnote_ref(inline) if isinstance(inline, FootnoteRef) else self._page()
                )
                continue
            if (inline.revision, inline.link) != key:
                key = (inline.revision, inline.link)
                wrapper = self._wrapper(inline, p)
            self._run(inline, p if wrapper is None else wrapper, proxy)

    def _wrapper(self, span: Span, p: etree._Element) -> etree._Element | None:
        if span.revision is not None and span.link is not None:
            raise ValueError("A tracked change inside a hyperlink is not supported.")
        if span.revision is not None:
            if self.spec.revision_date is None:
                raise ValueError("A tracked change needs a revision date.")
            self._revisions += 1
            wrapper = etree.SubElement(p, qn(f"w:{span.revision}"))
            wrapper.set(qn("w:id"), str(self._revisions))
            wrapper.set(qn("w:author"), self.spec.revision_author)
            wrapper.set(qn("w:date"), _w3c(self.spec.revision_date))
            return wrapper
        if span.link is not None:
            wrapper = etree.SubElement(p, qn("w:hyperlink"))
            wrapper.set(qn("r:id"), self.part.relate_to(span.link, RT.HYPERLINK, is_external=True))
            wrapper.set(qn("w:history"), "1")
            return wrapper
        return None

    def _run(self, span: Span, parent: etree._Element, proxy: DocxParagraph) -> None:
        r = etree.SubElement(parent, qn("w:r"))
        run = Run(r, proxy)
        run.text = span.text
        if span.link is not None:
            run.style = "Hyperlink"
        if span.bold:
            run.bold = True
        if span.italic:
            run.italic = True
        if span.hidden:
            run.font.hidden = True
        if span.revision == "del":
            for t in r.iter(qn("w:t")):
                t.tag = qn("w:delText")
        if span.comment is not None:
            self._comment_runs.setdefault(span.comment, []).append(run)

    def _footnote_ref(self, ref: FootnoteRef) -> etree._Element:
        return parse_xml(
            f'<w:r {nsdecls("w")}><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
            f'<w:footnoteReference w:id="{ref.number}"/></w:r>'
        )

    def _page(self) -> etree._Element:
        return parse_xml(
            f'<w:fldSimple {nsdecls("w")} w:instr="PAGE"><w:r><w:rPr><w:noProof/></w:rPr>'
            "<w:t>1</w:t></w:r></w:fldSimple>"
        )

    def _table(self, table: Table, container: etree._Element) -> None:
        widths = [round(w * _TWIPS_PER_CM) for w in table.widths]
        tbl = OxmlElement("w:tbl")
        self._place(container, tbl)
        properties = etree.SubElement(tbl, qn("w:tblPr"))
        etree.SubElement(properties, qn("w:tblStyle")).set(qn("w:val"), "TableGrid")
        total = etree.SubElement(properties, qn("w:tblW"))
        total.set(qn("w:w"), str(sum(widths)))
        total.set(qn("w:type"), "dxa")
        grid = etree.SubElement(tbl, qn("w:tblGrid"))
        for width in widths:
            etree.SubElement(grid, qn("w:gridCol")).set(qn("w:w"), str(width))
        for index, row in enumerate(table.rows):
            tr = etree.SubElement(tbl, qn("w:tr"))
            if index == 0:
                etree.SubElement(etree.SubElement(tr, qn("w:trPr")), qn("w:tblHeader"))
            for width, cell in zip(widths, row, strict=True):
                tc = etree.SubElement(tr, qn("w:tc"))
                cell_properties = etree.SubElement(tc, qn("w:tcPr"))
                cell_width = etree.SubElement(cell_properties, qn("w:tcW"))
                cell_width.set(qn("w:w"), str(width))
                cell_width.set(qn("w:type"), "dxa")
                if index == 0:
                    shading = etree.SubElement(cell_properties, qn("w:shd"))
                    shading.set(qn("w:val"), "clear")
                    shading.set(qn("w:color"), "auto")
                    shading.set(qn("w:fill"), "D9E2F3")
                p = self._paragraph(Paragraph(cell, align="left"), tc)
                DocxParagraph(p, self.doc).paragraph_format.space_after = Pt(0)

    def _image(self, image: Image, container: etree._Element) -> None:
        p = OxmlElement("w:p")
        self._place(container, p)
        DocxParagraph(p, self.doc).alignment = _ALIGN[image.align]
        inline = self.part.new_pic_inline(io.BytesIO(image.png), width=Cm(image.width))
        inline.docPr.set("descr", image.alt)
        drawing = etree.SubElement(etree.SubElement(p, qn("w:r")), qn("w:drawing"))
        drawing.append(inline)

    def _text_box(self, box: TextBox, container: etree._Element) -> None:
        p = OxmlElement("w:p")
        self._place(container, p)
        r = etree.SubElement(p, qn("w:r"))
        shape = self.part.next_id
        width, height = Cm(box.width), Cm(1.6)
        r.append(
            parse_xml(
                _TEXT_BOX.format(
                    id=shape,
                    spid=1024 + shape,
                    cx=int(width),
                    cy=int(height),
                    width=round(Emu(width).pt, 1),
                    height=round(Emu(height).pt, 1),
                )
            )
        )
        for content in r.iter(qn("w:txbxContent")):  # the DrawingML text and the VML copy
            for paragraph in box.paragraphs:
                self._paragraph(paragraph, content)

    # ---- the other parts ---------------------------------------------------------------------

    def _header_and_footer(self) -> None:
        section = self.doc.sections[0]
        for story, paragraphs in (
            (section.header, self.spec.header),
            (section.footer, self.spec.footer),
        ):
            story.is_linked_to_previous = False
            root = story.part.element
            for child in list(root):
                root.remove(child)
            for paragraph in paragraphs:
                self._paragraph(paragraph, root)

    def _footnotes(self) -> None:
        if not self.spec.footnotes:
            return
        root = parse_xml(_FOOTNOTES)
        for number, inlines in enumerate(self.spec.footnotes, start=1):
            note = etree.SubElement(root, qn("w:footnote"))
            note.set(qn("w:id"), str(number))
            p = self._paragraph(Paragraph(inlines, style="Footnote Text", align="left"), note)
            reference = parse_xml(
                f'<w:r {nsdecls("w")}><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
                "<w:footnoteRef/></w:r>"
            )
            p.pPr.addnext(reference)  # the note's own number comes first
        part = XmlPart(PackURI("/word/footnotes.xml"), CT.WML_FOOTNOTES, root, self.part.package)
        self.part.relate_to(part, RT.FOOTNOTES)

    def _comments(self) -> None:
        for index, comment in enumerate(self.spec.comments):
            self.doc.add_comment(
                self._comment_runs[index],
                text=comment.text,
                author=comment.author,
                initials=comment.initials,
            )
        if self.spec.comments:  # python-docx dates a comment now(); give it the comment's date
            comments = cast(XmlPart, self.part.part_related_by(RT.COMMENTS))
            elements = comments.element.iter(qn("w:comment"))
            for element, comment in zip(elements, self.spec.comments, strict=True):
                element.set(qn("w:date"), _w3c(comment.date))

    def _core_properties(self) -> None:
        props, core = self.spec.properties, self.doc.core_properties
        core.title = props.title
        core.subject = props.subject
        core.author = props.creator
        core.last_modified_by = props.last_modified_by
        core.keywords = props.keywords
        core.comments = props.description
        core.category = props.category
        core.content_status = props.content_status
        core.created = props.created
        core.modified = props.modified
        core.revision = props.revision

    def _custom_properties(self) -> None:
        if not self.spec.properties.custom:
            return
        fmtid = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"
        rows = "".join(
            f'<property fmtid="{fmtid}" pid="{pid}" name={_attribute(name)}>'
            f"<vt:lpwstr>{escape(value)}</vt:lpwstr></property>"
            for pid, (name, value) in enumerate(self.spec.properties.custom, start=2)
        )
        xml = (
            "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n"
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            'custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'docPropsVTypes">{rows}</Properties>'
        )
        package = self.part.package
        part = Part(
            PackURI("/docProps/custom.xml"), CT.OFC_CUSTOM_PROPERTIES, xml.encode(), package
        )
        package.relate_to(part, RT.CUSTOM_PROPERTIES)

    def _settings(self) -> None:
        """The attached template, document variables and, as Word writes them, revision tracking."""
        settings = cast(XmlPart, self.part.part_related_by(RT.SETTINGS))
        root = settings.element
        # python-docx's template leaves out the zoom percentage the schema requires.
        root.find(qn("w:zoom")).set(qn("w:percent"), "100")
        proof, compat = root.find(qn("w:proofState")), root.find(qn("w:compat"))
        template = OxmlElement("w:attachedTemplate")
        proof.addnext(template)
        rid = settings.relate_to(self.spec.template_path, _ATTACHED_TEMPLATE, is_external=True)
        template.set(qn("r:id"), rid)
        if self.spec.revision_author:
            template.addnext(OxmlElement("w:trackRevisions"))
        if self.spec.footnotes:
            compat.addprevious(
                parse_xml(
                    f'<w:footnotePr {nsdecls("w")}><w:footnote w:id="-1"/>'
                    '<w:footnote w:id="0"/></w:footnotePr>'
                )
            )
        if self.spec.doc_vars:
            variables = OxmlElement("w:docVars")
            compat.addnext(variables)
            for name, value in self.spec.doc_vars:
                variable = etree.SubElement(variables, qn("w:docVar"))
                variable.set(qn("w:name"), name)
                variable.set(qn("w:val"), value)

    def _drop_thumbnail(self) -> None:
        """python-docx's template carries a picture of an empty page; a contract has none."""
        relationships = self.part.package.rels
        for rid, relationship in list(relationships.items()):
            if relationship.reltype == RT.THUMBNAIL:
                del relationships[rid]

    def _app_xml(self) -> bytes:
        props = self.spec.properties
        words = word_count(self.spec.body)
        paragraphs = sum(isinstance(b, Paragraph) for b in self.spec.body)
        return (
            "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n"
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            'extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/'
            'docPropsVTypes">'
            f"<Template>{escape(props.template)}</Template>"
            f"<TotalTime>{props.total_time}</TotalTime>"
            f"<Pages>{max(1, round(words / 420))}</Pages>"
            f"<Words>{words}</Words>"
            f"<Characters>{words * 6}</Characters>"
            "<Application>Microsoft Office Word</Application>"
            "<DocSecurity>0</DocSecurity>"
            f"<Lines>{paragraphs * 2}</Lines>"
            f"<Paragraphs>{paragraphs}</Paragraphs>"
            "<ScaleCrop>false</ScaleCrop>"
            '<HeadingPairs><vt:vector size="2" baseType="variant">'
            "<vt:variant><vt:lpstr>Title</vt:lpstr></vt:variant>"
            "<vt:variant><vt:i4>1</vt:i4></vt:variant></vt:vector></HeadingPairs>"
            '<TitlesOfParts><vt:vector size="1" baseType="lpstr">'
            f"<vt:lpstr>{escape(props.title)}</vt:lpstr></vt:vector></TitlesOfParts>"
            f"<Manager>{escape(props.manager)}</Manager>"
            f"<Company>{escape(props.company)}</Company>"
            "<LinksUpToDate>false</LinksUpToDate>"
            f"<CharactersWithSpaces>{words * 7}</CharactersWithSpaces>"
            "<SharedDoc>false</SharedDoc>"
            f"<HyperlinkBase>{escape(props.hyperlink_base)}</HyperlinkBase>"
            "<HyperlinksChanged>false</HyperlinksChanged>"
            "<AppVersion>16.0000</AppVersion>"
            "</Properties>"
        ).encode()


def _attribute(value: str) -> str:
    """``value`` as a quoted XML attribute value."""
    return '"' + escape(value, {'"': "&quot;"}) + '"'


def _reproducible_zip(data: bytes, replacements: dict[str, bytes]) -> bytes:
    """The package again, with fixed entry dates and some parts replaced."""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            entry = zipfile.ZipInfo(info.filename, date_time=_ZIP_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(entry, replacements.get(info.filename, source.read(info.filename)))
    return out.getvalue()
