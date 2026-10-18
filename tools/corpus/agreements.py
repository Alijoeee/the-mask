"""The four kinds of agreement in the corpus: supply, logistics services, NDA and DPA.

Each writer puts the whole agreement up to the signature blocks into ``ctx.c``: opening, parties,
background, numbered clauses and the schedule with its table. The builder adds the long schedules
of a 30-page document and the signatures; ``annexes`` writes the second file of a case.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from tools.corpus.clauses import (
    agreed_by,
    background,
    business_day,
    confidentiality,
    definitions,
    email,
    general,
    governing_law,
    hidden_note,
    liability,
    notices,
    opening,
    payment,
    pct,
    remark,
    round_amount,
    round_to,
    stated_total,
    term_and_termination,
    text_box,
    third_party,
    volume,
    worded,
)
from tools.corpus.compose import Ctx, Part, bold, day, money_value, plain
from tools.corpus.model import Span
from tools.corpus.parties import Person
from tools.corpus.pools import COMPANIES, GOODS, SERVICE_LINES, SUB_PROCESSORS
from tools.corpus.truth import Secret

_MONTHLY = {"pallets": (300, 2_400, 50), "cartons": (6_000, 60_000, 500), "tonnes": (4, 30, 1)}
_SINGULAR = {"pallets": "pallet", "cartons": "carton", "tonnes": "tonne"}


@dataclass
class Facts:
    """What an agreement tells the builder: for the file properties and for its annex."""

    total: Secret
    subject: str
    priced: list[tuple[str, Secret]] = field(default_factory=list)
    privacy: Person | None = None
    sub_processors: list[tuple[str, str]] = field(default_factory=list)  # (short name, service)


def _footnote(ctx: Ctx, text: str) -> list[Part]:
    return [ctx.footnote(text)] if ctx.has("footnotes") else []


def _hidden(ctx: Ctx, make: Callable[[], str]) -> list[Part]:
    """A hidden note, made only when the document has hidden text (so its secret is too)."""
    return hidden_note(make()) if ctx.has("hidden_text") else []


def _bare(ctx: Ctx, low: int, high: int) -> Secret:
    return ctx.bare(Decimal(ctx.rng.randrange(low, high, 250)))


# --------------------------------------------------------------------------------------------
# Supply
# --------------------------------------------------------------------------------------------


def supply(ctx: Ctx) -> Facts:
    c, a, b, rng = ctx.c, ctx.a, ctx.b, ctx.rng
    goods, catalogue = rng.choice(GOODS)
    lines = rng.sample(list(catalogue), rng.randrange(3, 5))
    opening(ctx)
    recitals = [
        f"The Supplier makes and distributes {goods}.",
        "The Buyer wishes to buy the Goods from the Supplier on the terms of this Agreement.",
    ]
    if ctx.project:
        recitals.append(
            f"The Buyer needs the Goods for its store refurbishment programme known as"
            f" {ctx.project}."
        )
    background(ctx, *recitals)
    delivery, _ = ctx.people.address(b.company.country)
    definitions(
        ctx,
        [
            business_day(ctx),
            (
                "Contract Year",
                (
                    "each period of twelve months starting on the Effective Date or on an"
                    " anniversary of it."
                ),
            ),
            (
                "Delivery Point",
                (
                    f"{ctx.s('the Buyer')} distribution centre at {delivery}, or any other place the"
                    " parties agree in writing."
                ),
            ),
            ("Effective Date", f"{day(ctx.effective)}."),
            ("Goods", "the products listed in Schedule 1."),
            ("Order", "an order for Goods placed by the Buyer under this Agreement."),
            ("Price", "the price of the Goods set out in Schedule 1."),
            (
                "Specification",
                (
                    "the description and quality requirements of the Goods agreed in writing by the"
                    " parties."
                ),
            ),
        ],
    )
    rows, total, total_value, priced = _price_table(ctx, lines)

    c.heading("Supply of the Goods")
    c.clause(
        "The Supplier shall supply, and the Buyer shall buy, the Goods in accordance with Orders"
        " placed under this Agreement.",
        *_footnote(
            ctx,
            f"{ctx.s(b.short)} general terms of purchase do not apply to Orders under this"
            " Agreement.",
        ),
    )
    minimum, _ = volume(ctx, lines[0][1], 0.6)
    c.clause(
        f"The Buyer shall buy at least {minimum} of the Goods in each Contract Year (the"
        f" {ctx.q('Minimum Volume')})."
    )
    stock = ctx.qty(rng.randrange(12, 61, 4), "pallets")
    c.clause(
        f"The Supplier shall keep a safety stock of at least {stock} of the Goods at its warehouse."
    )
    c.clause(
        "The Buyer shall give the Supplier a rolling forecast of its requirements for the next"
        " three months by the fifth Business Day of each month. Forecasts are for planning only"
        " and do not bind the Buyer."
    )
    c.clause(
        f"{ctx.s(a.short)} account manager for the Buyer is {a.contact.mr} (telephone"
        f" {a.local_phone}), who shall attend the quarterly review meetings between the parties."
    )
    if ctx.project:
        c.clause(
            f"Deliveries for {ctx.project} shall be labelled separately and invoiced under their"
            " own purchase order."
        )
    c.clause(
        f"The Supplier uses {third_party(ctx)} as its carrier for deliveries to the Delivery"
        " Point, and remains responsible for the carrier as for its own staff."
    )

    c.heading("Orders")
    c.clause(
        "Each Order shall be placed in writing, including by e-mail, and shall state the type and"
        " quantity of Goods, the requested delivery date and the Delivery Point."
    )
    c.clause(
        "The Supplier shall accept or reject each Order within two Business Days of receiving it."
        " An Order is accepted only when the Supplier confirms it in writing."
    )
    smallest = ctx.qty(rng.choice((4, 6, 8, 10)), "pallets")
    c.clause(f"The smallest quantity the Buyer may order at one time is {smallest}.")

    c.heading("Delivery")
    lead: list[Part] = ["14"]
    if ctx.has("tracked_changes"):
        lead = [Span("14", revision="del"), Span("10", revision="ins")]
    c.clause(
        "The Supplier shall deliver the Goods to the Delivery Point within ",
        *lead,
        " days of accepting the Order.",
    )
    c.clause(
        "Delivery is complete when the Goods have been unloaded at the Delivery Point. Risk in the"
        " Goods passes to the Buyer on delivery, and title passes when the Supplier has received"
        " payment for them in full."
    )
    credit, ceiling = pct(ctx, "1.5", "2", "2.5"), pct(ctx, "10", "12.5", "15")
    c.clause(
        f"If the Supplier delivers late, it shall pay the Buyer a service credit of {credit} of the"
        f" Price of the late Goods for each full week of delay, up to {ceiling} of that Price."
    )

    c.heading("Price and payment")
    c.clause(
        "The Price is set out in Schedule 1 and excludes VAT. The Price for the first Contract"
        " Year is ",
        *stated_total(ctx, total, total_value),
        " in total.",
        *_hidden(
            ctx,
            lambda: (
                "the lowest total approved by the board is"
                f" {ctx.money(round_to(total_value * Decimal('0.85'), 1000))}."
            ),
        ),
    )
    if ctx.bare_amount:
        c.clause(
            "For budgeting purposes only, the parties expect a total price of"
            f" {_bare(ctx, 40_000, 90_000)} per year for replenishment orders after the first"
            " Contract Year."
        )
    increase = pct(ctx, "2.5", "3", "3.5", "4")
    c.clause(
        "The Supplier may increase the Price once in each Contract Year by giving the Buyer at"
        f" least 60 days{ctx.apostrophe} written notice. No increase may exceed {increase} of the"
        " Price then in force."
    )
    payment(ctx)

    c.heading("Quality and warranties")
    warranty = c.clause("The Supplier warrants that on delivery the Goods shall:")
    c.items(
        "conform in all material respects with the Specification;",
        "be free from material defects in design, materials and workmanship;",
        "be of satisfactory quality and fit for any purpose held out by the Supplier; and",
        "comply with all applicable statutory and regulatory requirements.",
    )
    c.clause(
        "The Buyer shall inspect the Goods within five Business Days of delivery and notify the"
        " Supplier of any defect that a reasonable inspection would reveal."
    )
    c.clause(
        f"If any Goods do not comply with clause {warranty}, the Supplier shall, at the"
        f" {ctx.s('Buyer')} option, repair or replace them or refund their Price in full."
    )
    limit, limit_n = round_amount(ctx, 1_000_000, 5_000_000, 250_000)
    liability(ctx, a, [limit.value, worded(ctx, limit, limit_n)], b.signatory)
    confidentiality(ctx)
    term_and_termination(ctx)
    notices(ctx)
    general(ctx)
    governing_law(ctx)

    c.section("SCHEDULE 1 — GOODS AND PRICES")
    c.table(rows, (5.4, 3.0, 2.6, 2.4, 3.2))
    text_box(ctx, f"the volumes in this Schedule were confirmed by {b.contact.formal} by e-mail.")
    agreed_by(ctx, "Prices")
    return Facts(total, f"Supply of {goods}", priced)


def _price_table(
    ctx: Ctx, lines: list[tuple[str, str, float, float]]
) -> tuple[list[list[Part]], Secret, Decimal, list[tuple[str, Secret]]]:
    headings = ("Product", "Annual volume", "Unit price", "Discount", "Annual value")
    rows: list[list[Part]] = [[bold(heading) for heading in headings]]
    total = Decimal(0)
    priced: list[tuple[str, Secret]] = []
    for product, unit, low, high in lines:
        quantity, n = volume(ctx, unit)
        price = money_value(ctx.rng, low, high, 0.05 if high < 100 else 1.0)
        discount = Decimal(ctx.rng.randrange(1, 16)) / 2
        value = (price * n * (1 - discount / 100)).quantize(Decimal("0.01"))
        total += value
        unit_price = ctx.money(price)
        priced.append((product, unit_price))
        rows.append(
            [
                product,
                quantity.value,
                unit_price.value,
                ctx.pct(plain(discount)).value,
                ctx.money(value).value,
            ]
        )
    total_secret = ctx.money(total)
    rows.append([bold("Total"), "", "", "", bold(total_secret.value)])
    return rows, total_secret, total, priced


# --------------------------------------------------------------------------------------------
# Logistics services
# --------------------------------------------------------------------------------------------


def services(ctx: Ctx) -> Facts:
    c, a, b, rng = ctx.c, ctx.a, ctx.b, ctx.rng
    opening(ctx)
    background(
        ctx,
        "The Service Provider runs warehouses and provides contract logistics services.",
        "The Customer wishes to appoint the Service Provider to store and handle its goods at the"
        " Site and to deliver them to its stores, on the terms of this Agreement.",
    )
    site, _ = ctx.people.address(a.company.country)
    definitions(
        ctx,
        [
            business_day(ctx),
            ("Charges", "the charges for the Services set out in Schedule 1."),
            ("Effective Date", f"{day(ctx.effective)}."),
            ("Key Personnel", "the people named as such in this Agreement."),
            (
                "Services",
                "the storage, handling and transport services described in this Agreement.",
            ),
            ("Service Levels", "the levels of service the Service Provider must meet each month."),
            ("Site", f"{ctx.s('the Service Provider')} warehouse at {site}."),
        ],
    )
    rows, monthly_value, priced = _rate_table(ctx)

    c.heading("Appointment and services")
    c.clause(
        "The Customer appoints the Service Provider to provide the Services from the Effective"
        " Date, and the Service Provider accepts that appointment.",
        *_footnote(ctx, f"{ctx.s(b.short)} own carriers may collect from the Site by arrangement."),
    )
    capacity = ctx.qty(rng.randrange(800, 4_001, 100), "pallets")
    c.clause(
        f"The Service Provider shall keep storage capacity for up to {capacity} available for the"
        " Customer at the Site."
    )
    weekly = ctx.qty(rng.randrange(4_000, 30_001, 500), "cartons")
    c.clause(
        f"The Service Provider shall receive, store, pick and dispatch the {ctx.s('Customer')}"
        f" goods, handling up to {weekly} each week."
    )
    c.clause(
        f"The Service Provider may use {third_party(ctx)} for transport between the Site and the"
        f" {ctx.s('Customer')} stores. It remains responsible for that subcontractor as for its"
        " own staff."
    )

    c.heading("Service levels")
    c.clause("The Service Provider shall meet the following Service Levels in each month:")
    c.items(
        f"order accuracy of at least {pct(ctx, '99.5', '99.7', '99.8')};",
        f"dispatch on the day of receipt of at least {pct(ctx, '97.5', '98', '98.5')} of the"
        " orders received before 2.00 pm; and",
        f"stock record accuracy of at least {pct(ctx, '99.6', '99.9')}.",
    )
    credit, ceiling = pct(ctx, "2", "3", "5"), pct(ctx, "10", "15", "20")
    c.clause(
        "If the Service Provider misses a Service Level in any month, it shall credit the"
        f" Customer with {credit} of the Charges for that month for each Service Level missed (a"
        f" {ctx.q('Service Credit')}), up to {ceiling} of those Charges."
    )

    c.heading("Charges and payment")
    annual_value = monthly_value * 12
    annual = ctx.money(annual_value)
    c.clause(
        "The Charges are set out in Schedule 1 and exclude VAT. The Charges for the first year are"
        " estimated at ",
        *stated_total(ctx, annual, annual_value),
        " in total.",
        *_hidden(
            ctx,
            lambda: (
                "the lowest Charges approved by the board are"
                f" {ctx.money(round_to(annual_value * Decimal('0.9'), 1000))} a year."
            ),
        ),
    )
    if ctx.bare_amount:
        c.clause(
            "For the second year the parties expect a total price of"
            f" {_bare(ctx, 40_000, 99_000)} per year for the additional seasonal storage."
        )
    review = pct(ctx, "2.5", "3", "3.5")
    c.clause(
        "The Service Provider may review the Charges once a year by giving at least 90"
        f" days{ctx.apostrophe} written notice. No increase may exceed {review} of the Charges then"
        " in force."
    )
    payment(ctx)

    c.heading("Customer obligations")
    c.clause(
        "The Customer shall give the Service Provider accurate information about the goods to be"
        " stored, including their weight, dimensions and any special handling requirements."
    )
    c.clause(
        "The Customer shall make sure that its goods are properly packed and labelled for storage"
        " and transport."
    )

    c.heading("Personnel")
    c.clause(
        f"The Service Provider shall appoint {a.contact.formal} as account manager for the"
        f" Customer. {a.contact.mr} is Key Personnel and shall not be replaced without the"
        f" {ctx.s('Customer')} prior written consent, which shall not be unreasonably withheld."
    )
    c.clause(
        f"The {ctx.s('Customer')} contact for day-to-day operational matters is"
        f" {b.contact.initial} (telephone {b.local_phone})."
    )

    c.heading("Insurance")
    insured, _ = round_amount(ctx, 2_000_000, 10_000_000, 1_000_000)
    c.clause(
        f"The Service Provider shall maintain public liability insurance of at least {insured} for"
        " each claim, and insurance of the goods at the Site for their full replacement value."
    )
    limit = pct(ctx, "125", "150", "200")
    liability(
        ctx,
        a,
        [
            limit.value,
            (
                " of the Charges paid or payable in the twelve months before the event giving rise to"
                " the claim"
            ),
        ],
        b.signatory,
    )
    confidentiality(ctx)
    term_and_termination(ctx)
    notices(ctx)
    general(ctx)
    governing_law(ctx)

    c.section("SCHEDULE 1 — CHARGES")
    c.table(rows, (5.6, 3.4, 4.4, 3.2))
    text_box(
        ctx, f"the volumes in this Schedule were confirmed by {b.contact.formal} on the site visit."
    )
    agreed_by(ctx, "Rates")
    return Facts(annual, "Contract logistics services", priced)


def _rate_table(ctx: Ctx) -> tuple[list[list[Part]], Decimal, list[tuple[str, Secret]]]:
    rows: list[list[Part]] = [
        [bold("Activity"), bold("Monthly volume"), bold("Rate"), bold("Monthly charge")]
    ]
    total = Decimal(0)
    priced: list[tuple[str, Secret]] = []
    for activity, unit, low, high in ctx.rng.sample(list(SERVICE_LINES), 4):
        lowest, highest, step = _MONTHLY[unit]
        n = ctx.rng.randrange(lowest, highest + 1, step)
        rate = money_value(ctx.rng, low, high, 0.05 if high < 100 else 1.0)
        charge = (rate * n).quantize(Decimal("0.01"))
        total += charge
        rate_secret = ctx.money(rate)
        priced.append((activity, rate_secret))
        rows.append(
            [
                activity,
                ctx.qty(n, unit).value,
                f"{rate_secret} per {_SINGULAR[unit]}",
                ctx.money(charge).value,
            ]
        )
    surcharge = pct(ctx, "3.5", "4.5", "6")
    rows.append(["Fuel surcharge", "", f"{surcharge} of transport charges", ""])
    rows.append([bold("Total monthly charge"), "", "", bold(ctx.money(total).value)])
    return rows, total, priced


# --------------------------------------------------------------------------------------------
# Non-disclosure
# --------------------------------------------------------------------------------------------


def nda(ctx: Ctx) -> Facts:
    c, a, b, rng = ctx.c, ctx.a, ctx.b, ctx.rng
    goods, _ = rng.choice(GOODS)
    opening(ctx)
    background(
        ctx,
        f"The parties are discussing a possible supply of {goods} by the Discloser to the"
        " Recipient.",
        "The Discloser is willing to disclose confidential information to the Recipient for the"
        " Purpose on the terms of this Agreement.",
    )
    annual = ctx.qty(rng.randrange(10_000, 120_001, 1_000), "units")
    definitions(
        ctx,
        [
            business_day(ctx),
            (
                "Confidential Information",
                (
                    "all information of a confidential nature, in any form, that the Discloser or its"
                    " Representatives disclose to the Recipient or its Representatives in connection"
                    " with the Purpose, including prices, volumes, specifications, customer"
                    " information and know-how."
                ),
            ),
            (
                "Purpose",
                (
                    f"the evaluation of a possible supply by the Discloser to the Recipient of up to"
                    f" {annual} of {goods} each year."
                ),
            ),
            (
                "Representatives",
                (
                    "in relation to a party, its officers, employees, professional advisers and the"
                    " companies in its group."
                ),
            ),
        ],
    )

    c.heading("Confidentiality obligations")
    c.clause("The Recipient shall:")
    c.items(
        "keep the Confidential Information secret and confidential;",
        "not use or exploit the Confidential Information in any way except for the Purpose;",
        "not disclose the Confidential Information to any person except as this Agreement permits;",
        "not copy or record the Confidential Information except as strictly necessary for the"
        " Purpose; and",
        "apply to the Confidential Information security measures no less strict than those it"
        " applies to its own confidential information.",
    )
    c.clause(
        f"The {ctx.s('Discloser')} contact for the Purpose is {a.contact.mr} (telephone"
        f" {a.local_phone})."
    )

    c.heading("Permitted disclosure")
    c.clause(
        "The Recipient may disclose Confidential Information to those of its Representatives who"
        " need to know it for the Purpose, provided that it tells them of its confidential nature"
        " before disclosure and remains responsible for their compliance with this Agreement.",
        *_footnote(ctx, f"The companies in the {ctx.s('Recipient')} group are listed on {b.url}."),
    )
    c.clause(
        f"In particular, the Recipient may share Confidential Information with its professional"
        f" adviser {third_party(ctx)}, which shall be treated as one of its Representatives.",
        *_hidden(
            ctx,
            lambda: (
                "background checks on the Recipient were run by"
                f" {ctx.people.person(a.company.domain, 'Compliance Officer').formal}."
            ),
        ),
    )
    c.clause(
        "The Recipient may disclose Confidential Information to the extent required by law, by any"
        " governmental or regulatory authority or by a court of competent jurisdiction, provided"
        " that it gives the Discloser as much notice of the disclosure as the law permits."
    )

    c.heading("Return and destruction")
    c.clause(
        "At the request of the Discloser, the Recipient shall promptly destroy or return all"
        " documents and materials containing Confidential Information and erase it from its"
        " computer systems, so far as this is technically practicable."
    )

    c.heading("Evaluation samples and costs")
    samples = ctx.qty(rng.randrange(100, 1_001, 50), "units")
    charge = ctx.money(money_value(rng, 1_500, 9_500, 50))
    note = f"{a.contact.full} will invoice the samples separately."
    c.clause(
        f"The Discloser shall provide {samples} of the products as evaluation samples. The"
        " Recipient shall pay ",
        remark(ctx, charge.value, b.contact, note),
        " for the samples.",
    )
    payment(ctx)

    c.heading("Remedies")
    c.clause(
        "The Recipient acknowledges that damages alone may not be an adequate remedy for a breach"
        " of this Agreement, and that the Discloser is entitled to seek an injunction or specific"
        " performance."
    )
    damages, damages_n = round_amount(ctx, 100_000, 1_000_000, 50_000)
    damages_note = f"{b.signatory.full} wants this figure lowered before signature."
    c.clause(
        "Without affecting any other remedy, the Recipient shall pay the Discloser ",
        remark(ctx, damages.value, a.contact, damages_note),
        f"{worded(ctx, damages, damages_n)} as liquidated damages for each material breach of"
        f" clause 2, which the parties agree is a genuine pre-estimate of the"
        f" {ctx.s('Discloser')} loss.",
    )
    if ctx.bare_amount:
        c.clause(
            "The parties expect that a supply agreement for the Purpose would have a total price"
            f" of {_bare(ctx, 150_000, 900_000)} per year."
        )

    c.heading("No licence and no warranty")
    c.clause(
        "All Confidential Information remains the property of the Discloser. This Agreement grants"
        " no licence under any patent, trade mark, copyright or other right."
    )
    c.clause(
        "The Discloser gives no warranty as to the accuracy or completeness of the Confidential"
        " Information."
    )

    c.heading("Duration")
    c.clause(
        "The obligations in this Agreement continue for two years from the date of this"
        " Agreement, or for as long as the Confidential Information remains confidential, if"
        " longer."
    )
    earlier = None
    if ctx.has("secret_only_in_deletion"):
        earlier = ctx.people.person(b.company.domain, b.contact.title)
    notices(ctx, earlier_contact=earlier)
    general(ctx)
    governing_law(ctx)

    c.section("SCHEDULE — EVALUATION DETAILS")
    value, _ = round_amount(ctx, 500_000, 4_000_000, 50_000)
    rows: list[list[Part]] = [
        [bold("Item"), bold("Detail")],
        ["Indicative annual volume", annual.value],
        ["Evaluation samples", samples.value],
        ["Sample charge", charge.value],
        ["Target price reduction", pct(ctx, "5", "7.5", "10").value],
        ["Indicative contract value", value.value],
        ["Liquidated damages per breach", damages.value],
    ]
    c.table(rows, (7.0, 9.0))
    text_box(ctx, f"evaluation samples will be collected from {a.address}.")
    agreed_by(ctx, "Details")
    return Facts(
        value, f"Evaluation of a possible supply of {goods}", [("Evaluation samples", charge)]
    )


# --------------------------------------------------------------------------------------------
# Data processing
# --------------------------------------------------------------------------------------------

_PROCESSING = (
    "payroll and HR administration services",
    "customer relationship management services",
    "cloud hosting and e-mail delivery services",
    "loyalty programme and marketing analytics services",
)


def dpa(ctx: Ctx) -> Facts:
    c, a, b, rng = ctx.c, ctx.a, ctx.b, ctx.rng
    work = rng.choice(_PROCESSING)
    main_date = ctx.dated - timedelta(days=rng.randrange(30, 400))
    opening(ctx)
    background(
        ctx,
        f"The Controller and the Processor are parties to a services agreement dated"
        f" {day(main_date)} (the {ctx.q('Main Agreement')}), under which the Processor provides"
        f" {work} (the {ctx.q('Services')}).",
        "In providing the Services the Processor processes personal data on behalf of the"
        " Controller. This Agreement sets out the terms of that processing, as Article 28 of the"
        " GDPR requires.",
    )
    definitions(
        ctx,
        [
            business_day(ctx),
            (
                "Data Protection Laws",
                (
                    "Regulation (EU) 2016/679 (the GDPR) and any law that implements or supplements"
                    " it."
                ),
            ),
            (
                "Personal Data",
                (
                    "any personal data processed by the Processor on behalf of the Controller under"
                    " the Main Agreement."
                ),
            ),
            (
                "Personal Data Breach",
                (
                    "a breach of security leading to the accidental or unlawful destruction, loss,"
                    " alteration or unauthorised disclosure of, or access to, Personal Data."
                ),
            ),
            (
                "Sub-processor",
                "any third party appointed by the Processor to process Personal Data.",
            ),
        ],
    )
    privacy = ctx.people.person(a.company.domain, "Data Protection Officer")
    records = ctx.qty(rng.randrange(40_000, 400_001, 5_000), "records")

    c.heading("Scope of the processing")
    c.clause(
        "The Processor shall process the Personal Data only on the documented instructions of the"
        " Controller, including with regard to transfers of Personal Data outside the European"
        " Economic Area."
    )
    c.clause(
        f"The processing concerns up to {records} about the customers and employees of the"
        " Controller, as described in Annex 1."
    )
    c.clause(
        f"The {ctx.s('Processor')} account manager for the Controller is {b.contact.mr}"
        f" (telephone {b.local_phone})."
    )

    c.heading("Obligations of the Processor")
    c.clause("The Processor shall:")
    c.items(
        "ensure that every person it authorises to process the Personal Data is bound by a duty"
        " of confidentiality;",
        "take all the security measures required by Article 32 of the GDPR;",
        "assist the Controller, by appropriate technical and organisational measures, in"
        " responding to requests from data subjects;",
        "assist the Controller in meeting its obligations on security, breach notification and"
        " data protection impact assessments; and",
        "make available to the Controller all information necessary to demonstrate compliance with"
        " this Agreement.",
    )

    c.heading("Sub-processors")
    available = [(n, s) for n, s in SUB_PROCESSORS if n not in (a.company.short, b.company.short)]
    hosting = rng.choice([n for n, s in available if s == "hosting"])
    subs = [(hosting, "hosting"), *((n, s) for n, s in available if s != "hosting")]
    named = [ctx.people.company(COMPANIES[n]) for n, _ in subs[:2]]
    c.clause(
        "The Controller authorises the Processor to engage the Sub-processors listed in Annex 1,"
        f" including {named[0]} for {subs[0][1]} and {named[1]} for {subs[1][1]}.",
        *_footnote(ctx, f"The current list is also published at {b.url}."),
    )
    c.clause(
        "The Processor shall inform the Controller of any intended addition or replacement of a"
        " Sub-processor at least 30 days in advance, giving the Controller the opportunity to"
        " object."
    )
    c.clause(
        "The Processor shall impose on each Sub-processor the same data protection obligations as"
        " are set out in this Agreement and remains fully liable for the performance of each"
        " Sub-processor."
    )

    c.heading("Security")
    c.clause(
        "The Processor shall implement appropriate technical and organisational measures to"
        " protect the Personal Data, including encryption in transit and at rest, access controls"
        " based on need to know, regular testing of its systems and secure deletion of media."
    )

    c.heading("Personal data breaches")
    reached: list[Part] = [email(ctx, privacy.email)]
    if ctx.has("secret_only_in_deletion"):
        mailbox = ctx.registry.add(privacy.email.type, f"privacy@{a.company.domain}")
        reached = [Span(mailbox.value, revision="del"), Span(privacy.email.value, revision="ins")]
    c.clause(
        "The Processor shall notify the Controller without undue delay, and in any event within 48"
        " hours, after becoming aware of a Personal Data Breach. Notifications shall be sent to ",
        *reached,
        f" and confirmed by telephone on {a.phone}.",
        *_hidden(
            ctx,
            lambda: (
                f"the {ctx.s('Processor')} out-of-hours security line is"
                f" {ctx.people.phone(b.company.country, b.area)}."
            ),
        ),
    )
    c.clause(
        "The notification shall describe the nature of the breach, the categories and approximate"
        " number of data subjects and records concerned, its likely consequences and the measures"
        " taken or proposed."
    )

    c.heading("Audits and assistance")
    c.clause(
        "The Processor shall allow for and contribute to audits, including inspections, conducted"
        " by the Controller or an auditor mandated by the Controller, on at least 30"
        f" days{ctx.apostrophe} notice."
    )
    audit_cap = ctx.money(Decimal(rng.randrange(5_000, 25_001, 500)))
    note = f"{privacy.full} asked us to keep this cap as low as possible."
    c.clause(
        "The Controller shall pay for assistance and audits at the rates set out in Annex 1, up to ",
        remark(ctx, audit_cap.value, a.contact, note),
        " in each year, unless the audit reveals a material breach of this Agreement by the"
        " Processor.",
    )
    if ctx.bare_amount:
        c.clause(
            f"The parties expect these fees to stay below a total fee of {_bare(ctx, 6_000, 24_000)}"
            " per year."
        )
    payment(ctx)

    c.heading("International transfers")
    c.clause(
        "The Processor shall not transfer Personal Data outside the European Economic Area"
        " without the prior written consent of the Controller and, where required, the standard"
        " contractual clauses adopted by the European Commission."
    )
    limit, limit_n = round_amount(ctx, 250_000, 2_000_000, 250_000)
    liability(ctx, b, [limit.value, worded(ctx, limit, limit_n)], a.signatory)

    c.heading("Duration and deletion")
    c.clause(
        "This Agreement continues for as long as the Processor processes Personal Data on behalf"
        " of the Controller."
    )
    c.clause(
        "Within 30 days after the end of the Services, the Processor shall, at the choice of the"
        " Controller, delete or return all Personal Data and delete existing copies, unless the"
        " law requires their storage."
    )
    notices(ctx, privacy=privacy)
    general(ctx)
    governing_law(ctx)

    c.section("ANNEX 1 — DETAILS OF THE PROCESSING AND FEES")
    day_rate = ctx.money(money_value(rng, 900, 1_800, 50))
    rows: list[list[Part]] = [
        [bold("Item"), bold("Detail")],
        ["Subject matter", work],
        ["Categories of data subjects", "customers and employees of the Controller"],
        ["Categories of personal data", "names, contact details, account and transaction data"],
        ["Volume", f"up to {records}"],
        ["Approved Sub-processors", f"{named[0]}; {named[1]}"],
        ["Assistance fee", f"{day_rate} per day"],
        ["Annual audit cap", audit_cap.value],
        ["Service credit for late breach notice", f"{pct(ctx, '5', '10')} of the monthly fee"],
    ]
    c.table(rows, (6.0, 10.0))
    text_box(ctx, f"questions about this Annex go to {b.contact.email}.")
    agreed_by(ctx, "Fees")
    return Facts(
        audit_cap,
        f"Processing of personal data for {work}",
        [("Assistance", day_rate)],
        privacy,
        subs,
    )


AGREEMENTS: dict[str, Callable[[Ctx], Facts]] = {
    "supply": supply,
    "services": services,
    "nda": nda,
    "dpa": dpa,
}
