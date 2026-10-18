"""The clauses every kind of agreement shares, and the small pieces they are built from.

Every value that is a secret goes through the document's registry (``ctx.money``, ``ctx.pct``, a
party's or person's details); everything else is ordinary contract wording with defined terms,
clause numbers, dates and durations, none of which is a secret. Where a feature changes the text
(a tracked change, a comment, a footnote, a link) the change is made here, at the one place the
clause is written.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

from tools.corpus.compose import Ctx, Part, bold, day, in_words
from tools.corpus.model import Image, Paragraph, Span, TextBox
from tools.corpus.parties import Party, Person
from tools.corpus.pools import COMPANIES, GOVERNING_LAW, THIRD_PARTIES
from tools.corpus.truth import Secret

ROLES = {
    "supply": ("Supplier", "Buyer"),
    "services": ("Service Provider", "Customer"),
    "nda": ("Discloser", "Recipient"),
    "dpa": ("Controller", "Processor"),
}
TITLES = {
    "supply": "Supply Agreement",
    "services": "Logistics Services Agreement",
    "nda": "Non-Disclosure Agreement",
    "dpa": "Data Processing Agreement",
}
CURRENCY_NAMES = {"EUR": "euros", "GBP": "pounds sterling"}
_BASE_RATES = {"EUR": "the European Central Bank", "GBP": "the Bank of England"}
# The range of a yearly volume in each unit: lowest, highest, step.
_VOLUMES = {
    "units": (20_000, 180_000, 1_000),
    "cartons": (800, 9_000, 50),
    "litres": (4_000, 48_000, 500),
    "kg": (1_500, 25_000, 250),
    "pallets": (24, 240, 6),
}

# --------------------------------------------------------------------------------------------
# Small pieces
# --------------------------------------------------------------------------------------------


def split_name(name: str) -> list[Span]:
    """A party name in three bold runs, the way Word often saves it: "Northwind ", "Trading "..."""
    words = name.split(" ")
    pieces = [f"{words[0]} ", f"{words[1]} ", " ".join(words[2:])]
    return [Span(p, bold=True) for p in pieces]


def the(party: Party) -> str:
    """The party by its defined term: "the Supplier"."""
    return f"the {party.role}"


def cap(text: str) -> str:
    """``text`` with a capital first letter, to start a sentence."""
    return text[:1].upper() + text[1:]


def remark(ctx: Ctx, text: str, author: Person, note: str) -> Span:
    """``text``, with ``author``'s comment ``note`` on it when the document has comments."""
    if not ctx.has("comments"):
        return Span(text)
    return Span(text, comment=ctx.comment(author, note))


def email(ctx: Ctx, secret: Secret) -> Span:
    """An e-mail address, as a ``mailto:`` link when the document has hyperlinks."""
    return Span(secret.value, link=f"mailto:{secret.value}" if ctx.has("hyperlinks") else None)


def website(ctx: Ctx, secret: Secret) -> Span:
    """A web address, as a link when the document has hyperlinks."""
    return Span(secret.value, link=secret.value if ctx.has("hyperlinks") else None)


