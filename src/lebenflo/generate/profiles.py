"""Synthetic applicant profiles and the per-document field values (the answer key).

Everything here is fictional:
- names are random combinations from short lists,
- employers are invented names,
- SSNs use area numbers 900-999, which the SSA never issues,
- Lebenflo Credit Union does not exist.
"""

import random
from dataclasses import dataclass, field
from datetime import date

FIRST_NAMES = ["Jon", "Tess", "Bea", "Sam", "Liz", "Rob", "Mia", "Ned", "Kat", "Will", "Dot", "Abe"]
# Nickname -> legal name, used to create a realistic name mismatch (stub says "Jon", W-2 "Jonathan").
LEGAL_NAMES = {
    "Jon": "Jonathan",
    "Tess": "Theresa",
    "Bea": "Beatrice",
    "Sam": "Samuel",
    "Liz": "Elizabeth",
    "Rob": "Robert",
    "Mia": "Amelia",
    "Ned": "Edward",
    "Kat": "Katherine",
    "Will": "William",
    "Dot": "Dorothy",
    "Abe": "Abraham",
}
LAST_NAMES = [
    "Quillfeather",
    "Marrowbrook",
    "Pennywhistle",
    "Ashcombe",
    "Thistlewood",
    "Larkspur",
    "Bramblecott",
    "Fennimore",
    "Oakhollow",
    "Wrenfield",
    "Cobbleton",
    "Harrowgate",
]
EMPLOYERS = [
    "Quillback Robotics Co",
    "Marrowind Bakery Supply",
    "Tessellate Freight Partners",
    "Glimmerstone Health Clinic",
    "Vantrell Hydroponics",
    "Orchard Lantern Software",
    "Brindlewood Hospitality",
    "Kestrelmoor Civil Engineering",
    "Saltmeadow Print Works",
    "Copperleaf Dental Group",
]
STREETS = [
    "Lantern Way",
    "Fernbank Rd",
    "Quarry Hill Ln",
    "Mossgate Ave",
    "Tallow St",
    "Birchend Ct",
]
CITY = "Northmarch City, NM 00000"  # fictional state/city; ZIP 00000 is not a real ZIP

APPLICATION_DATE = date(2026, 10, 15)
TAX_YEAR = 2025

# Which packets are deliberately flawed. Everything else is a clean packet.
FLAWS = {"P003": "name_mismatch", "P006": "income_gap", "P009": "missing_document"}
# Maps a flaw to the validation rule that should catch it.
FLAW_TO_RULE = {"name_mismatch": "V-001", "income_gap": "V-002", "missing_document": "V-003"}
MISSING_DOC_TYPE = "bank_statement"  # what P009 leaves out

PAY_SCHEDULES = {
    # frequency: (periods per year, period start, period end, pay date, periods paid YTD)
    "semimonthly": (24, date(2026, 9, 16), date(2026, 9, 30), date(2026, 10, 3), 18),
    "biweekly": (26, date(2026, 9, 20), date(2026, 10, 3), date(2026, 10, 9), 20),
}


@dataclass
class Applicant:
    packet_id: str
    first_name: str
    last_name: str
    dob: date
    ssn: str
    address: str
    employer: str
    annual_salary: float
    pay_frequency: str
    loan_amount: float
    loan_purpose: str
    flaw: str | None = None
    documents: dict[str, dict] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


def fake_ssn(rng: random.Random) -> str:
    """Return an SSN in the 900-999 area range, which is never issued."""
    return f"{rng.randint(900, 999)}-{rng.randint(10, 99):02d}-{rng.randint(1000, 9999):04d}"


def make_applicant(index: int, rng: random.Random) -> Applicant:
    packet_id = f"P{index:03d}"
    first = FIRST_NAMES[(index - 1) % len(FIRST_NAMES)]
    last = LAST_NAMES[(index - 1) % len(LAST_NAMES)]
    applicant = Applicant(
        packet_id=packet_id,
        first_name=first,
        last_name=last,
        dob=date(rng.randint(1965, 2000), rng.randint(1, 12), rng.randint(1, 28)),
        ssn=fake_ssn(rng),
        address=f"{rng.randint(10, 9999)} {rng.choice(STREETS)}, {CITY}",
        employer=EMPLOYERS[(index - 1) % len(EMPLOYERS)],
        annual_salary=float(rng.randrange(42_000, 118_000, 500)),
        pay_frequency=rng.choice(list(PAY_SCHEDULES)),
        loan_amount=float(rng.randrange(5_000, 40_000, 1_000)),
        loan_purpose=rng.choice(["Auto loan", "Home improvement", "Debt consolidation"]),
        flaw=FLAWS.get(packet_id),
    )
    applicant.documents = build_documents(applicant, rng)
    return applicant


def build_documents(a: Applicant, rng: random.Random) -> dict[str, dict]:
    """Field values for each document. These exact values are printed on the PDFs."""
    periods, start, end, pay_date, ytd_periods = PAY_SCHEDULES[a.pay_frequency]
    gross = round(a.annual_salary / periods, 2)
    net = round(gross * 0.76, 2)  # flat ~24% for taxes/deductions; realistic enough for a demo

    # Last year's W-2 wages: a small raise since then (0-4%) keeps clean packets within 10%.
    w2_wages = round(a.annual_salary / (1 + rng.uniform(0.0, 0.04)), 2)
    if a.flaw == "income_gap":
        w2_wages = round(a.annual_salary * 0.70, 2)  # stub implies ~43% more than the W-2

    w2_name = a.full_name
    if a.flaw == "name_mismatch":
        w2_name = f"{LEGAL_NAMES[a.first_name]} {a.last_name}"

    beginning = round(rng.uniform(800, 9000), 2)
    deposits = [net, net]  # two paychecks in September
    withdrawals = [round(rng.uniform(40, 900), 2) for _ in range(4)]
    ending = round(beginning + sum(deposits) - sum(withdrawals), 2)

    docs = {
        "pay_stub": {
            "employee_name": a.full_name,
            "employer_name": a.employer,
            "employee_ssn": a.ssn,
            "pay_period_start": start.isoformat(),
            "pay_period_end": end.isoformat(),
            "pay_date": pay_date.isoformat(),
            "gross_pay": gross,
            "ytd_gross_pay": round(gross * ytd_periods, 2),
            "net_pay": net,
        },
        "w2": {
            "employee_name": w2_name,
            "employee_ssn": a.ssn,
            "employer_name": a.employer,
            "wages": w2_wages,
            "tax_year": str(TAX_YEAR),
        },
        "bank_statement": {
            "account_holder_name": a.full_name,
            "account_number": f"00{rng.randint(10_000_000, 99_999_999)}",
            "beginning_balance": beginning,
            "ending_balance": ending,
            "statement_start": "2026-09-01",
            "statement_end": "2026-09-30",
            "_deposits": deposits,  # underscore = printed on the PDF, not an evaluated field
            "_withdrawals": withdrawals,
        },
        "drivers_license": {
            "first_name": a.first_name,
            "last_name": a.last_name,
            "document_number": f"N{rng.randint(10_000_000, 99_999_999)}",
            "date_of_birth": a.dob.isoformat(),
            "date_of_expiration": date(2030, a.dob.month, a.dob.day).isoformat(),
        },
    }
    if a.flaw == "missing_document":
        del docs[MISSING_DOC_TYPE]
    return docs
