"""Writing one contract: the running document, its number style and what clause writers share.

``Composer`` collects the blocks of a document and numbers its clauses ("5." and "5.1 ...").
``Numbers`` writes amounts, percentages and quantities in the document's house style. ``Ctx`` holds
everything the clause writers need about the document being built: its parties, random generator,
secrets, footnotes and comments.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from themask.model import PlaceholderType
from tools.corpus.model import (
    Align,
    Block,
    Comment,
    FootnoteRef,
    Inline,
    Kind,
    PageNumber,
    Paragraph,
    Span,
    Table,
)
from tools.corpus.parties import Party, PartyMaker, Person
from tools.corpus.pools import CURRENCY
from tools.corpus.truth import Registry, Secret

P = PlaceholderType
NBSP = "\N{NO-BREAK SPACE}"
NNBSP = "\N{NARROW NO-BREAK SPACE}"

Part = str | Inline
CellContent = str | Inline | Sequence[Part]


def inlines(parts: Iterable[Part]) -> tuple[Inline, ...]:
    """``parts`` as inline content: a string becomes a plain span; empty strings are dropped."""
    return tuple(Span(p) if isinstance(p, str) else p for p in parts if p != "")


def bold(text: str) -> Span:
    return Span(text, bold=True)


class Composer:
    """Collects the blocks of one document in reading order and numbers its clauses."""

    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.clause_number = 0
        self._sub = 0
        self._lists = 0

    def add(self, block: Block) -> None:
        self.blocks.append(block)

    def para(
        self,
        *parts: Part,
        style: str = "Normal",
        align: Align = "justify",
        indent: float = 0.0,
        hanging: float = 0.0,
        keep: bool = False,
    ) -> None:
        self.blocks.append(
            Paragraph(inlines(parts), style, align, indent, hanging, keep_with_next=keep)
        )

    def title(self, text: str) -> None:
        self.para(text, style="Title", align="center")

    def heading(self, text: str) -> int:
        """Start the next numbered clause ("5. PRICE AND PAYMENT"); returns its number."""
        self.clause_number += 1
        self._sub = 0
        self.para(
            f"{self.clause_number}. {text.upper()}", style="Heading 1", align="left", keep=True
        )
        return self.clause_number

    def section(self, text: str) -> None:
        """An unnumbered heading such as "SCHEDULE 1"; clause numbers start again after it."""
        self.clause_number = 0
        self._sub = 0
        self.para(text, style="Heading 1", align="left", keep=True)

    def clause(self, *parts: Part) -> str:
        """The next sub-clause of the current clause ("5.2 ..."); returns its number."""
        self._sub += 1
        number = f"{self.clause_number}.{self._sub}"
        self.para(f"{number} ", *parts, indent=1.25, hanging=1.25)
        return number

    def detail(self, *parts: Part) -> None:
        """An indented line under a clause, such as one line of bank or contact details."""
        self.para(*parts, align="left", indent=2.5)

    def items(self, *items: str | Sequence[Part]) -> None:
        """A lettered list, (a), (b), (c) ..., under the current clause."""
        self._lists += 1
        for item in items:
            parts = [item] if isinstance(item, str) else list(item)
            self.blocks.append(
                Paragraph(inlines(parts), "List Paragraph", "justify", 2.5, 0.75, self._lists)
            )

    def table(self, rows: Sequence[Sequence[CellContent]], widths: Sequence[float]) -> None:
        def cell(content: CellContent) -> tuple[Inline, ...]:
            if isinstance(content, (str, Span, FootnoteRef, PageNumber)):
                return inlines([content])
            return inlines(content)

        self.blocks.append(Table(tuple(tuple(cell(c) for c in row) for row in rows), tuple(widths)))


def plain(value: Decimal) -> str:
    """``value`` without trailing zeros or an exponent: 2.50 is "2.5", 10 is "10"."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


_SYMBOLS = {"EUR": "€", "GBP": "£"}


@dataclass(frozen=True)
class Numbers:
    """How one document writes numbers: separators, currency and percentages.

    ``gap`` goes between a currency and its number ("" gives "€48,000"); ``after`` puts a currency
    code after the number ("1.250.000,00 EUR"); ``per_cent`` writes "4 per cent" for "4%".
    """

    group: str = ","
    decimal: str = "."
    symbol: bool = False
    after: bool = False
    gap: str = " "
    per_cent: bool = False

    def number(self, value: Decimal, places: int = 0) -> str:
        text = f"{value:,.{places}f}"
        separators: dict[str, str | int | None] = {",": self.group, ".": self.decimal}
        return text.translate(str.maketrans(separators))

    def money(self, value: Decimal, currency: str, places: int = 2) -> str:
        number = self.number(value, places)
        if self.symbol:
            return f"{_SYMBOLS[currency]}{self.gap}{number}"
        gap = self.gap or " "
        return f"{number}{gap}{currency}" if self.after else f"{currency}{gap}{number}"

    def percent(self, value: Decimal) -> str:
        text = plain(value).replace(".", self.decimal)
        return f"{text} per cent" if self.per_cent else f"{text}%"


