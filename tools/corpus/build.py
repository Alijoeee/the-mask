"""Building one made-up contract, and its annex, as data with its ground truth.

Everything comes from the document's seed: ``random.Random(seed)`` for every choice and a Faker
(``en_GB``) seeded with it for names, so the same seed always gives the same contract.
"""

from __future__ import annotations

import io
import random
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta

from faker import Faker
from PIL import Image as Picture
from PIL import ImageDraw

from tools.corpus.agreements import AGREEMENTS, Facts
from tools.corpus.annexes import ANNEXES
from tools.corpus.clauses import ROLES, TITLES, signatures
from tools.corpus.compose import NBSP, NNBSP, Composer, Ctx, Numbers
from tools.corpus.long import long_schedules
from tools.corpus.model import (
    FEATURES,
    KINDS,
    ContractSpec,
    Image,
    Kind,
    PageNumber,
    Paragraph,
    Properties,
    Span,
)
from tools.corpus.parties import Party, PartyMaker, Person
from tools.corpus.pools import COMPANIES, CURRENCY, JOB_TITLES, Company
from tools.corpus.truth import Registry, truth_of

# Every document has a header and footer and at least one table.
ALWAYS = frozenset({"header_footer", "table"})


def build_spec(
    seed: int,
    kind: str,
    features: Iterable[str],
    *,
    parties: tuple[str, str] | None = None,
    project: str | None = None,
    bare_amount: bool = False,
) -> ContractSpec:
    """One contract of ``kind`` with ``features``, built from ``seed``.

    ``parties`` names the two companies by short name (``"Northwind"``); otherwise two are drawn.
    ``project`` is a project code name the contract mentions twice, and ``bare_amount`` adds one
    amount written without its currency. A contract with no feature besides a header, footer
    and table is written in the plainest style: straight quotes, "EUR 1,250,000.00", "4 per cent".
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown kind {kind!r}; the kinds are {', '.join(KINDS)}.")
    wanted = frozenset(features) | ALWAYS
    unknown = wanted - set(FEATURES)
    if unknown:
        raise ValueError(f"Unknown features: {', '.join(sorted(unknown))}.")
    if "secret_only_in_deletion" in wanted and "tracked_changes" not in wanted:
        raise ValueError("A secret only in a deletion needs tracked changes.")
    rng = random.Random(seed)
    fake = Faker("en_GB")
    fake.seed_instance(seed)
    plain = wanted == ALWAYS
    companies = _companies(rng, parties)
    registry = Registry()
    people = PartyMaker(
        rng,
        fake,
        registry,
        compact_iban=not plain and rng.random() < 0.3,
        email_style="initial" if plain else rng.choice(("initial", "full", "joined")),
    )
    a, b = _parties(rng, people, kind, companies, shared="shared_surname" in wanted)
    currency = CURRENCY[(b if kind == "dpa" else a).company.country]  # the payee's
    curly = not plain and rng.random() < 0.6
    dated = date(2026, 1, 5) + timedelta(days=rng.randrange(0, 260))
    ctx = Ctx(
        kind=kind,
        seed=seed,
        features=wanted,
        rng=rng,
        registry=registry,
        people=people,
        numbers=_numbers(rng, plain=plain, nbsp="nbsp_numbers" in wanted, currency=currency),
        a=a,
        b=b,
        dated=dated,
        effective=dated + timedelta(days=rng.choice((0, 0, 14, 30))),
        quotes=("\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}")
        if curly
        else ('"', '"'),
        apostrophe="\N{RIGHT SINGLE QUOTATION MARK}" if curly else "'",
        upper_names=not plain and rng.random() < 0.35,
        words=not plain and rng.random() < 0.5,
        bare_amount=bare_amount,
        project=project,
    )
    facts = AGREEMENTS[kind](ctx)
    if "thirty_pages" in wanted:
        long_schedules(ctx)
    signatures(ctx, _signature_png(rng) if "image" in wanted else None)
    if "image" in wanted:
        ctx.c.blocks.insert(0, Image(_logo_png(rng), 4.5, f"{a.short} logo"))
    title = TITLES[kind]
    spec = _spec(
        ctx, title, title, wanted, _properties(ctx, facts, title, rich="properties" in wanted)
    )
    spec.truth = truth_of(registry, spec)
    if "annex" in wanted:
        spec.annex = _annex(ctx, facts)
    return spec


def _companies(rng: random.Random, names: tuple[str, str] | None) -> tuple[Company, Company]:
    if names is not None:
        return COMPANIES[names[0]], COMPANIES[names[1]]
    while True:  # at least one party in the EU, so the contract has a VAT number to show
        first, second = rng.sample(list(COMPANIES.values()), 2)
        if "GB" not in (first.country, second.country) or first.country != second.country:
            return first, second


def _parties(
    rng: random.Random,
    people: PartyMaker,
    kind: Kind,
    companies: tuple[Company, Company],
    *,
    shared: bool,
) -> tuple[Party, Party]:
    """The two parties, their signatories and their contacts for notices.

    With ``shared`` the two signatories share a surname: a man on the side whose contact the
    contract later calls "Mr <Surname>" (the processor in a DPA, the first party otherwise) and a
    woman with another initial on the other side.
    """
    for company in companies:  # the names first, so the truth lists the parties first
        people.company(company)
    titles = rng.sample(JOB_TITLES["signatory"], 2)
    signatories: list[Person] = []
    contacts: list[Person] = []
    if shared:
        mr = 1 if kind == "dpa" else 0
        man = people.person(companies[mr].domain, titles[mr], female=False, honorific="Mr")
        woman = people.person(
            companies[1 - mr].domain, titles[1 - mr], surname=man.last, female=True
        )
        other = people.person(companies[1 - mr].domain, rng.choice(JOB_TITLES["contact"]))
        signatories = [man, woman] if mr == 0 else [woman, man]
        contacts = [man, other] if mr == 0 else [other, man]
    else:
        for company, title in zip(companies, titles, strict=True):
            signatory = people.person(company.domain, title)
            contact = signatory
            if rng.random() >= 0.3:
                contact = people.person(company.domain, rng.choice(JOB_TITLES["contact"]))
            signatories.append(signatory)
            contacts.append(contact)
    first, second = ROLES[kind]
    return (
        people.party(companies[0], first, signatory=signatories[0], contact=contacts[0]),
        people.party(companies[1], second, signatory=signatories[1], contact=contacts[1]),
    )


def _numbers(rng: random.Random, *, plain: bool, nbsp: bool, currency: str) -> Numbers:
    if plain:
        return Numbers(per_cent=True)
    if nbsp:
        group = rng.choice((NBSP, NNBSP))
        return Numbers(group=group, decimal=",", symbol=rng.random() < 0.5, gap=NBSP)
    per_cent = rng.random() < 0.25
    if currency == "GBP" or rng.random() < 0.5:
        symbol = rng.random() < 0.4
        return Numbers(symbol=symbol, gap="" if symbol else " ", per_cent=per_cent)
    return Numbers(group=".", decimal=",", after=rng.random() < 0.5, per_cent=per_cent)


def _properties(ctx: Ctx, facts: Facts, title: str, *, rich: bool) -> Properties:
    rng, a, b = ctx.rng, ctx.a, ctx.b
    created = datetime.combine(
        ctx.dated - timedelta(days=rng.randrange(20, 60)),
        time(rng.randrange(8, 12), rng.randrange(60)),
        tzinfo=UTC,
    )
    modified = datetime.combine(
        ctx.dated - timedelta(days=1), time(rng.randrange(13, 18), rng.randrange(60)), tzinfo=UTC
    )
    revision = rng.randrange(3, 24)
    if not rich:
        return Properties(title=title, created=created, modified=modified, revision=revision)
    return Properties(
        title=f"{title} — {a.short} / {b.short}",
        created=created,
        modified=modified,
        revision=revision,
        creator=a.contact.full,
        last_modified_by=b.contact.full,
        subject=facts.subject,
        keywords=f"{a.short}; {b.short}; {title.lower()}",
        description=f"Final draft for signature, agreed with {b.contact.full}.",
        category="Contracts",
        content_status="Final draft",
        company=a.full,
        manager=a.signatory.full,
        hyperlink_base=f"{a.url}/contracts/",
        template=f"{title}.dotx",
        total_time=rng.randrange(90, 900),
        custom=(
            ("Client", b.full),
            ("Matter owner", a.contact.full),
            ("Contract value", facts.total.value),
            ("Counterparty contact", b.contact.email.value),
        ),
    )


def _spec(
    ctx: Ctx, title: str, running: str, features: frozenset[str], properties: Properties
) -> ContractSpec:
    a, b = ctx.a.short, ctx.b.short
    header = [Paragraph((Span(f"{a} / {b} — {running}"),), style="Header", align="right")]
    footer = [
        Paragraph(
            (Span(f"Confidential · {a} / {b} · Page "), PageNumber()),
            style="Footer",
            align="center",
        )
    ]
    tracked = "tracked_changes" in features
    return ContractSpec(
        kind=ctx.kind,
        seed=ctx.seed,
        features=features,
        truth=[],
        defined_terms=list(ctx.terms),
        title=title,
        short_names=(a, b),
        body=ctx.c.blocks,
        header=header,
        footer=footer,
        properties=properties,
        footnotes=ctx.footnotes,
        comments=ctx.comments,
        revision_author=ctx.b.contact.full if tracked else "",
        revision_date=datetime.combine(ctx.dated - timedelta(days=2), time(14, 5), tzinfo=UTC)
        if tracked
        else None,
        doc_vars=(("DocumentType", title), ("TemplateVersion", "4.2")),
        template_path="file:///C:/Templates/Contracts/" + title.replace(" ", "%20") + ".dotx",
    )


def _annex(ctx: Ctx, facts: Facts) -> ContractSpec:
    """The second file of the case: an annex in its own document, with the same parties."""
    ctx.c, ctx.footnotes, ctx.comments, ctx.terms = Composer(), [], [], []
    ctx.features = ALWAYS
    title = ANNEXES[ctx.kind](ctx, facts)
    running = title.split(" — ")[0]
    spec = _spec(ctx, title, running, ALWAYS, _properties(ctx, facts, title, rich=False))
    spec.truth = truth_of(ctx.registry, spec)
    return spec


def _png(picture: Picture.Image) -> bytes:
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def _logo_png(rng: random.Random) -> bytes:
    """A small made-up logo: shapes only, no text."""
    colour = (rng.randrange(20, 180), rng.randrange(20, 180), rng.randrange(20, 180))
    picture = Picture.new("RGB", (360, 120), "white")
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((8, 8, 112, 112), radius=24, fill=colour)
    draw.ellipse((34, 34, 86, 86), fill="white")
    for i in range(3):
        draw.rectangle((132, 30 + 24 * i, 132 + rng.randrange(120, 216), 44 + 24 * i), fill=colour)
    return _png(picture)


def _signature_png(rng: random.Random) -> bytes:
    """A scanned-looking signature: a scribble over a line."""
    picture = Picture.new("RGB", (320, 100), "white")
    draw = ImageDraw.Draw(picture)
    points = [(12 + 14 * i, 50 + rng.randrange(-32, 33)) for i in range(21)]
    draw.line(points, fill=(18, 32, 96), width=3, joint="curve")
    draw.line([(30, 82), (290, 78)], fill=(18, 32, 96), width=2)
    return _png(picture)
