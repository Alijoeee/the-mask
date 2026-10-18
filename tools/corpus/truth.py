"""The secrets of one case, and how they become the truth file of each of its documents.

The builder registers every confidential value it writes, together with the other forms it may
use for it. Once a document is complete, ``truth_of`` reads that document's own text to decide
which secrets it holds, which of the other forms it really uses, and whether a value appears only
in tracked-deleted text or only in hidden text. So the truth always matches the text: a form that
was never written is not listed, and no flag is set by hand.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from themask.model import PlaceholderType
from tools.corpus.model import (
    Block,
    ContractSpec,
    Inline,
    Paragraph,
    Span,
    Table,
    TextBox,
    TruthItem,
)


class Secret:
    """A confidential value and the other forms of it a document may use."""

    def __init__(self, type_: PlaceholderType, value: str, forms: Iterable[str] = ()) -> None:
        self.type = type_
        self.value = value
        self.forms: list[str] = []
        self.add_forms(forms)

    def add_forms(self, forms: Iterable[str]) -> None:
        """Note further forms of the value; repeats and the value itself are ignored."""
        for form in forms:
            if form and form != self.value and form not in self.forms:
                self.forms.append(form)

    def form(self, text: str) -> str:
        """Note ``text`` as a form of this secret and return it, to write it into the document."""
        self.add_forms([text])
        return text

    def __str__(self) -> str:
        return self.value


class Registry:
    """Every secret of one case (a contract and its annex), in the order they were made.

    Registering the same type and value twice gives back the same secret.
    """

    def __init__(self) -> None:
        self._secrets: dict[tuple[PlaceholderType, str], Secret] = {}

    def add(self, type_: PlaceholderType, value: str, *forms: str) -> Secret:
        """The secret for ``value``, made on first use, with ``forms`` noted."""
        secret = self._secrets.get((type_, value))
        if secret is None:
            secret = self._secrets[(type_, value)] = Secret(type_, value)
        secret.add_forms(forms)
        return secret

    def __iter__(self) -> Iterator[Secret]:
        return iter(self._secrets.values())


@dataclass
class _Texts:
    """A document's text, paragraph by paragraph, in three views.

    ``accepted`` is what Word shows with every tracked change accepted, ``rejected`` with every
    change rejected; hidden text is in neither and sits in ``hidden`` instead.
    """

    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)

    def add(self, inlines: Iterable[Inline]) -> None:
        accepted, rejected, hidden = [], [], []
        for inline in inlines:
            if not isinstance(inline, Span):
                continue
            if inline.hidden:
                hidden.append(inline.text)
                continue
            if inline.revision != "del":
                accepted.append(inline.text)
            if inline.revision != "ins":
                rejected.append(inline.text)
        self.accepted.append("".join(accepted))
        self.rejected.append("".join(rejected))
        self.hidden.append("".join(hidden))


def _paragraphs(blocks: Iterable[Block]) -> Iterator[tuple[Inline, ...]]:
    for block in blocks:
        if isinstance(block, Paragraph):
            yield block.inlines
        elif isinstance(block, Table):
            for row in block.rows:
                yield from row
        elif isinstance(block, TextBox):
            yield from (p.inlines for p in block.paragraphs)


def _texts_of(spec: ContractSpec) -> _Texts:
    texts = _Texts()
    for inlines in _paragraphs([*spec.body, *spec.header, *spec.footer]):
        texts.add(inlines)
    for footnote in spec.footnotes:
        texts.add(footnote)
    return texts


def _pattern(form: str) -> re.Pattern[str]:
    """``form`` written exactly, and not as the middle of a longer word or number."""
    start = r"(?<![A-Za-z0-9])" if form[0].isalnum() else ""
    end = r"(?![A-Za-z0-9])" if form[-1].isalnum() else ""
    return re.compile(start + re.escape(form) + end)


def _item(secret: Secret, views: dict[str, str]) -> TruthItem | None:
    """The truth item for ``secret`` in a document with these views, or None if it is not there.

    A form counts as used when it appears at least once on its own, not just inside a longer form
    of the same secret ("Northwind" inside "Northwind Trading B.V." does not count).
    """
    forms = [secret.value, *secret.forms]
    patterns = [_pattern(f) for f in forms]
    where: dict[str, set[str]] = {f: set() for f in forms}
    on_its_own: set[str] = set()
    for view, text in views.items():
        spans = {f: [m.span() for m in p.finditer(text)] for f, p in zip(forms, patterns)}
        for f, found in spans.items():
            if found:
                where[f].add(view)
            longer = [s for g in forms if len(g) > len(f) for s in spans[g]]
            if any(not any(a <= s and e <= b for a, b in longer) for s, e in found):
                on_its_own.add(f)
    used = [f for f in forms if where[f]]
    if not used:
        return None
    if not where[secret.value]:
        raise ValueError(f"{secret.value!r} is only written in other forms: {used}")
    views_used = set().union(*where.values())
    return TruthItem(
        type=secret.type,
        value=secret.value,
        variants=[f for f in secret.forms if f in on_its_own],
        only_in_deletion=views_used == {"rejected"},
        hidden=views_used == {"hidden"},
    )


def truth_of(registry: Registry, spec: ContractSpec) -> list[TruthItem]:
    """The truth of ``spec``: every registered secret its text holds, in the order made.

    Raises ValueError when two secrets of the same type share a form the document uses, because
    the truth could then not say which value that form stands for.
    """
    texts = _texts_of(spec)
    views = {
        "accepted": "\n".join(texts.accepted),
        "rejected": "\n".join(texts.rejected),
        "hidden": "\n".join(texts.hidden),
    }
    items: list[TruthItem] = []
    owner: dict[tuple[PlaceholderType, str], str] = {}
    for secret in registry:
        item = _item(secret, views)
        if item is None:
            continue
        for form in [item.value, *item.variants]:
            other = owner.setdefault((item.type, form), item.value)
            if other != item.value:
                raise ValueError(f"{form!r} stands for both {other!r} and {item.value!r}")
        items.append(item)
    return items
