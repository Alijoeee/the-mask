"""The made-up material the corpus draws on: companies, places, banks, VAT numbers and goods.

Every company name here is invented. Web and e-mail domains end in ``.example``, which is reserved
for examples and never belongs to anyone. UK telephone numbers come from Ofcom's ranges set aside
for drama; other numbers are random but valid in form. VAT numbers pass ``stdnum.eu.vat``; IBANs
are built by ``schwifty`` for real bank codes, so their check digits and BICs are right, with
random account numbers. ``test_numbers_pass_their_own_checks`` checks the IBANs, BICs, VAT and
telephone numbers of every truth file with these same libraries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Country = Literal["NL", "DE", "GB", "IE"]


@dataclass(frozen=True)
class Company:
    """A made-up company: its legal name, where it is registered and its internet domain."""

    name: str
    country: Country
    domain: str
    # A fixed bank and account number for the IBAN, for the one company later tasks name by IBAN.
    bank_account: tuple[str, str] | None = None

    @property
    def short(self) -> str:
        """The name people use in running text: the first word ("Northwind")."""
        return self.name.split()[0]

    @property
    def is_partnership(self) -> bool:
        """A limited liability partnership is not a company, and contracts say so."""
        return self.name.endswith(" LLP")


_COMPANY_LIST: tuple[Company, ...] = (
    # Netherlands
    Company(
        "Northwind Trading B.V.",
        "NL",
        "northwind.example",
        bank_account=("ABNA", "0417164300"),
    ),
    Company("Brightwater Hygiene B.V.", "NL", "brightwater-hygiene.example"),
    Company("Polderkant Packaging B.V.", "NL", "polderkant.example"),
    Company("Ambergate Foodservice N.V.", "NL", "ambergate.example"),
    Company("Veldkamp Distribution B.V.", "NL", "veldkamp-distribution.example"),
    Company("Tulpenburg Medical Supplies B.V.", "NL", "tulpenburg.example"),
    Company("Kanaalzicht Logistics B.V.", "NL", "kanaalzicht.example"),
    Company("Zuiderhaven Cold Chain B.V.", "NL", "zuiderhaven.example"),
    Company("Lindeboom Facility Services B.V.", "NL", "lindeboom-fs.example"),
    Company("Kastanje Retail Group B.V.", "NL", "kastanje.example"),
    Company("Brinkhof Property Management B.V.", "NL", "brinkhof.example"),
    Company("Oosterdok Ventures B.V.", "NL", "oosterdok.example"),
    Company("Duinrand Hospitality B.V.", "NL", "duinrand.example"),
    Company("Westerkade Insurance N.V.", "NL", "westerkade.example"),
    Company("Havenlicht Energy B.V.", "NL", "havenlicht.example"),
    Company("Oakridge Hosting B.V.", "NL", "oakridge-hosting.example"),
    # Germany
    Company("Rheinwerk Verpackung GmbH", "DE", "rheinwerk.example"),
    Company("Kronberg Medical AG", "DE", "kronberg-medical.example"),
    Company("Hanseatic Paper Products GmbH", "DE", "hanseatic-paper.example"),
    Company("Isarthal Hygiene Systems GmbH", "DE", "isarthal.example"),
    Company("Baltic Fasteners GmbH", "DE", "baltic-fasteners.example"),
    Company("Lindenhof Hotels GmbH", "DE", "lindenhof-hotels.example"),
    Company("Stellwerk Software GmbH", "DE", "stellwerk.example"),
    Company("Wendelstein Foods GmbH", "DE", "wendelstein.example"),
    Company("Altmark Medizintechnik GmbH", "DE", "altmark.example"),
    Company("Elbmarsch Data Services GmbH", "DE", "elbmarsch.example"),
    Company("Bergmann Haushaltswaren GmbH", "DE", "bergmann-hw.example"),
    Company("Elbtal Rechenzentrum GmbH", "DE", "elbtal-rz.example"),
    Company("Nordlicht Cloud GmbH", "DE", "nordlicht.example"),
    # United Kingdom
    Company("Thamesgate Catering plc", "GB", "thamesgate.example"),
    Company("Ashcombe Healthcare Ltd", "GB", "ashcombe.example"),
    Company("Calder Valley Foods Ltd", "GB", "caldervalley.example"),
    Company("Larchfield Care Group Ltd", "GB", "larchfield.example"),
    Company("Acme Supplies Ltd", "GB", "acme-supplies.example"),
    Company("Pennine Workwear Ltd", "GB", "pennine-workwear.example"),
    Company("Harbourline Retail Ltd", "GB", "harbourline.example"),
    Company("Fairhaven Fresh Foods Ltd", "GB", "fairhaven.example"),
    Company("Greystone Facilities Ltd", "GB", "greystone.example"),
    Company("Kestrel Analytics Limited", "GB", "kestrel-analytics.example"),
    Company("Marlowe Print and Packaging Ltd", "GB", "marlowe.example"),
    Company("Quayside Hotels Ltd", "GB", "quayside.example"),
    Company("Riverside Partners LLP", "GB", "riverside-partners.example"),
    Company("Kingsmead Leisure Ltd", "GB", "kingsmead.example"),
    Company("Penrose Marketing Ltd", "GB", "penrose.example"),
    Company("Eastbridge Pharmacy Group plc", "GB", "eastbridge.example"),
    Company("Glenmore Freight Limited", "GB", "glenmore.example"),
    Company("Cobalt Mail Services Ltd", "GB", "cobalt-mail.example"),
    # Ireland
    Company("Burren Logistics Limited", "IE", "burren.example"),
    Company("Corrib Cleaning Supplies Ltd", "IE", "corrib.example"),
    Company("Liffey Data Services Limited", "IE", "liffey.example"),
    Company("Merrion Payroll Services Limited", "IE", "merrion.example"),
    Company("Slaney Cloud Services Limited", "IE", "slaney.example"),
    Company("Fernleaf Payments Limited", "IE", "fernleaf.example"),
)

COMPANIES: dict[str, Company] = {c.short: c for c in _COMPANY_LIST}

# Companies a contract names besides the parties: carriers, transport subcontractors, advisers.
THIRD_PARTIES: dict[str, tuple[str, ...]] = {
    "supply": ("Glenmore", "Burren"),
    "services": ("Glenmore", "Burren"),
    "nda": ("Riverside", "Penrose"),
}
# The sub-processors of a data processing agreement, with what each does.
SUB_PROCESSORS: tuple[tuple[str, str], ...] = (
    ("Oakridge", "hosting"),
    ("Nordlicht", "hosting"),
    ("Cobalt", "e-mail delivery"),
    ("Fernleaf", "payment processing"),
)

# What a country is called where a contract says a company is registered there, and the law and
# courts the contract then chooses.
REGISTERED_IN: dict[Country, str] = {
    "NL": "the Netherlands",
    "DE": "Germany",
    "GB": "England and Wales",
    "IE": "Ireland",
}
GOVERNING_LAW: dict[Country, tuple[str, str]] = {
    "NL": ("the Netherlands", "the competent court in Amsterdam"),
    "DE": ("Germany", "the courts of Hamburg"),
    "GB": ("England and Wales", "the courts of England and Wales"),
    "IE": ("Ireland", "the courts of Ireland"),
}
CURRENCY: dict[Country, str] = {"NL": "EUR", "DE": "EUR", "GB": "GBP", "IE": "EUR"}

# --------------------------------------------------------------------------------------------
# Places: (city, lowest postcode, highest postcode or outward codes, telephone area code)
# --------------------------------------------------------------------------------------------

NL_CITIES: tuple[tuple[str, int, int, str], ...] = (
    ("Amsterdam", 1011, 1109, "20"),
    ("Rotterdam", 3011, 3089, "10"),
    ("Utrecht", 3511, 3585, "30"),
    ("Eindhoven", 5611, 5658, "40"),
    ("Tilburg", 5011, 5049, "13"),
    ("Groningen", 9711, 9747, "50"),
)
NL_STREETS: tuple[str, ...] = (
    "Keizersgracht",
    "Herengracht",
    "Stationsplein",
    "Coolsingel",
    "Weena",
    "Oudegracht",
    "Vestdijk",
    "Stadhouderskade",
    "Kanaalweg",
    "Havenstraat",
    "Industrieweg",
    "Mercatorweg",
)
DE_CITIES: tuple[tuple[str, int, int, str], ...] = (
    ("Berlin", 10115, 14199, "30"),
    ("Hamburg", 20095, 22769, "40"),
    ("Munich", 80331, 81929, "89"),
    ("Cologne", 50667, 51149, "221"),
    ("Frankfurt am Main", 60306, 60599, "69"),
    ("Stuttgart", 70173, 70629, "711"),
)
DE_STREETS: tuple[str, ...] = (
    "Friedrichstraße",
    "Königsallee",
    "Hauptstraße",
    "Bahnhofstraße",
    "Schillerstraße",
    "Goethestraße",
    "Industriestraße",
    "Hafenstraße",
    "Lindenstraße",
)
# UK towns with outward postcodes and the Ofcom drama range of their area code.
GB_TOWNS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("London", ("EC1A", "EC2M", "SE1", "W1F", "N1"), "20 7946 0"),
    ("Manchester", ("M1", "M2", "M3"), "161 496 0"),
    ("Leeds", ("LS1", "LS2", "LS11"), "113 496 0"),
    ("Bristol", ("BS1", "BS2"), "117 496 0"),
    ("Birmingham", ("B1", "B2", "B3"), "121 496 0"),
    ("Reading", ("RG1", "RG2"), "118 496 0"),
    ("Sheffield", ("S1", "S3"), "114 496 0"),
    ("Leicester", ("LE1",), "116 496 0"),
    ("Cardiff", ("CF10",), "29 2018 0"),
)
GB_STREETS: tuple[str, ...] = (
    "High Street",
    "Station Road",
    "Church Street",
    "Victoria Road",
    "Mill Lane",
    "Park Road",
    "King Street",
    "Queen Street",
    "Bridge Street",
    "Market Street",
    "Albert Road",
    "Wellington Street",
    "Castle Street",
)
GB_INWARD_LETTERS = "ABDEFGHJLNPQRSTUWXYZ"
IE_TOWNS: tuple[tuple[str, str, str], ...] = (
    ("Dublin 2", "D02", "1"),
    ("Dublin 4", "D04", "1"),
    ("Cork", "T12", "21"),
)
IE_STREETS: tuple[str, ...] = (
    "Harcourt Street",
    "Baggot Street Lower",
    "Merrion Square",
    "Grand Canal Quay",
    "Fitzwilliam Square",
    "Pembroke Road",
)
EIRCODE_CHARACTERS = "ACDEFHKNPRTVWXY0123456789"

# --------------------------------------------------------------------------------------------
# Banks and VAT numbers
# --------------------------------------------------------------------------------------------

# Bank codes schwifty knows (so the IBAN gets its BIC), with the length of the account number.
BANKS: dict[Country, tuple[tuple[str, int], ...]] = {
    "NL": (("ABNA", 10), ("INGB", 10), ("RABO", 10), ("TRIO", 10)),
    "DE": (("37040044", 10), ("10070000", 10), ("50010517", 10), ("70020270", 10)),
    "GB": (("NWBK601613", 8), ("BARC200000", 8), ("LOYD309634", 8), ("HBUK400515", 8)),
    "IE": (("AIBK931152", 8), ("BOFI900017", 8)),
}

# VAT numbers with valid check digits under stdnum.eu.vat. UK numbers are not in the EU scheme any
# more, so a UK company shows its registration number only.
VAT_NUMBERS: dict[Country, tuple[str, ...]] = {
    "NL": (
        "NL286168741B01",
        "NL190169072B01",
        "NL321273266B01",
        "NL337768651B01",
        "NL662851602B01",
        "NL585385405B01",
        "NL266025201B01",
        "NL253623698B01",
        "NL319448204B01",
        "NL435158089B01",
        "NL583473556B01",
        "NL328449465B01",
        "NL246895172B01",
        "NL117507866B01",
        "NL231110017B01",
        "NL219411670B01",
    ),
    "DE": (
        "DE725777517",
        "DE187794532",
        "DE552077616",
        "DE110896106",
        "DE350983343",
        "DE618105446",
        "DE136401282",
        "DE685291231",
        "DE440690252",
        "DE374509237",
        "DE769722535",
        "DE384520497",
    ),
    "IE": (
        "IE1349995J",
        "IE4604689V",
        "IE2258058P",
        "IE3829661T",
        "IE2094041L",
        "IE7628784C",
        "IE9462554E",
        "IE1871199V",
    ),
    "GB": (),
}

# --------------------------------------------------------------------------------------------
# People
# --------------------------------------------------------------------------------------------

# Names that read as ordinary words in a contract (a defined term, a month, money) are not used,
# so that a person's name never doubles as something that must stay visible.
NAME_STOPLIST: frozenset[str] = frozenset(
    {
        "April",
        "August",
        "Banks",
        "Bill",
        "Bond",
        "Cash",
        "Chase",
        "Day",
        "Gold",
        "Grant",
        "Hope",
        "Judge",
        "June",
        "Law",
        "Marshall",
        "May",
        "Money",
        "Price",
        "Rich",
        "Sale",
        "Silver",
        "Sterling",
        "Summer",
        "Term",
        "Ward",
        "Will",
        "Winter",
    }
)

JOB_TITLES: dict[str, tuple[str, ...]] = {
    "signatory": (
        "Managing Director",
        "Chief Executive Officer",
        "Chief Financial Officer",
        "Commercial Director",
        "Director",
        "Finance Director",
    ),
    "contact": (
        "Head of Procurement",
        "Account Manager",
        "Contracts Manager",
        "Operations Director",
        "Supply Chain Manager",
        "Head of Legal",
    ),
}

# --------------------------------------------------------------------------------------------
# What the contracts are about
# --------------------------------------------------------------------------------------------

# Goods a supply agreement covers: (description, unit, lowest and highest unit price).
GOODS: tuple[tuple[str, tuple[tuple[str, str, float, float], ...]], ...] = (
    (
        "hygiene and catering consumables",
        (
            ("Nitrile examination gloves, powder-free", "units", 3.10, 5.40),
            ("Two-ply hand towels", "cartons", 18.0, 29.0),
            ("Centrefeed wiping rolls", "cartons", 21.0, 34.0),
            ("Surface disinfectant, ready to use", "litres", 2.10, 4.80),
            ("Heavy-duty waste sacks", "cartons", 11.0, 19.0),
        ),
    ),
    (
        "food packaging and catering disposables",
        (
            ("Compostable food containers", "cartons", 24.0, 41.0),
            ("Double-wall paper cups", "cartons", 31.0, 52.0),
            ("Kraft carrier bags", "cartons", 15.0, 27.0),
            ("Wooden cutlery sets", "cartons", 19.0, 33.0),
            ("Stretch film, hand grade", "pallets", 380.0, 640.0),
        ),
    ),
    (
        "personal protective equipment",
        (
            ("High-visibility vests", "units", 2.40, 4.90),
            ("Safety boots, composite toe", "units", 28.0, 46.0),
            ("Disposable coveralls", "units", 3.20, 6.10),
            ("Protective eyewear", "units", 2.90, 5.80),
            ("Cut-resistant gloves", "units", 4.10, 7.90),
        ),
    ),
    (
        "industrial fasteners and fixings",
        (
            ("Hex bolts, zinc plated", "kg", 6.10, 9.80),
            ("Countersunk wood screws", "kg", 7.20, 11.40),
            ("Nylon wall plugs", "kg", 8.30, 12.90),
            ("Stainless threaded rod", "kg", 9.50, 14.70),
            ("Galvanised washers", "kg", 5.40, 8.80),
        ),
    ),
    (
        "medical consumables",
        (
            ("Sterile wound dressings", "cartons", 42.0, 71.0),
            ("Disposable aprons", "cartons", 16.0, 28.0),
            ("Examination couch rolls", "cartons", 22.0, 37.0),
            ("Surgical face masks", "cartons", 13.0, 24.0),
            ("Alcohol hand rub", "litres", 3.40, 6.90),
        ),
    ),
)

# Logistics and facility services: (description, unit, lowest and highest rate per unit).
SERVICE_LINES: tuple[tuple[str, str, float, float], ...] = (
    ("Pallet storage per week", "pallets", 4.20, 7.80),
    ("Inbound handling", "pallets", 3.10, 5.60),
    ("Order picking", "cartons", 0.55, 1.20),
    ("Outbound loading", "pallets", 2.80, 4.90),
    ("Returns processing", "cartons", 0.90, 1.80),
    ("Waste collection", "tonnes", 95.0, 160.0),
)
