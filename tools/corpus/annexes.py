"""The annexes: the second file of a case, written as a document of its own.

An annex names both parties in full (bold and split across runs in its parties clause, like the
contract, and once more in running text) so that the same company gets the same placeholder in
both files, and it adds secrets of its own: contacts, an overflow warehouse, sub-processors.
"""

from __future__ import annotations

from collections.abc import Callable

from tools.corpus.agreements import Facts
from tools.corpus.clauses import TITLES, parties_clause, pct
from tools.corpus.compose import Ctx, Part, bold, day
from tools.corpus.pools import COMPANIES, REGISTERED_IN


def _opening(ctx: Ctx, title: str, made_under: str) -> None:
    c = ctx.c
    c.title(title.upper())
    c.para(
        f"This {made_under} forms part of the {TITLES[ctx.kind].lower()} between {ctx.a.full} and"
        f" {ctx.b.full} dated {day(ctx.dated)} (the {ctx.q('Agreement')}).",
        align="left",
    )
    parties_clause(ctx, office_only=True)
    c.para("Words defined in the Agreement have the same meaning here.")


def supply_annex(ctx: Ctx, facts: Facts) -> str:
    c, a, b, rng = ctx.c, ctx.a, ctx.b, ctx.rng
    title = "Annex 1 — Product specifications and prices"
    _opening(ctx, title, "Annex")
    c.heading("Products")
    rows: list[list[Part]] = [
        [bold("Product"), bold("Lead time"), bold("Unit price"), bold("Minimum order")]
    ]
    for product, price in facts.priced:
        lead_time = f"{rng.choice((5, 10, 14, 21))} days"
        minimum = ctx.qty(rng.randrange(5, 41, 5), "cartons")
        rows.append([product, lead_time, price.value, minimum.value])
    c.table(rows, (6.4, 2.8, 3.0, 3.8))
    c.heading("Quality contacts")
    c.clause(
        f"Questions about the quality of the Goods should be sent to {a.contact.formal} at"
        f" {a.contact.email} or by telephone on {a.phone}."
    )
    quality = ctx.people.person(b.company.domain, "Quality Manager")
    c.clause(
        f"The {ctx.s('Buyer')} quality team is led by {quality.formal}, who may be reached at"
        f" {quality.email}."
    )
    c.heading("Validity")
    c.clause(
        f"The prices in this Annex are valid until 31 December {ctx.dated.year} and may then be"
        " reviewed in accordance with the Agreement."
    )
    return title


def services_annex(ctx: Ctx, facts: Facts) -> str:
    c, a, rng = ctx.c, ctx.a, ctx.rng
    title = "Statement of Work — Peak season support"
    _opening(ctx, title, "Statement of Work")
    overflow, _ = ctx.people.address(a.company.country)
    extra = ctx.qty(rng.randrange(200, 1_201, 50), "pallets")
    year = ctx.dated.year
    c.heading("Scope")
    c.clause(
        f"From 1 October {year} to 31 January {year + 1} the Service Provider shall provide"
        f" additional storage for up to {extra} at its overflow warehouse at {overflow}."
    )
    c.clause("All other terms of the Agreement apply to the additional storage.")
    c.heading("Charges")
    rows: list[list[Part]] = [[bold("Activity"), bold("Rate")]]
    rows += [[activity, rate.value] for activity, rate in facts.priced]
    rows.append(["Peak season surcharge", pct(ctx, "8", "10", "12.5").value])
    c.table(rows, (8.0, 8.0))
    c.heading("Key personnel")
    coordinator = ctx.people.person(a.company.domain, "Peak Season Coordinator")
    c.clause(
        f"The peak season coordinator is {coordinator.formal}, who may be reached at"
        f" {coordinator.email} or on {a.phone}."
    )
    return title


def nda_annex(ctx: Ctx, facts: Facts) -> str:
    c, b = ctx.c, ctx.b
    title = "Schedule — Authorised representatives"
    _opening(ctx, title, "Schedule")
    rows: list[list[Part]] = [[bold("Name"), bold("Position"), bold("E-mail")]]
    for position in ("Head of Procurement", "Category Manager", "Legal Counsel"):
        person = ctx.people.person(b.company.domain, position)
        rows.append([person.full, position, person.email.value])
    c.table(rows, (5.0, 5.0, 6.0))
    c.para(
        "Only the people listed here may receive Confidential Information on behalf of the"
        " Recipient."
    )
    return title


def dpa_annex(ctx: Ctx, facts: Facts) -> str:
    c = ctx.c
    title = "Annex 2 — Approved sub-processors"
    _opening(ctx, title, "Annex")
    rows: list[list[Part]] = [
        [bold("Sub-processor"), bold("Registered office"), bold("Service"), bold("Location")]
    ]
    for short, service in facts.sub_processors:
        company = COMPANIES[short]
        office, _ = ctx.people.address(company.country)
        name = ctx.people.company(company)
        rows.append([name.value, office.value, service, REGISTERED_IN[company.country]])
    c.table(rows, (4.4, 6.6, 2.8, 2.8))
    officer: list[Part] = []
    if facts.privacy is not None:
        officer = [f" Changes to this list shall be notified to {facts.privacy.email}."]
    c.para(
        "Each Sub-processor has signed a written agreement that imposes the same data protection"
        " obligations as the Agreement.",
        *officer,
    )
    return title


ANNEXES: dict[str, Callable[[Ctx, Facts], str]] = {
    "supply": supply_annex,
    "services": services_annex,
    "nda": nda_annex,
    "dpa": dpa_annex,
}
