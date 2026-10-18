"""A contract as plain data, and its ground truth.

A contract is built once as data and then written out: as a Word file and as PDF files. Nothing in
this module knows about XML or PDF. A tracked deletion is a ``Span`` with
``revision="del"``; a party name split the way Word often saves it is three ``Span`` objects in a
row; a footnote is a ``FootnoteRef`` in the text plus an entry in ``ContractSpec.footnotes``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from themask.model import PlaceholderType

Kind = Literal["supply", "services", "nda", "dpa"]
KINDS: tuple[Kind, ...] = ("supply", "services", "nda", "dpa")

# Every feature a corpus document can have. Every document has the first two.
FEATURES: tuple[str, ...] = (
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
)


@dataclass(frozen=True)
class Span:
    """A run of text with one formatting.

    ``revision`` marks a tracked insertion or deletion, ``hidden`` text that Word does not show,
    ``link`` the target of a hyperlink round the run (``mailto:`` or ``https:``), and ``comment``
    the comment (an index into ``ContractSpec.comments``) anchored on the run.
    """

    text: str
    bold: bool = False
    italic: bool = False
    revision: Literal["ins", "del"] | None = None
    hidden: bool = False
    link: str | None = None
    comment: int | None = None


@dataclass(frozen=True)
class FootnoteRef:
    """The mark of footnote ``number`` (1-based: ``ContractSpec.footnotes[number - 1]``)."""

    number: int


@dataclass(frozen=True)
class PageNumber:
    """The number of the current page (Word's ``PAGE`` field)."""


Inline = Span | FootnoteRef | PageNumber
Align = Literal["left", "center", "right", "justify"]


@dataclass(frozen=True)
class Paragraph:
    """A paragraph.

    ``style`` names a Word paragraph style ("Title", "Heading 1", "Heading 2", "Normal", "List
    Paragraph"); a writer for another format maps it to its own look. ``indent`` and ``hanging``
    are in centimetres: ``hanging`` pulls the first line back left, for "1.1 ..." clauses.
    Paragraphs with the same ``list_id`` form one lettered list: (a), (b), (c) ...
    """

    inlines: tuple[Inline, ...]
    style: str = "Normal"
    align: Align = "justify"
    indent: float = 0.0
    hanging: float = 0.0
    list_id: int | None = None
    keep_with_next: bool = False


Cell = tuple[Inline, ...]


@dataclass(frozen=True)
class Table:
    """A table whose first row is the header row; ``widths`` are column widths in centimetres."""

    rows: tuple[tuple[Cell, ...], ...]
    widths: tuple[float, ...]


@dataclass(frozen=True)
class Image:
    """A picture on a paragraph of its own: PNG bytes, width in centimetres, alternative text."""

    png: bytes
    width: float
    alt: str
    align: Align = "left"


@dataclass(frozen=True)
class TextBox:
    """A floating text box, anchored where it stands in the text; width in centimetres."""

    paragraphs: tuple[Paragraph, ...]
    width: float = 7.0


@dataclass(frozen=True)
class PageBreak:
    """The rest starts on a new page."""


Block = Paragraph | Table | Image | TextBox | PageBreak


@dataclass(frozen=True)
class Comment:
    """A reviewer's comment, anchored on the spans that carry its index."""

    author: str
    initials: str
    text: str
    date: datetime


@dataclass(frozen=True)
class Properties:
    """The file's properties: core (``docProps/core.xml``), extended (``app.xml``) and custom."""

    title: str
    created: datetime
    modified: datetime
    revision: int = 1
    creator: str = ""
    last_modified_by: str = ""
    subject: str = ""
    keywords: str = ""
    description: str = ""
    category: str = ""
    content_status: str = ""
    company: str = ""
    manager: str = ""
    hyperlink_base: str = ""
    template: str = "Normal.dotm"
    total_time: int = 0  # minutes spent editing
    custom: tuple[tuple[str, str], ...] = ()


@dataclass
class TruthItem:
    """One secret in a document, as its truth file lists it.

    ``value`` is the fullest form, spelled exactly as the document spells it. ``variants`` are the
    other forms the document uses, each spelled as in the document: a short company name, "Mr
    Smith", "J. Smith", an IBAN without spaces. ``only_in_deletion`` marks a value that appears
    only in tracked-deleted text, ``hidden`` one that appears only in hidden text.
    """

    type: PlaceholderType
    value: str
    variants: list[str]
    only_in_deletion: bool = False
    hidden: bool = False

    def to_json(self) -> dict[str, object]:
        """The item as the truth file writes it; a flag appears only when it is set."""
        item: dict[str, object] = {
            "type": self.type.value,
            "value": self.value,
            "variants": list(self.variants),
        }
        if self.only_in_deletion:
            item["only_in_deletion"] = True
        if self.hidden:
            item["hidden"] = True
        return item


@dataclass
class ContractSpec:
    """One made-up contract, ready to be written out, with its ground truth.

    ``short_names`` are the two parties' short names (for running headers), ``body`` the content
    in reading order, ``footnotes`` the text of each footnote, ``comments`` the reviewers'
    comments. Tracked changes are by ``revision_author`` on ``revision_date``. ``doc_vars`` and
    ``template_path`` are the document variables and attached template Word keeps in its
    settings. A contract that comes with an annex (a second file in the same case) holds it in
    ``annex``.
    """

    kind: Kind
    seed: int
    features: frozenset[str]
    truth: list[TruthItem]
    defined_terms: list[str]
    title: str
    short_names: tuple[str, str]
    body: list[Block]
    header: list[Paragraph]
    footer: list[Paragraph]
    properties: Properties
    footnotes: list[tuple[Inline, ...]] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    revision_author: str = ""
    revision_date: datetime | None = None
    doc_vars: tuple[tuple[str, str], ...] = ()
    template_path: str = ""
    annex: ContractSpec | None = None