def money_value(rng: random.Random, low: float, high: float, step: float = 0.01) -> Decimal:
    """A random amount between ``low`` and ``high``, a whole multiple of ``step``."""
    steps = round((high - low) / step)
    value = Decimal(str(low)) + Decimal(str(step)) * rng.randrange(steps + 1)
    return value.quantize(Decimal("0.01"), ROUND_HALF_UP)


_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def in_words(n: int) -> str:
    """A whole number in British English words: 2,500,000 is "two million five hundred thousand"."""

    def below_thousand(k: int) -> str:
        hundreds, rest = divmod(k, 100)
        words = [f"{_ONES[hundreds]} hundred"] if hundreds else []
        if rest:
            tens, ones = divmod(rest, 10)
            small = _ONES[rest] if rest < 20 else _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
            words.append(f"and {small}" if hundreds else small)
        return " ".join(words)

    if n == 0:
        return "zero"
    parts = []
    for size, name in ((10**9, "billion"), (10**6, "million"), (10**3, "thousand"), (1, "")):
        count, n = divmod(n, size)
        if count:
            words = below_thousand(count)
            parts.append(f"{words} {name}".strip())
    if len(parts) > 1 and " hundred" not in parts[-1] and "and " not in parts[-1]:
        parts[-1] = f"and {parts[-1]}"
    return " ".join(parts)


_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def day(d: date) -> str:
    """A date the way contracts write it: "14 March 2026"."""
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


@dataclass
class Ctx:
    """Everything the clause writers need about the document being built.

    ``dated`` is the date of the agreement and ``effective`` the day it starts. ``upper_names``
    writes party names in capitals in the signature blocks, ``words`` adds a round amount in words
    after its figure, ``bare_amount`` adds one amount written without its currency, and
    ``project`` is a project code name the contract mentions.
    """

    kind: Kind
    seed: int
    features: frozenset[str]
    rng: random.Random
    registry: Registry
    people: PartyMaker
    numbers: Numbers
    a: Party
    b: Party
    dated: date
    effective: date
    quotes: tuple[str, str] = ('"', '"')
    apostrophe: str = "'"
    upper_names: bool = False
    words: bool = False
    bare_amount: bool = False
    project: str | None = None
    c: Composer = field(default_factory=Composer)
    footnotes: list[tuple[Inline, ...]] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)

    def has(self, feature: str) -> bool:
        return feature in self.features

    # ---- words -------------------------------------------------------------------------------

    def q(self, term: str) -> str:
        """A defined term in the document's quotation marks, noted as a defined term."""
        if term not in self.terms:
            self.terms.append(term)
        return f"{self.quotes[0]}{term}{self.quotes[1]}"

    def s(self, name: str) -> str:
        """The possessive: "the Buyer's"."""
        return f"{name}{self.apostrophe}s"

    @property
    def payee(self) -> Party:
        """The party that is paid: the processor in a DPA, the first party otherwise."""
        return self.b if self.kind == "dpa" else self.a

    @property
    def payer(self) -> Party:
        return self.a if self.kind == "dpa" else self.b

    @property
    def currency(self) -> str:
        """The currency of the contract: the payee's."""
        return CURRENCY[self.payee.company.country]

    # ---- secrets -------------------------------------------------------------------------------

    def money(self, value: Decimal, places: int = 2) -> Secret:
        """An amount in the payee's currency, written in the document's style."""
        return self.registry.add(P.AMOUNT, self.numbers.money(value, self.currency, places))

    def pct(self, value: str) -> Secret:
        return self.registry.add(P.PERCENT, self.numbers.percent(Decimal(value)))

    def qty(self, value: Decimal | int, unit: str, places: int = 0) -> Secret:
        return self.registry.add(
            P.QUANTITY, f"{self.numbers.number(Decimal(value), places)} {unit}"
        )

    def bare(self, value: Decimal) -> Secret:
        """An amount written without its currency, as a few contracts do in running text."""
        return self.registry.add(P.AMOUNT, self.numbers.number(value, 0))

    # ---- notes ---------------------------------------------------------------------------------

    def footnote(self, text: str) -> FootnoteRef:
        """A footnote with ``text``; returns the mark to put in the text."""
        self.footnotes.append((Span(f" {text}"),))
        return FootnoteRef(len(self.footnotes))

    def comment(self, author: Person, text: str) -> int:
        """A comment by ``author``, dated a few days before the contract; returns its index."""
        when = datetime.combine(
            self.dated - timedelta(days=3), time(9 + len(self.comments), 15), tzinfo=UTC
        )
        initials = f"{author.first[0]}{author.last[0]}"
        self.comments.append(Comment(author.full, initials, text, when))
        return len(self.comments) - 1
