"""The owner's lists: what to hide in every document, and what never to hide.

``DEFAULT_NEVER_HIDE`` holds the words the AI needs to read a contract: the parties' roles, the
document's own words, legal vocabulary, the public bodies a contract cites, months, weekdays,
currencies, countries, nationality and language adjectives ("English law"), and the single words
the language model takes for a company or a person in a contract ("VAT", "Schedule",
"Signature"). ``UserLists`` are the owner's own lists, kept for every document in the data
folder's ``lists.json``; ``CaseLists`` are the lists of one case, with the terms its contracts
define ("the Supplier", "Business Day"), which stay visible too.

An always-hide entry is a value to hide wherever it stands, as ``[CUSTOM_N]``. Written
``TYPE:value``, with TYPE one of the twelve placeholder types in any case, the value is hidden as
that type instead: ``COMPANY:Falcon Freight`` hides Falcon Freight as a company. Anything else
before a colon is part of the value ("Note: keep" is hidden as it is).

``is_never_hide`` tells whether a text is a never-hide term. A term matches whatever its case,
spacing and punctuation, in the singular and the plural, with or without a leading "the" and a
possessive "'s". A document word with its reference ("SCHEDULE 1", "Clause 4.2", "1.2 Clause",
"Annex II") is never hidden either, nor is a date in words ("25 June 2026"), nor a standard with
its number ("ISO 9001", "EN 1090"). A text that holds a term but is longer than it is no term:
"Supplier Logistics Ltd" is a name. The names found in a document beat its defined terms: after
``"Acme" means Acme Supplies Ltd`` the term "Acme" is still a name to hide. The owner's own
never-hide lists and the defaults always win.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from themask.errors import MaskError
from themask.model import PlaceholderType
from themask.textnorm import normalize


def _terms(text: str) -> frozenset[str]:
    """The terms in ``text``, which lists them separated by commas."""
    return frozenset(term.strip() for term in text.split(",") if term.strip())


# The parties' roles.
_ROLES = _terms(
    """
    Supplier, Buyer, Seller, Purchaser, Customer, Client, Vendor, Contractor, Subcontractor,
    Sub-contractor, Consultant, Service Provider, Provider, Licensor, Licensee, Lessor, Lessee,
    Landlord, Tenant, Employer, Employee, Worker, Lender, Borrower, Guarantor, Distributor,
    Reseller, Agent, Principal, Manufacturer, Producer, Carrier, Shipper, Consignee, Consignor,
    Party, Parties, Other Party, First Party, Second Party, Disclosing Party, Receiving Party,
    Discloser, Recipient, Data Controller, Data Processor, Controller, Processor, Sub-processor,
    Joint Controller, Data Subject, Data Exporter, Data Importer, Supervisory Authority,
    Beneficiary, Affiliate, Group Company, Subsidiary, Holding Company, Parent Company, Company,
    Group, Supplier Group, Buyer Group, Customer Group, Representative, Authorised Representative,
    Authorised Signatory, Signatory, Third Party, Personnel, Staff, Supplier Personnel, Customer
    Personnel
    """
)
# The document's own words: what the contract calls itself, its parts, labels and headings.
_DOCUMENT_WORDS = _terms(
    """
    Agreement, Contract, Deed, Master Agreement, Framework Agreement, Supply Agreement, Services
    Agreement, Service Agreement, Non-Disclosure Agreement, NDA, Data Processing Agreement, DPA,
    Order, Purchase Order, Order Form, Statement of Work, SOW, Schedule, Annex, Appendix, Exhibit,
    Attachment, Addendum, Amendment, Side Letter, Clause, Sub-clause, Section, Article, Paragraph,
    Recital, Background, Definitions, Interpretation, Preamble, Part, Chapter, Page, Table, Item,
    Heading, Contents, Index, Signature, Signatures, Signature Page, Execution Page, Cover Page,
    Execution, Title, Name, Date, Place, Signed, Witness, Attention, Notice, Notices, Confidential,
    Strictly Confidential, Draft, Final, Version, Copy, Original, Total, Subtotal, Grand Total,
    Amount, Price, Prices, Total Price, Contract Price, Purchase Price, Unit Price, Price List,
    Fee, Fees, Charges, Charge, Rate, Rates, Invoice, Discount, Rebate, Payment, Payment Terms,
    Deposit, Site, Premises, Territory, City, Country, Address, Registered Office, Postcode, Post
    Code, Zip Code, Telephone, Phone, Mobile, Fax, Email, E-mail, Website, VAT, VAT Number,
    IBAN, BIC, SWIFT, Account, Account Number, Bank, Bank Details, Reference, Goods, Services,
    Products, Product, Deliverables, Specification, Specifications, Documentation, Materials,
    Equipment, Software, Hardware, Term, Initial Term, Renewal Term, Effective Date, Commencement
    Date, Start Date, End Date, Expiry Date, Delivery Date, Delivery, Delivery Point, Business
    Day, Working Day, Month, Year, Quarter, Week, Contract Year, Service Levels, Service Level,
    Service Credits, KPI, Key Performance Indicators, Change Control, Change Request, Project,
    Programme, Purpose, Permitted Purpose, Scope, Forecast, Minimum Order Quantity, MOQ, Operative
    Provisions, Agreed Terms, General, Miscellaneous, Pricing, Invoicing, Duration, Commencement,
    Terms of Use, Terms and Conditions, General Terms and Conditions, Long Stop Date, Bank Holiday,
    Public Holiday, Performance Bond, Parent Company Guarantee, Grant of Licence, Licence, Licences
    """
)
# Legal vocabulary, and the delivery terms (Incoterms) a supply contract quotes.
_LEGAL_WORDS = _terms(
    """
    Force Majeure, Force Majeure Event, Confidential Information, Confidentiality, Intellectual
    Property, Intellectual Property Rights, IPR, Data Protection, Data Protection Legislation, Data
    Protection Laws, Data Protection Law, Applicable Law, Applicable Laws, Laws, Legislation,
    Regulation, Regulations, Directive, GDPR, UK GDPR, EU GDPR, General Data Protection
    Regulation, Data Protection Act, Data Protection Act 2018, Personal Data, Special Category
    Data, Personal Data Breach, Data Breach, Processing, Standard Contractual Clauses, SCCs,
    Technical and Organisational Measures, Security Measures, Liability, Limitation of Liability,
    Losses, Damages, Indemnity, Indemnities, Warranty, Warranties, Representations, Governing Law,
    Jurisdiction, Arbitration, Mediation, Dispute Resolution, Termination, Expiry, Insolvency
    Event, Insolvency, Change of Control, Good Industry Practice, Anti-Bribery Laws, Bribery Act,
    Bribery Act 2010, Modern Slavery Act, Modern Slavery Act 2015, Companies Act, Companies Act
    2006, Sanctions, Material Breach, Breach, Default, Remedy, Remedies, Waiver, Severance,
    Severability, Entire Agreement, Counterparts, Assignment, Subcontracting, Audit, Audit Rights,
    Records, Insurance, Retention of Title, Risk, Acceptance, Rejection, Defects, Non-Solicitation,
    Exclusivity, Compliance, Anti-Corruption, Export Control, Business Continuity, Exit Plan,
    Incoterms, Ex Works, EXW, FCA, CPT, CIP, DAP, DPU, DDP, FAS, FOB, CFR, CIF
    """
)
# The public bodies a contract cites (the regulators, courts, central banks and registers its
# clauses refer to): never one of the parties.
_PUBLIC_BODIES = _terms(
    """
    European Commission, European Central Bank, ECB, Bank of England, European Data Protection
    Board, EDPB, European Data Protection Supervisor, Information Commissioner, Information
    Commissioner's Office, ICO, Data Protection Commission, Autoriteit Persoonsgegevens, Court of
    Justice of the European Union, CJEU, European Parliament, Council of the European Union, HM
    Revenue and Customs, HMRC, Companies House, Chamber of Commerce, Netherlands Chamber of
    Commerce, Kamer van Koophandel, KvK, Handelsregister, International Chamber of Commerce, ICC,
    London Court of International Arbitration, LCIA, Netherlands Arbitration Institute, Financial
    Conduct Authority, FCA, Competition and Markets Authority, CMA, High Court, High Court of
    Justice, Court of Appeal, Supreme Court, County Court, Commercial Court, District Court
    """
)
_MONTHS = _terms(
    "January, February, March, April, May, June, July, August, September, October, November,"
    " December"
)
_WEEKDAYS = _terms("Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday")
_CURRENCIES = _terms(
    """
    Euro, Euros, Pound, Pounds, Pound Sterling, Pounds Sterling, Sterling, British Pound, Dollar,
    Dollars, US Dollar, US Dollars, Swiss Franc, Swiss Francs, Franc, Francs, Turkish Lira, Lira,
    Yen, Japanese Yen, Yuan, Renminbi, Krona, Kronor, Krone, Kroner, Danish Krone, Norwegian
    Krone, Swedish Krona, Zloty, Polish Zloty, Forint, Koruna, Czech Koruna, Romanian Leu,
    Australian Dollar, Canadian Dollar, EUR, GBP, USD, CHF, JPY, CNY, RMB, SEK, NOK, DKK, PLN,
    CZK, HUF, RON, BGN, TRY, AUD, CAD, NZD, SGD, HKD, INR, ZAR, AED, SAR, ISK
    """
)
# Countries, and the unions and areas a contract names. Left out: names that are as often a
# person's first name (Jordan, Chad, Georgia), which must never stop a name from being hidden.
_COUNTRIES = _terms(
    """
    Afghanistan, Albania, Algeria, Andorra, Angola, Argentina, Armenia, Australia, Austria,
    Azerbaijan, Bahamas, Bahrain, Bangladesh, Barbados, Belarus, Belgium, Belize, Benin, Bhutan,
    Bolivia, Bosnia and Herzegovina, Botswana, Brazil, Brunei, Bulgaria, Burkina Faso, Burundi,
    Cabo Verde, Cape Verde, Cambodia, Cameroon, Canada, Central African Republic, Chile, China,
    Colombia, Comoros, Congo, Costa Rica, Ivory Coast, Croatia, Cuba, Cyprus, Czechia, Czech
    Republic, Denmark, Djibouti, Dominican Republic, Ecuador, Egypt, El Salvador, Equatorial
    Guinea, Eritrea, Estonia, Eswatini, Ethiopia, Fiji, Finland, France, Gabon, Gambia, Germany,
    Ghana, Greece, Grenada, Guatemala, Guinea, Guyana, Haiti, Honduras, Hungary, Iceland, India,
    Indonesia, Iran, Iraq, Ireland, Israel, Italy, Jamaica, Japan, Kazakhstan, Kenya, Kosovo,
    Kuwait, Kyrgyzstan, Laos, Latvia, Lebanon, Lesotho, Liberia, Libya, Liechtenstein, Lithuania,
    Luxembourg, Madagascar, Malawi, Malaysia, Maldives, Mali, Malta, Mauritania, Mauritius, Mexico,
    Moldova, Monaco, Mongolia, Montenegro, Morocco, Mozambique, Myanmar, Namibia, Nepal,
    Netherlands, New Zealand, Nicaragua, Niger, Nigeria, North Korea, North Macedonia, Norway,
    Oman, Pakistan, Palestine, Panama, Papua New Guinea, Paraguay, Peru, Philippines, Poland,
    Portugal, Qatar, Romania, Russia, Russian Federation, Rwanda, San Marino, Saudi Arabia,
    Senegal, Serbia, Seychelles, Sierra Leone, Singapore, Slovakia, Slovenia, Somalia, South
    Africa, South Korea, Korea, South Sudan, Spain, Sri Lanka, Sudan, Suriname, Sweden,
    Switzerland, Syria, Taiwan, Tajikistan, Tanzania, Thailand, Togo, Trinidad and Tobago, Tunisia,
    Turkey, Türkiye, Turkmenistan, Uganda, Ukraine, United Arab Emirates, UAE, United Kingdom, UK,
    Great Britain, Britain, England, Wales, Scotland, Northern Ireland, England and Wales, United
    States, United States of America, USA, US, America, Uruguay, Uzbekistan, Venezuela, Vietnam,
    Viet Nam, Yemen, Zambia, Zimbabwe, Holland, Hong Kong, Macau, Puerto Rico, Greenland, Faroe
    Islands, Gibraltar, Jersey, Guernsey, Isle of Man, European Union, EU, European Economic Area,
    EEA, Europe, Benelux, Scandinavia
    """
)
# Nationality and language adjectives, as "English law", "the Dutch courts" and "German-language"
# use them (ruling R53). A person named by one of them ("Tom English") is still hidden where the
# word stands as their name, but the group is marked for checking (rulings R42, R50).
_NATIONALITIES = _terms(
    """
    English, British, Scottish, Welsh, Irish, Northern Irish, Dutch, Flemish, German, French,
    Belgian, Luxembourgish, Swiss, Austrian, Italian, Spanish, Portuguese, Catalan, Basque, Greek,
    Danish, Swedish, Norwegian, Finnish, Icelandic, Polish, Czech, Slovak, Slovenian, Croatian,
    Serbian, Hungarian, Romanian, Bulgarian, Estonian, Latvian, Lithuanian, Maltese, Cypriot,
    Turkish, Russian, Ukrainian, European, American, Canadian, Mexican, Brazilian, Argentinian,
    Chilean, Australian, Chinese, Japanese, Korean, Indian, Pakistani, Singaporean, Malaysian,
    Indonesian, Thai, Vietnamese, Arabic, Arab, Emirati, Saudi, Israeli, Hebrew, Egyptian,
    Moroccan, Nigerian, Kenyan, South African, Latin, Mandarin, Cantonese, Hindi, Persian
    """
)
# The single words the language model takes for a company or a person in a contract: labels,
# headings and codes.
_MISTAKEN_FOR_NAMES = _terms(
    """
    VAT, IBAN, BIC, SWIFT, EUR, GBP, USD, Schedule, Appendix, Annex, Exhibit, Clause, Section,
    Article, Recital, City, Country, Date, Signature, Title, Name, Attention, Confidential, Draft,
    Page, Total, Subtotal, Amount, Price, Site, Sub, Time, Assistance, Operations, Finance, Sales,
    Marketing, Procurement, Purchasing, Legal, Accounts, Treasury, Human Resources, HR
    """
)

DEFAULT_NEVER_HIDE: frozenset[str] = (
    _ROLES
    | _DOCUMENT_WORDS
    | _LEGAL_WORDS
    | _PUBLIC_BODIES
    | _MONTHS
    | _WEEKDAYS
    | _CURRENCIES
    | _COUNTRIES
    | _NATIONALITIES
    | _MISTAKEN_FOR_NAMES
)

# The document words a reference follows, and the reference itself: a number ("1", "4.2",
# "28(3)"), a number with a letter ("1A"), a letter ("A") or a roman numeral ("II").
_REFERENCE_WORDS = _terms(
    """
    Schedule, Annex, Appendix, Exhibit, Attachment, Addendum, Clause, Sub-clause, Section,
    Article, Paragraph, Recital, Part, Chapter, Table, Item, Party, Annexure, Figure
    """
)
_REFERENCE = re.compile(
    r"\(?(?:\d{1,3}(?:\.\d{1,3})*[A-Za-z]?|[A-Za-z]|[IVXLCDM]{1,8}|[ivxlcdm]{1,8})\)?"
    r"(?:\([A-Za-z0-9]{1,4}\))*\.?"
)

# A page label as a footer or a field shows it: "Page 3", "Page 3 of 12", "Seite 2 von 5",
# "Pagina 3 van 7", "Bladzijde 4", and a field's own code, which a PDF or a Word export may leave
# as text: "Page PAGE1", "PAGE", "NUMPAGES", "Seite PAGE2 von NUMPAGES".
_PAGE_FIELD = r"(?:NUM|SECTION)?PAGES?\d*|PAGEREF\w*"
_PAGE_NUMBER = rf"(?:\d{{1,4}}|[IVX]{{2,4}}|[ivx]{{2,4}}|{_PAGE_FIELD})"
_PAGE_LABEL = re.compile(
    rf"(?i:(?:pages?|seiten?|pagina'?s?|p[aá]ginas?|bladzijden?|blz|pág)\.?[ \N{{NO-BREAK SPACE}}]+)"
    rf"{_PAGE_NUMBER}(?:[ \N{{NO-BREAK SPACE}}]+(?i:of|von|van|de|sur|di|din|av|af)"
    rf"[ \N{{NO-BREAK SPACE}}]+{_PAGE_NUMBER})?"
    rf"|(?:{_PAGE_FIELD})(?:[ \N{{NO-BREAK SPACE}}]+(?i:of|von|van|de|sur)"
    rf"[ \N{{NO-BREAK SPACE}}]+(?:{_PAGE_FIELD}|\d{{1,4}}))?"
)

_LEADING_THE = re.compile(r"(?i:the)\s+")
_POSSESSIVE = re.compile(r"['\N{RIGHT SINGLE QUOTATION MARK}][sS]\Z")
_EDGES = re.compile(r"\A[\W_]+|[\W_]+\Z")


def term_key(text: str) -> str:
    """``text`` reduced to how a term is compared: without a leading "the", a possessive "'s",
    the punctuation at its ends, and then normalised (case, spacing and punctuation gone).
    "the Buyer's" and "BUYER" both give "buyer".
    """
    text = _POSSESSIVE.sub("", text.strip())
    text = _EDGES.sub("", text)
    the = _LEADING_THE.match(text)
    if the:
        text = text[the.end() :]
    return normalize(text)


def _number_forms(key: str) -> set[str]:
    """The singular and plural forms a term key may stand for: "party", "parties", "goods"."""
    forms = {key, key + "s", key + "es"}
    if key.endswith("ies"):
        forms.add(key[:-3] + "y")
    if key.endswith("es"):
        forms.add(key[:-2])
    if key.endswith("s"):
        forms.add(key[:-1])
    if key.endswith("y"):
        forms.add(key[:-1] + "ies")
    return forms


class _Terms:
    """A set of terms, compared by ``term_key`` in the singular and the plural."""

    def __init__(self, terms: Iterable[str]) -> None:
        self._keys = frozenset(key for key in map(term_key, terms) if key)

    def has(self, key: str) -> bool:
        return not self._keys.isdisjoint(_number_forms(key))


_DEFAULTS = _Terms(DEFAULT_NEVER_HIDE)
# The single words the contract vocabulary is built of ("Confidential" and "Information" of
# "Confidential Information"; "Receiving" of "Receiving Party"): roles, document words and legal
# words only, never a place, a month or a body, which are names in other combinations.
_VOCABULARY_KEYS = frozenset(
    key
    for term in _ROLES | _DOCUMENT_WORDS | _LEGAL_WORDS
    for key in map(term_key, term.split())
    if key
)
_PLACE_KEYS = frozenset(
    map(term_key, _PUBLIC_BODIES | _MONTHS | _WEEKDAYS | _CURRENCIES | _COUNTRIES | _NATIONALITIES)
)
_REFERENCE_TERMS = _Terms(_REFERENCE_WORDS)


def _is_reference(text: str) -> bool:
    """Whether ``text`` is a document word with its reference ("SCHEDULE 1", "Clause 4.2",
    "Annex II"), a clause number before the word ("1.2 Clause", as a heading may read), or a page
    label ("Page 3 of 12", "Seite 2 von 5", "Page PAGE1", "NUMPAGES").
    """
    stripped = text.strip().strip("-\N{EN DASH}\N{EM DASH}|.:,() ")
    if _PAGE_LABEL.fullmatch(stripped):
        return True
    words = text.split()
    if len(words) < 2:
        return False
    if _REFERENCE.fullmatch(words[-1]) and _REFERENCE_TERMS.has(term_key(" ".join(words[:-1]))):
        return True
    number_first = words[0][:1].isdigit() and _REFERENCE.fullmatch(words[0]) is not None
    return number_first and _REFERENCE_TERMS.has(term_key(" ".join(words[1:])))


# A standard with its number: "ISO 9001", "ISO 9001:2015", "ISO/IEC 27001", "BS EN 1176-1".
_STANDARD = re.compile(
    r"(?:ISO|EN|IEC|DIN|BS|NEN|ASTM|ANSI|IEEE)(?:[/ ](?:IEC|EN|ISO|TS|TR|PAS))*"
    r"[ \N{NO-BREAK SPACE}]?\d{1,6}(?:[\-:.]\d{1,4})*"
)


def _is_standard(text: str) -> bool:
    """Whether ``text`` is a standard with its number, which a contract cites: "ISO 9001"."""
    return _STANDARD.fullmatch(text.strip()) is not None


_MONTH_KEYS = frozenset(map(term_key, _MONTHS))
_WEEKDAY_KEYS = frozenset(map(term_key, _WEEKDAYS))
# The other words of a date: a day ("25", "1st"), a year ("2026"), and "of" or "the".
_DATE_WORD = re.compile(r"(?i:\d{1,2}(?:st|nd|rd|th)?|(?:19|20)\d{2}|of|the)")


def _is_date(text: str) -> bool:
    """Whether ``text`` is a date written in words, which stays visible: "June 2026", "25 June
    2026", "June 25, 2026", "Monday, 1 June 2026". "April Jones" is a name.
    """
    words = text.replace(",", " ").split()
    keys = [term_key(word) for word in words]
    return (
        len(words) >= 2
        and any(key in _MONTH_KEYS for key in keys)
        and all(
            key in _MONTH_KEYS or key in _WEEKDAY_KEYS or _DATE_WORD.fullmatch(word)
            for word, key in zip(words, keys, strict=True)
        )
    )


@dataclass
class CaseLists:
    """The lists of one case: values to hide and to keep in its documents only, and the terms
    its documents define, which the analysis collects.
    """

    always_hide: list[str]
    never_hide: list[str]
    defined_terms: set[str]


def never_hide_check(
    user: UserLists, case: CaseLists, names: Iterable[str] = ()
) -> Callable[[str], bool]:
    """``is_never_hide`` for many texts: a function that tells whether a text is never hidden.

    ``names`` are the names of people and companies found in the document, in any spelling. A
    defined term that is one of them is a name and does not count as a term; the owner's lists
    and the defaults always count.
    """
    explicit = _Terms([*user.never_hide, *case.never_hide])
    defined = _Terms(case.defined_terms)
    name_keys = frozenset(map(term_key, names))

    def check(text: str) -> bool:
        key = term_key(text)
        if not key:
            return False
        if _DEFAULTS.has(key) or explicit.has(key) or _is_reference(text) or _is_date(text):
            return True
        if _is_standard(text):
            return True
        return defined.has(key) and key not in name_keys

    return check


def is_month(text: str) -> bool:
    """Whether ``text`` is the name of a month ("May", "MARCH")."""
    return term_key(text) in _MONTH_KEYS


def is_default_term(text: str) -> bool:
    """Whether ``text`` is one of ``DEFAULT_NEVER_HIDE``, matched the way ``is_never_hide`` matches."""
    key = term_key(text)
    return bool(key) and _DEFAULTS.has(key)


def on_never_hide_list(text: str, user: UserLists, case: CaseLists) -> bool:
    """Whether ``text`` is on the owner's or the case's own never-hide list."""
    key = term_key(text)
    return bool(key) and _Terms([*user.never_hide, *case.never_hide]).has(key)


def is_never_hide(text: str, user: UserLists, case: CaseLists) -> bool:
    """Whether ``text`` is a term that is never hidden: one of the defaults, on the owner's or the
    case's never-hide list, or a term the case's documents define. See the module for how terms
    are matched.
    """
    return never_hide_check(user, case)(text)


_TYPED_ENTRY = re.compile(r"\s*(?P<type>[A-Za-z]+)\s*:(?P<value>.*)", re.DOTALL)


def always_hide_entry(entry: str) -> tuple[PlaceholderType, str]:
    """The type and the value of an always-hide entry: "Project Falcon" is a CUSTOM value,
    "COMPANY:Falcon Freight" the company Falcon Freight. The value has no spaces at its ends and
    may be blank ("ID:").
    """
    typed = _TYPED_ENTRY.fullmatch(entry)
    if typed is not None and typed["type"].upper() in PlaceholderType.__members__:
        return PlaceholderType(typed["type"].upper()), typed["value"].strip()
    return PlaceholderType.CUSTOM, entry.strip()


def _lists_error(path: Path) -> MaskError:
    return MaskError(
        f"The MASK cannot read its always-hide and never-hide lists in {path}. Repair or delete"
        " that file, then start The MASK again."
    )


def _entries(data: dict[str, object], name: str) -> list[str]:
    entries = data.get(name, [])
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise TypeError(f"{name} is not a list of texts.")
    return list(entries)


@dataclass
class UserLists:
    """The owner's own lists, for every document: values to always hide and to never hide.

    A value is on one of the two lists at a time: adding it to one takes it off the other.
    """

    always_hide: list[str]
    never_hide: list[str]

    @classmethod
    def load(cls, path: Path) -> UserLists:
        """The lists saved at ``path``; empty lists when there is no file yet.

        Raises MaskError for a file that is not the lists ``save`` writes (not UTF-8, not JSON,
        or not two lists of texts). A damaged file is never taken for empty lists: the owner's
        always-hide values would silently stop being hidden.
        """
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return cls([], [])
        try:
            data = json.loads(content.decode("utf-8"))
            if not isinstance(data, dict):
                raise TypeError("The lists file holds no object.")
            return cls(_entries(data, "always_hide"), _entries(data, "never_hide"))
        except (ValueError, TypeError) as error:
            raise _lists_error(path) from error

    def save(self, path: Path) -> None:
        """Write the lists to ``path`` as JSON, readable by the owner only.

        The lists go to a temporary file next to ``path`` first, which then replaces it, so a
        crash or a full disk never leaves half a file in place of the lists.
        """
        content = json.dumps(
            {"always_hide": self.always_hide, "never_hide": self.never_hide},
            ensure_ascii=False,
            indent=2,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # mkstemp makes the file readable and writable by its owner only.
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".lists-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def add_always(self, value: str) -> None:
        """Hide ``value`` (an always-hide entry) in every document from now on."""
        kind, text = always_hide_entry(value)
        if not text:
            raise ValueError("A blank value cannot be added to the always-hide list.")
        key = term_key(text)
        self.never_hide = [term for term in self.never_hide if term_key(term) != key]
        if not any(_same_entry(entry, kind, key) for entry in self.always_hide):
            self.always_hide.append(value.strip())

    def add_never(self, value: str) -> None:
        """Never hide ``value`` from now on."""
        key = term_key(value)
        if not value.strip():
            raise ValueError("A blank value cannot be added to the never-hide list.")
        self.always_hide = [e for e in self.always_hide if term_key(always_hide_entry(e)[1]) != key]
        if not any(term_key(term) == key for term in self.never_hide):
            self.never_hide.append(value.strip())

    def remove_always(self, value: str) -> None:
        """Take ``value`` off the always-hide list; a value that is not on it is no error."""
        kind, text = always_hide_entry(value)
        key = term_key(text)
        self.always_hide = [e for e in self.always_hide if not _same_entry(e, kind, key)]

    def remove_never(self, value: str) -> None:
        """Take ``value`` off the never-hide list; a value that is not on it is no error."""
        key = term_key(value)
        self.never_hide = [term for term in self.never_hide if term_key(term) != key]


def _same_entry(entry: str, kind: PlaceholderType, key: str) -> bool:
    """Whether the always-hide ``entry`` hides the value with term key ``key`` as ``kind``."""
    entry_kind, entry_text = always_hide_entry(entry)
    return entry_kind is kind and term_key(entry_text) == key


def is_vocabulary_word(text: str) -> bool:
    """Whether the single word ``text`` is one of the plain words contracts are written in: a
    word of a default role, document word or legal term ("Personal", "Information", "Receiving").
    A place, a month and a body are not (``Bank of Ireland`` is a name).
    """
    key = term_key(text)
    if not key or " " in key:
        return False
    forms = _number_forms(key)
    return _PLACE_KEYS.isdisjoint(forms) and not _VOCABULARY_KEYS.isdisjoint(forms)


def is_place_term(text: str) -> bool:
    """Whether ``text`` is a country, nationality, currency, month, weekday or public body."""
    key = term_key(text)
    return bool(key) and not _PLACE_KEYS.isdisjoint(_number_forms(key))
