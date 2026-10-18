"""The people and companies of one document, with every detail of them that is a secret.

Names come from Faker (``en_GB``); addresses, telephone numbers, registration numbers and bank
accounts from the document's own random generator, so a document is the same every time it is
built from the same seed.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

import phonenumbers
from faker import Faker
from schwifty import IBAN

from themask.model import PlaceholderType
from tools.corpus.pools import (
    BANKS,
    DE_CITIES,
    DE_STREETS,
    EIRCODE_CHARACTERS,
    GB_INWARD_LETTERS,
    GB_STREETS,
    GB_TOWNS,
    IE_STREETS,
    IE_TOWNS,
    NAME_STOPLIST,
    NL_CITIES,
    NL_STREETS,
    REGISTERED_IN,
    VAT_NUMBERS,
    Company,
    Country,
)
from tools.corpus.truth import Registry, Secret

P = PlaceholderType
_LEGAL_FORM_WORDS = {"B.V.", "N.V.", "GmbH", "AG", "Ltd", "Limited", "plc", "LLP"}


@dataclass
class Person:
    """A person named in a document, with the forms of the name the document may use."""

    first: str
    last: str
    honorific: str
    title: str
    secret: Secret
    email: Secret

    @property
    def full(self) -> str:
        """The name in full: "John Smith"."""
        return self.secret.value

    @property
    def formal(self) -> str:
        """With the title: "Mr John Smith"."""
        return self.secret.form(f"{self.honorific} {self.full}")

    @property
    def mr(self) -> str:
        """Title and surname: "Mr Smith"."""
        return self.secret.form(f"{self.honorific} {self.last}")

    @property
    def initial(self) -> str:
        """Initial and surname: "J. Smith"."""
        return self.secret.form(f"{self.first[0]}. {self.last}")


@dataclass
class Party:
    """One party to a contract: the company, its details and the people who act for it."""

    company: Company
    role: str
    name: Secret
    reg: Secret
    address: Secret
    phone: Secret
    url: Secret
    signatory: Person
    contact: Person
    area: str = ""  # the telephone area code of the registered office
    vat: Secret | None = None
    iban: Secret | None = None
    bic: Secret | None = None
    people: list[Person] = field(default_factory=list)

    @property
    def full(self) -> str:
        """The legal name: "Northwind Trading B.V."."""
        return self.name.value

    @property
    def short(self) -> str:
        """The name in running text: "Northwind"."""
        return self.name.form(self.company.short)

    @property
    def upper(self) -> str:
        """The legal name in capitals: "NORTHWIND TRADING B.V."."""
        return self.name.form(self.full.upper())

    @property
    def local_phone(self) -> str:
        """The telephone number as written at home, "020 7946 0123" (international elsewhere)."""
        return self.phone.forms[0] if self.phone.forms else self.phone.value

    @property
    def registered_in(self) -> str:
        return REGISTERED_IN[self.company.country]


class PartyMaker:
    """Makes the people, companies and numbers of one document.

    Within a document no two people share a surname (unless asked to), an initial-and-surname
    form or a first name with another's surname, and no surname is a company's short name.
    """

    def __init__(
        self,
        rng: random.Random,
        fake: Faker,
        registry: Registry,
        *,
        compact_iban: bool,
        email_style: str,
    ) -> None:
        self._rng = rng
        self._fake = fake
        self._registry = registry
        self._compact_iban = compact_iban
        self._email_style = email_style
        self._people: list[Person] = []
        self._vat_used: set[str] = set()
        self._phones_used: set[str] = set()
        self._shorts: set[str] = set()

    # ---- people ------------------------------------------------------------------------------

    def person(
        self,
        domain: str,
        title: str,
        *,
        surname: str | None = None,
        female: bool | None = None,
        honorific: str | None = None,
    ) -> Person:
        """A new person working at ``domain``; with ``surname``, someone sharing that surname."""
        rng, fake = self._rng, self._fake
        if female is None:
            female = rng.random() < 0.5
        while True:
            first = fake.first_name_female() if female else fake.first_name_male()
            last = surname or fake.last_name()
            if self._acceptable(first, last, shared=surname is not None):
                break
        if honorific is None:
            honorific = "Dr" if rng.random() < 0.12 else ("Ms" if female else "Mr")
        secret = self._registry.add(P.PERSON, f"{first} {last}")
        email = self._registry.add(P.EMAIL, self._email(first, last, domain))
        person = Person(first, last, honorific, title, secret, email)
        self._people.append(person)
        return person

    def _acceptable(self, first: str, last: str, *, shared: bool) -> bool:
        if not re.fullmatch(r"[A-Z][a-z]+", first) or not re.fullmatch(r"[A-Z][a-z]+", last):
            return False  # no apostrophes, hyphens or capitals inside a name
        if first in NAME_STOPLIST or last in NAME_STOPLIST or last in self._shorts:
            return False
        for other in self._people:
            if other.first == first or other.last == first or other.first == last:
                return False
            if other.last == last and (not shared or other.first[0] == first[0]):
                return False
        return True

    def _email(self, first: str, last: str, domain: str) -> str:
        local = {
            "initial": f"{first[0]}.{last}",
            "full": f"{first}.{last}",
            "joined": f"{first[0]}{last}",
        }[self._email_style]
        return f"{local.lower()}@{domain}"

    # ---- companies ---------------------------------------------------------------------------

    def company(self, company: Company) -> Secret:
        """The COMPANY secret of ``company``, with its short name and name without legal form."""
        self._shorts.add(company.short)
        words = company.name.split()
        base = " ".join(words[:-1]) if words[-1] in _LEGAL_FORM_WORDS else company.name
        return self._registry.add(P.COMPANY, company.name, company.short, base)

    def party(self, company: Company, role: str, *, signatory: Person, contact: Person) -> Party:
        """A full party: name, registration, address, telephone, website, VAT and bank account."""
        name = self.company(company)
        address, area = self.address(company.country)
        party = Party(
            company=company,
            role=role,
            name=name,
            reg=self._registry.add(P.ID, self._registration(company)),
            address=address,
            phone=self.phone(company.country, area),
            url=self._registry.add(P.URL, f"https://www.{company.domain}", f"www.{company.domain}"),
            signatory=signatory,
            contact=contact,
            area=area,
        )
        party.people = [signatory] if signatory is contact else [signatory, contact]
        pool = [v for v in VAT_NUMBERS[company.country] if v not in self._vat_used]
        if pool:
            vat = self._rng.choice(pool)
            self._vat_used.add(vat)
            party.vat = self._registry.add(P.ID, vat)
        party.iban, party.bic = self._bank(company)
        return party

    def _registration(self, company: Company) -> str:
        rng, country = self._rng, company.country
        if company.is_partnership:
            return f"OC{rng.randrange(300_000, 449_999)}"  # Companies House numbers of LLPs
        if country == "NL":
            return f"{rng.randrange(10_000_000, 99_999_999)}"
        if country == "GB":
            return f"0{rng.randrange(1_000_000, 9_999_999)}"
        if country == "DE":
            return f"HRB {rng.randrange(10_000, 199_999)}"
        return f"{rng.randrange(100_000, 799_999)}"

    def _bank(self, company: Company) -> tuple[Secret, Secret]:
        rng = self._rng
        if company.bank_account is not None:
            bank, account = company.bank_account
        else:
            bank, length = rng.choice(BANKS[company.country])
            account = "".join(str(rng.randrange(10)) for _ in range(length))
        iban = IBAN.generate(company.country, bank_code=bank, account_code=account)
        grouped, compact = iban.formatted, iban.compact
        value, other = (compact, grouped) if self._compact_iban else (grouped, compact)
        bic = str(iban.bic)
        bic = bic.removesuffix("XXX") if len(bic) == 11 else bic
        return self._registry.add(P.IBAN, value, other), self._registry.add(P.ID, bic)

    # ---- addresses and telephone numbers -----------------------------------------------------

    def address(self, country: Country) -> tuple[Secret, str]:
        """A made-up street address on one line, and the telephone area code that goes with it."""
        rng = self._rng
        if country == "NL":
            city, low, high, area = rng.choice(NL_CITIES)
            letters = "".join(rng.choice("BCEGHJKLMNPRTVWXZ") for _ in range(2))
            street = f"{rng.choice(NL_STREETS)} {rng.randrange(2, 240)}"
            text = f"{street}, {rng.randrange(low, high)} {letters} {city}, the Netherlands"
        elif country == "DE":
            city, low, high, area = rng.choice(DE_CITIES)
            street = f"{rng.choice(DE_STREETS)} {rng.randrange(2, 160)}"
            text = f"{street}, {rng.randrange(low, high)} {city}, Germany"
        elif country == "GB":
            town, outward, area = rng.choice(GB_TOWNS)
            inward = f"{rng.randrange(1, 10)}{rng.choice(GB_INWARD_LETTERS)}"
            inward += rng.choice(GB_INWARD_LETTERS)
            street = f"{rng.randrange(2, 220)} {rng.choice(GB_STREETS)}"
            text = f"{street}, {town} {rng.choice(outward)} {inward}, United Kingdom"
        else:
            town, routing, area = rng.choice(IE_TOWNS)
            unique = "".join(rng.choice(EIRCODE_CHARACTERS) for _ in range(4))
            street = f"{rng.randrange(2, 90)} {rng.choice(IE_STREETS)}"
            text = f"{street}, {town}, {routing} {unique}, Ireland"
        return self._registry.add(P.ADDRESS, text), area

    def phone(self, country: Country, area: str) -> Secret:
        """A telephone number valid in form, written internationally, with its national form."""
        rng = self._rng
        for _ in range(1000):
            if country == "GB":
                raw = f"+44 {area}{rng.randrange(100, 1000)}"  # an Ofcom drama number
            elif country == "NL":
                raw = f"+31 {area} {rng.randrange(2_000_000, 9_999_999)}"
            elif country == "DE":
                raw = f"+49 {area} {rng.randrange(2_000_000, 99_999_999)}"
            else:
                raw = f"+353 {area} {rng.randrange(2_000_000, 9_999_999)}"
            number = phonenumbers.parse(raw, None)
            if phonenumbers.is_valid_number(number) and raw not in self._phones_used:
                self._phones_used.add(raw)
                break
        else:
            raise RuntimeError(f"no valid telephone number for area code {area} in {country}")
        international = phonenumbers.format_number(
            number, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
        national = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
        forms = [national] if country in ("GB", "NL") else []
        return self._registry.add(P.PHONE, international, *forms)