def volume(ctx: Ctx, unit: str, share: float = 1.0) -> tuple[Secret, int]:
    """A quantity in ``unit``, ``share`` of a typical yearly volume, and its number."""
    low, high, step = _VOLUMES[unit]
    n = max(step, int(ctx.rng.randrange(low, high + 1, step) * share) // step * step)
    return ctx.qty(n, unit), n


def round_to(value: Decimal, step: int) -> Decimal:
    """``value`` rounded to a whole multiple of ``step``."""
    return (value / step).quantize(Decimal(1)) * step


def round_amount(ctx: Ctx, low: int, high: int, step: int) -> tuple[Secret, int]:
    """A round amount such as a liability cap, and its number."""
    n = ctx.rng.randrange(low, high + 1, step)
    return ctx.money(Decimal(n)), n


def worded(ctx: Ctx, secret: Secret, n: int) -> str:
    """The amount in words after its figure, " (two million euros)", where a document does that."""
    if not ctx.words or n % 100_000:
        return ""
    return f" ({secret.form(f'{in_words(n)} {CURRENCY_NAMES[ctx.currency]}')})"


def pct(ctx: Ctx, *choices: str) -> Secret:
    """A percentage, one of ``choices``."""
    return ctx.pct(ctx.rng.choice(choices))


def third_party(ctx: Ctx) -> Secret:
    """A carrier, transport subcontractor or adviser the contract names (never a party)."""
    taken = {ctx.a.company.short, ctx.b.company.short}
    names = [n for n in THIRD_PARTIES[ctx.kind] if n not in taken]
    return ctx.people.company(COMPANIES[ctx.rng.choice(names)])


def hidden_note(text: str) -> list[Part]:
    """An internal note Word does not show, put at the end of a paragraph."""
    return [Span(f" Internal note: {text}", hidden=True)]


def stated_total(ctx: Ctx, total: Secret, value: Decimal) -> list[Part]:
    """The contract total as a clause states it: changed by a tracked change, or commented on."""
    if ctx.has("secret_only_in_deletion") and ctx.kind in ("supply", "services"):
        earlier = ctx.money(round_to(value * Decimal("0.92"), 1000))
        return [Span(earlier.value, revision="del"), Span(total.value, revision="ins")]
    note = f"Volumes confirmed by {ctx.b.contact.full}. The total follows from the schedule."
    return [remark(ctx, total.value, ctx.a.contact, note)]


def text_box(ctx: Ctx, text: str) -> None:
    """A floating "Text box note", when the document has a text box."""
    if ctx.has("textbox"):
        ctx.c.add(TextBox((Paragraph((bold("Text box note: "), Span(text)), align="left"),)))


def agreed_by(ctx: Ctx, what: str) -> None:
    """The line under a schedule saying who agreed it: "Prices agreed by J. Smith and K. Lee"."""
    a, b = ctx.a.signatory.initial, ctx.b.signatory.initial
    ref: list[Part] = []
    if ctx.has("footnotes"):
        ref = [ctx.footnote(f"{what} were last reviewed with {ctx.a.contact.formal}.")]
    agreed = ctx.dated - timedelta(days=ctx.rng.randrange(5, 30))
    ctx.c.para(f"{what} agreed by {a} and {b} on {day(agreed)}.", *ref, align="left")


# --------------------------------------------------------------------------------------------
# The parts every agreement has
# --------------------------------------------------------------------------------------------


def parties_clause(ctx: Ctx, *, office_only: bool = False) -> None:
    """BETWEEN: (1) ... (the "Supplier"); and (2) ... (the "Buyer"). Names bold, in three runs."""
    c = ctx.c
    c.para(bold("BETWEEN:"), align="left", keep=True)
    for number, party in ((1, ctx.a), (2, ctx.b)):
        end = "; and" if number == 1 else "."
        entity = "limited liability partnership" if party.company.is_partnership else "company"
        registered = (
            ""
            if office_only
            else f", a {entity} registered in {party.registered_in} under number {party.reg}"
        )
        c.para(
            f"({number}) ",
            *split_name(party.full),
            f"{registered}, whose registered office is at {party.address}"
            f" (the {ctx.q(party.role)}){end}",
            align="left",
        )


def opening(ctx: Ctx) -> None:
    ctx.c.title(TITLES[ctx.kind].upper())
    ctx.c.para(f"THIS AGREEMENT is dated {day(ctx.dated)}.", align="left")
    parties_clause(ctx)


def background(ctx: Ctx, *recitals: str) -> None:
    c = ctx.c
    c.para(bold("BACKGROUND"), align="left", keep=True)
    for letter, text in zip("ABCDEF", recitals, strict=False):
        c.para(f"({letter}) {text}")
    c.para(bold("AGREED TERMS"), align="left", keep=True)


def definitions(ctx: Ctx, entries: Sequence[tuple[str, str]]) -> None:
    c = ctx.c
    c.heading("Definitions and interpretation")
    c.clause("In this Agreement the following definitions apply:")
    for term, meaning in sorted(entries):
        c.para(bold(ctx.q(term)), f" means {meaning}", indent=2.5)
    c.clause(
        "Clause, schedule and paragraph headings do not affect the interpretation of this"
        " Agreement."
    )
    c.clause(
        "A reference to a statute or statutory provision is a reference to it as amended or"
        " re-enacted from time to time."
    )
    c.clause(
        "Words in the singular include the plural, and words in the plural include the singular."
    )


def business_day(ctx: Ctx) -> tuple[str, str]:
    law = GOVERNING_LAW[ctx.a.company.country][0]
    return ("Business Day", f"a day other than a Saturday, Sunday or public holiday in {law}.")


def payment(ctx: Ctx) -> None:
    c, payer, payee = ctx.c, ctx.payer, ctx.payee
    days: list[Part] = ["30"]
    if ctx.has("tracked_changes"):
        days = [Span("30", revision="del"), Span("45", revision="ins")]
    c.clause(
        f"{cap(the(payee))} shall invoice {the(payer)} monthly in arrears. {cap(the(payer))} shall"
        " pay each valid invoice within ",
        *days,
        " days of the date of the invoice.",
    )
    c.clause(
        f"Payments shall be made in {CURRENCY_NAMES[ctx.currency]} by bank transfer to the"
        f" following account of {the(payee)}:"
    )
    c.detail(f"Account name: {payee.full}")
    c.detail(f"IBAN: {payee.iban}")
    c.detail(f"BIC: {payee.bic}")
    vats = [f"the VAT number of {the(p)} is {p.vat}" for p in (payee, payer) if p.vat]
    if vats:
        c.clause(f"For invoicing purposes, {' and '.join(vats)}.")
    interest = pct(ctx, "2", "3", "4", "8")
    c.clause(
        f"If {the(payer)} fails to pay any amount by its due date, it shall pay interest on the"
        f" overdue amount at the rate of {interest} a year above the base rate of"
        f" {_BASE_RATES[ctx.currency]} from time to time, from the due date until payment."
    )


def liability(ctx: Ctx, liable: Party, limit: Sequence[Part], comment_by: Person) -> None:
    c = ctx.c
    n = c.heading("Limitation of liability")
    c.clause(
        "Nothing in this Agreement limits any liability that cannot legally be limited, including"
        " liability for death or personal injury caused by negligence and for fraud or fraudulent"
        " misrepresentation."
    )
    parts = list(limit)
    if isinstance(parts[0], str):
        note = f"{comment_by.full} asked for a higher cap. We kept the figure from the last draft."
        reviewer = ctx.b.contact if comment_by in ctx.a.people else ctx.a.contact
        parts[0] = remark(ctx, parts[0], reviewer, note)
    c.clause(
        f"Subject to clause {n}.1, the total liability of {the(liable)} arising under or in"
        " connection with this Agreement, whether in contract, tort (including negligence), breach"
        " of statutory duty or otherwise, shall not exceed ",
        *parts,
        ".",
    )
    c.clause(
        "Neither party shall be liable for any loss of profits, sales, business, agreements or"
        " contracts, anticipated savings or goodwill, or for any indirect or consequential loss."
    )


def confidentiality(ctx: Ctx) -> None:
    c = ctx.c
    c.heading("Confidentiality")
    c.clause(
        "Each party shall keep confidential all information about the business, affairs,"
        " customers and suppliers of the other party that it receives in connection with this"
        " Agreement, during this Agreement and for five years after it ends."
    )
    c.clause(
        "Each party may disclose such information to its employees, officers, advisers and"
        " subcontractors who need to know it for the purposes of this Agreement, provided that"
        " they keep it confidential, and as required by law, a court of competent jurisdiction or"
        " any regulatory authority."
    )


def term_and_termination(ctx: Ctx) -> None:
    c = ctx.c
    c.heading("Term and termination")
    c.clause(
        "This Agreement starts on the Effective Date and continues for an initial term of three"
        f" years (the {ctx.q('Initial Term')}). It then renews automatically for successive"
        " periods of twelve months unless either party gives the other at least six"
        f" months{ctx.apostrophe} written notice to end it at the end of the Initial Term or of"
        " any renewal period."
    )
    c.clause(
        "Either party may terminate this Agreement with immediate effect by giving written notice"
        " to the other party if:"
    )
    c.items(
        "the other party commits a material breach of this Agreement which cannot be remedied"
        " or, if it can be remedied, which it fails to remedy within 30 days of being notified of"
        " the breach in writing;",
        "the other party suspends, or threatens to suspend, payment of its debts, or is unable to"
        " pay its debts as they fall due; or",
        "the other party enters into liquidation, administration or any arrangement with its"
        " creditors, other than for the purpose of a solvent restructuring.",
    )
    c.clause(
        "Termination of this Agreement does not affect any rights, remedies, obligations or"
        " liabilities of the parties that have accrued up to the date of termination."
    )


def notices(
    ctx: Ctx, *, privacy: Person | None = None, earlier_contact: Person | None = None
) -> None:
    """The notices clause with both parties' contact details.

    ``privacy`` adds the first party's data protection officer; ``earlier_contact`` is a contact
    of the second party whom a tracked change replaces by the current one.
    """
    c = ctx.c
    c.heading("Notices")
    c.clause(
        "Any notice given under this Agreement shall be in writing and shall be delivered by"
        " hand, by pre-paid first-class post or other next working day delivery service, or by"
        " e-mail, to the other party as follows:"
    )
    for party in (ctx.a, ctx.b):
        contact = party.contact
        c.detail(bold(party.full))
        attention: list[Part] = [f"{contact.formal}, {contact.title}"]
        if earlier_contact is not None and party is ctx.b:
            attention = [
                Span(f"{earlier_contact.formal}, {earlier_contact.title}", revision="del"),
                Span(f"{contact.formal}, {contact.title}", revision="ins"),
            ]
        c.detail("Attention: ", *attention)
        c.detail(f"Address: {party.address}")
        c.detail("E-mail: ", email(ctx, contact.email))
        c.detail(f"Telephone: {party.phone}")
        c.detail("Website: ", website(ctx, party.url))
        if privacy is not None and party is ctx.a:
            c.detail(f"Data protection officer: {privacy.formal}, ", email(ctx, privacy.email))
    note: list[Part] = []
    if ctx.has("footnotes"):
        copy_to = ctx.b.signatory.email
        note = [ctx.footnote(f"Copies of notices to {the(ctx.b)} may also be sent to {copy_to}.")]
    c.clause(
        "A notice is deemed received: if delivered by hand, when it is left at the address above;"
        " if sent by post, at 9.00 am on the second Business Day after posting; and if sent by"
        " e-mail, at the time of transmission.",
        *note,
    )
    c.clause(
        "This clause does not apply to the service of any proceedings or other documents in any"
        " legal action."
    )
    if ctx.has("existing_placeholders"):
        c.para(
            Span(
                "Drafting note: the comments returned on the masked draft call the"
                f" {ctx.s(ctx.b.role)} contact [PERSON_1], and that reference has been kept as it"
                " was. Insert the name of the witness in place of [Name] before signature.",
                italic=True,
            )
        )


def general(ctx: Ctx) -> None:
    c = ctx.c
    c.heading("General")
    c.clause(
        "Neither party shall be in breach of this Agreement nor liable for any delay in performing"
        " its obligations if the delay or failure results from events, circumstances or causes"
        " beyond its reasonable control."
    )
    c.clause(
        "Neither party may assign, transfer or subcontract any of its rights or obligations under"
        " this Agreement without the prior written consent of the other party, which shall not be"
        " unreasonably withheld."
    )
    entire: list[Part] = [
        (
            "This Agreement is the entire agreement between the parties and supersedes all previous"
            " agreements, promises and understandings between them relating to its subject matter."
        )
    ]
    if ctx.has("tracked_changes"):
        entire.append(Span(" It is drawn up in the English language only.", revision="ins"))
    c.clause(*entire)
    c.clause(
        "No variation of this Agreement shall be effective unless it is in writing and signed by"
        " the parties or their authorised representatives."
    )
    if ctx.a.company.country == "GB":
        c.clause(
            "A person who is not a party to this Agreement shall not have any rights under the"
            " Contracts (Rights of Third Parties) Act 1999 to enforce any of its terms."
        )
    c.clause(
        "This Agreement may be signed in any number of counterparts, each of which is an original"
        " and which together are one agreement."
    )


def governing_law(ctx: Ctx) -> None:
    c = ctx.c
    law, courts = GOVERNING_LAW[ctx.a.company.country]
    c.heading("Governing law and jurisdiction")
    c.clause(
        "This Agreement and any dispute or claim arising out of or in connection with it,"
        " including non-contractual disputes or claims, shall be governed by the law of"
        f" {law}."
    )
    c.clause(
        f"Each party irrevocably agrees that {courts} shall have exclusive jurisdiction to settle"
        " any such dispute or claim."
    )


def signatures(ctx: Ctx, signature_png: bytes | None) -> None:
    c = ctx.c
    c.para("This Agreement has been entered into on the date stated at the beginning of it.")
    for party in (ctx.a, ctx.b):
        name = party.upper if ctx.upper_names else party.full
        c.para(bold(f"SIGNED for and on behalf of {name}"), align="left", keep=True)
        if signature_png is not None and party is ctx.a:
            c.add(Image(signature_png, 4.0, f"Signature of {party.signatory.full}"))
        c.para("By: ______________________________", align="left", keep=True)
        c.para(f"Name: {party.signatory.full}", align="left", keep=True)
        c.para(f"Title: {party.signatory.title}", align="left", keep=True)
        c.para("Date: ____________________", align="left")
    if ctx.has("existing_placeholders"):
        c.para("Witness name: [Name]", align="left")
