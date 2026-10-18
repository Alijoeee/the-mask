"""The long schedules that make a contract run to about thirty pages.

They are built from a pool of ordinary contract sentences, two or three to a numbered paragraph,
with the parties' defined terms and a few wording choices filled in. The sentences are dealt from
a shuffled deck, so the whole pool is used before any sentence comes back. Apart from one governance paragraph that names the contract
managers and one performance target, they hold no secrets.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from tools.corpus.clauses import pct
from tools.corpus.compose import Ctx
from tools.corpus.model import Block, Paragraph, Span, Table, TextBox

_TITLES = {
    "supply": (
        "Quality and specification",
        "Forecasting and ordering",
        "Key performance indicators",
        "Business continuity",
        "Exit management",
        "Governance",
        "Change control",
        "Sustainability",
        "Audit and records",
    ),
    "services": (
        "Service description",
        "Service levels and reporting",
        "Governance",
        "Change control",
        "Business continuity",
        "Exit management",
        "Health and safety",
        "Audit and records",
        "Sustainability",
    ),
    "nda": (
        "Handling of Confidential Information",
        "Security of information",
        "Governance",
        "Audit and records",
    ),
    "dpa": (
        "Technical and organisational measures",
        "Requests from data subjects",
        "Breach response plan",
        "Audit procedure",
        "Records of processing",
        "Management of Sub-processors",
        "Return and deletion of data",
        "Governance",
        "Change control",
    ),
}
_SUBHEADINGS = (
    "Purpose",
    "Scope",
    "Responsibilities",
    "Procedure",
    "Reporting",
    "Meetings",
    "Records",
    "Review",
    "Escalation",
    "Costs",
    "Timetable",
    "Standards",
)

# {P}/{C}: the provider and the customer ("the Supplier", "the Buyer"); {Pc}/{Cc} the same with a
# capital; {Ps}/{Cs} their possessives. {days}, {period} and {manager} vary the wording.
_COMMON = (
    (
        "{Pc} shall maintain a documented quality management system and shall make it available to"
        " {C} on reasonable request."
    ),
    (
        "Each party shall appoint a {manager} who shall be the first point of contact for all"
        " day-to-day matters under this Agreement."
    ),
    (
        "The {manager}s of the parties shall meet at least once in each {period} to review"
        " performance against the key performance indicators."
    ),
    (
        "{Pc} shall keep complete and accurate records of all activities carried out under this"
        " Agreement for at least six years after the date on which they were created."
    ),
    (
        "Any change to the scope of this Agreement shall be agreed in writing using the change"
        " control procedure in this Schedule."
    ),
    (
        "{Cc} may request a change by giving {P} a written change request describing the proposed"
        " change in reasonable detail."
    ),
    (
        "Within {days} Business Days of receiving a change request, {P} shall provide an impact"
        " assessment describing the effect of the change on the timetable, the charges and the risks."
    ),
    (
        "No change shall take effect until it has been recorded in a change note signed by an"
        " authorised representative of each party."
    ),
    (
        "{Pc} shall ensure that all personnel engaged in the performance of this Agreement are"
        " suitably skilled, experienced and qualified."
    ),
    (
        "{Pc} shall comply with the reasonable site rules and security procedures notified to it by"
        " {C} from time to time."
    ),
    (
        "Each party shall comply with all applicable laws relating to anti-bribery and"
        " anti-corruption and shall maintain adequate procedures to prevent bribery."
    ),
    (
        "{Pc} shall maintain a business continuity plan and shall test it at least once in every"
        " twelve months."
    ),
    (
        "If a business continuity event occurs, {P} shall put the business continuity plan into"
        " effect without delay and shall keep {C} informed of progress."
    ),
    (
        "{Pc} shall not subcontract any of its obligations without the prior written consent of {C},"
        " which shall not be unreasonably withheld."
    ),
    (
        "{Pc} remains responsible for the acts and omissions of its subcontractors as if they were"
        " its own."
    ),
    (
        "On expiry or termination of this Agreement, {P} shall cooperate fully with {C} to ensure an"
        " orderly transfer of responsibilities to {C} or to a replacement provider."
    ),
    (
        "{Pc} shall deliver an exit plan within three months of the date of this Agreement and shall"
        " review and update it at least once a year."
    ),
    (
        "During the exit period, {P} shall continue to perform its obligations in accordance with"
        " this Agreement."
    ),
    (
        "Each party shall promptly notify the other of any actual or expected delay in the"
        " performance of its obligations."
    ),
    (
        "The parties shall try in good faith to resolve any dispute arising out of or in connection"
        " with this Agreement through negotiation between their {manager}s."
    ),
    (
        "If the {manager}s cannot resolve the dispute within {days} Business Days, either party may"
        " refer it to a senior executive of each party."
    ),
    (
        "Nothing in this Schedule prevents either party from seeking urgent injunctive relief from a"
        " court of competent jurisdiction."
    ),
    (
        "{Pc} shall provide a monthly performance report showing its performance against each key"
        " performance indicator during the previous month."
    ),
    (
        "If {P} fails to meet a key performance indicator in any two consecutive months, the parties"
        " shall agree a remediation plan within {days} Business Days."
    ),
    (
        "{Pc} shall carry out the remediation plan in accordance with its terms and shall report on"
        " progress at each review meeting."
    ),
    (
        "Repeated failure to meet the key performance indicators is a material breach of this"
        " Agreement."
    ),
    (
        "{Cc} shall give {P} such access to its premises, systems and personnel as {P} reasonably"
        " requires to perform its obligations."
    ),
    (
        "{Pc} shall ensure that any equipment it brings onto {Cs} premises is safe, properly"
        " maintained and fit for purpose."
    ),
    (
        "Each party shall maintain in force, with a reputable insurer, adequate insurance to cover the"
        " liabilities that may arise under or in connection with this Agreement."
    ),
    "{Pc} shall, on request, provide {C} with copies of its insurance certificates.",
    (
        "Each party shall take reasonable steps to ensure that its systems are protected against"
        " viruses and other malicious software."
    ),
    (
        "{Pc} shall notify {C} without undue delay on becoming aware of any security incident"
        " affecting {Cs} data or premises."
    ),
    (
        "All documents, information and materials provided by {C} remain the property of {C} and"
        " shall be returned on request."
    ),
    (
        "{Pc} shall not use {Cs} name or trade marks in any publicity material without {Cs} prior"
        " written consent."
    ),
    (
        "Any audit shall be carried out on reasonable notice, during normal business hours and in a"
        " way that keeps disruption to {Ps} business to a minimum."
    ),
    (
        "Each party shall bear its own costs of any audit unless the audit reveals a material breach,"
        " in which case {P} shall bear the reasonable costs of the audit."
    ),
    (
        "The parties shall review this Schedule at least once a year and shall agree in writing any"
        " updates that are required."
    ),
    (
        "{Pc} shall comply with {Cs} supplier code of conduct as updated from time to time and"
        " notified to {P} in writing."
    ),
    (
        "{Pc} shall ensure that its supply chain is free from modern slavery and human trafficking"
        " and shall report each year on the steps it has taken."
    ),
    (
        "Where this Schedule requires a party to use reasonable endeavours, that party is not"
        " required to act against its own commercial interests."
    ),
    (
        "Time is not of the essence for the performance of any obligation in this Schedule unless"
        " this Schedule expressly says otherwise."
    ),
    (
        "A failure or delay by a party to exercise any right or remedy under this Schedule shall not"
        " be a waiver of that right or remedy."
    ),
    (
        "If any provision of this Schedule is found to be invalid or unenforceable, the remaining"
        " provisions shall continue in full force and effect."
    ),
    (
        "Each party shall keep the other informed of any matter that may materially affect the"
        " performance of this Agreement."
    ),
    (
        "{Pc} shall provide reasonable training to {Cs} personnel on the use of any new process"
        " introduced under this Schedule."
    ),
    (
        "All reports under this Schedule shall be provided in electronic form, in a format reasonably"
        " specified by {C}."
    ),
    (
        "The governance board shall consist of two representatives of each party and shall meet at"
        " least twice a year."
    ),
    (
        "Minutes of each governance meeting shall be circulated within {days} Business Days and"
        " approved at the next meeting."
    ),
    "Decisions of the governance board shall be unanimous and shall be recorded in writing.",
    (
        "{Cc} may withhold approval of any deliverable that does not meet the agreed acceptance"
        " criteria, giving its reasons in writing."
    ),
    (
        "{Pc} shall correct any deficiency identified by {C} and resubmit the deliverable for approval"
        " within {days} Business Days."
    ),
    (
        "Each party shall ensure that its personnel observe the confidentiality obligations of this"
        " Agreement."
    ),
    (
        "{Pc} shall keep a register of all risks and issues relating to this Agreement and shall"
        " share it with {C} each {period}."
    ),
    (
        "The parties shall jointly agree a continuous improvement plan each year, with measurable"
        " targets."
    ),
    (
        "{Pc} shall propose ways of reducing cost or improving quality and shall share any agreed"
        " savings fairly with {C}."
    ),
    (
        "Neither party shall make any public announcement about this Agreement without the prior"
        " written approval of the other."
    ),
    "{Cc} shall pay any undisputed part of an invoice even if another part of it is disputed.",
    "Disputed amounts shall be resolved under the dispute resolution procedure in this Schedule.",
    (
        "{Pc} shall, at its own cost, obtain and maintain all licences, permits and consents it needs"
        " to perform its obligations."
    ),
)
_OPERATIONS = (
    (
        "{Pc} shall operate an environmental management system and shall work with {C} to reduce"
        " packaging waste and transport emissions."
    ),
    (
        "{Pc} shall label each consignment with the delivery address, the order reference and the"
        " number of packages."
    ),
    (
        "Goods damaged in transit shall be reported to {P} within {days} Business Days of delivery,"
        " with photographs where possible."
    ),
    "{Pc} shall rotate stock on a first-expiry, first-out basis unless {C} instructs otherwise.",
    (
        "{Pc} shall carry out a full stock count at least once in each {period} and shall reconcile"
        " any differences with {C}."
    ),
    (
        "Each delivery shall be accompanied by a delivery note listing the goods delivered and any"
        " goods still outstanding."
    ),
)
_DATA = (
    (
        "{Pc} shall keep a record of all categories of processing activities carried out on behalf"
        " of {C}."
    ),
    (
        "{Pc} shall ensure that personal data is pseudonymised wherever this is possible without"
        " affecting the Services."
    ),
    (
        "Access to personal data shall be limited to personnel who need it to perform the Services"
        " and shall be reviewed each {period}."
    ),
    (
        "{Pc} shall test, assess and evaluate the effectiveness of its technical and organisational"
        " measures at least once a year."
    ),
    "{Pc} shall forward to {C}, without undue delay, any request it receives from a data subject.",
    (
        "{Pc} shall not respond to a request from a data subject unless {C} instructs it to do so in"
        " writing."
    ),
    (
        "Back-up copies shall be encrypted and stored in a secure location separate from the primary"
        " systems."
    ),
    (
        "{Pc} shall keep logs of access to personal data for at least twelve months and shall make"
        " them available to {C} on request."
    ),
    (
        "Where a data protection impact assessment is required, {P} shall provide {C} with all the"
        " information it reasonably needs."
    ),
    (
        "{Pc} shall ensure that any portable device holding personal data is encrypted and protected"
        " by a strong password."
    ),
)
_DAYS = ("five", "ten", "15", "20")
_PERIODS = ("month", "calendar quarter", "half-year")
_MANAGERS = ("contract manager", "account manager", "service manager")
_WORD = re.compile(r"\w+")


def _visible_spans(blocks: Iterable[Block]) -> Iterable[Span]:
    for block in blocks:
        paragraphs: Iterable[Paragraph] = ()
        if isinstance(block, Paragraph):
            paragraphs = (block,)
        elif isinstance(block, TextBox):
            paragraphs = block.paragraphs
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row:
                    yield from (s for s in cell if isinstance(s, Span))
        for p in paragraphs:
            yield from (s for s in p.inlines if isinstance(s, Span))


def word_count(blocks: Iterable[Block]) -> int:
    """The words a reader sees in ``blocks``: no tracked deletions and no hidden text."""
    return sum(
        len(_WORD.findall(s.text))
        for s in _visible_spans(blocks)
        if s.revision != "del" and not s.hidden
    )


def long_schedules(ctx: Ctx, words: int = 12_600) -> None:
    """Add schedules until the body holds at least ``words`` words of clause text."""
    c, rng = ctx.c, ctx.rng
    provider, customer = (ctx.b, ctx.a) if ctx.kind == "dpa" else (ctx.a, ctx.b)
    terms = {
        "P": f"the {provider.role}",
        "C": f"the {customer.role}",
        "Pc": f"The {provider.role}",
        "Cc": f"The {customer.role}",
        "Ps": ctx.s(f"the {provider.role}"),
        "Cs": ctx.s(f"the {customer.role}"),
    }
    pool = _COMMON + (_DATA if ctx.kind == "dpa" else _OPERATIONS)
    label = "ANNEX" if ctx.kind == "dpa" else "SCHEDULE"
    titles = _TITLES[ctx.kind]
    deck = rng.sample(pool, len(pool))  # sentences are dealt like cards, so none comes up twice
    number = 2
    while word_count(c.blocks) < words:
        title = titles[(number - 2) % len(titles)]
        if number - 2 >= len(titles):
            title += " (further provisions)"
        c.section(f"{label} {number} — {title.upper()}")
        if number == 2:
            c.heading("Contract management")
            c.clause(
                f"The governance board shall be chaired by {provider.contact.formal}, supported by"
                f" {customer.contact.initial} for {terms['C']}."
            )
            c.clause(
                "The target for performance against the key performance indicators is"
                f" {pct(ctx, '97', '98', '99')} in each month."
            )
        for heading in rng.sample(_SUBHEADINGS, rng.randrange(4, 7)):
            c.heading(heading)
            for _ in range(rng.randrange(3, 6)):
                sentences = [deck.pop() for _ in range(rng.randrange(2, 4))]
                c.clause(
                    " ".join(
                        s.format(
                            **terms,
                            days=rng.choice(_DAYS),
                            period=rng.choice(_PERIODS),
                            manager=rng.choice(_MANAGERS),
                        )
                        for s in sentences
                    )
                )
                if len(deck) < 3:  # every sentence used once: shuffle them all again
                    deck = rng.sample(pool, len(pool))
        number += 1
