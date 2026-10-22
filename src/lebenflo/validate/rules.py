"""Validation rules. Each rule has a stable ID so every escalation is explainable and auditable.

V-001  Name on the documents does not match
V-002  Pay stub income (annualized) differs from W-2 wages by more than 10%
V-003  A required document is missing
V-004  A field the decision depends on was read with confidence below 0.80 (or not at all)

Rules are plain Python, not LLM calls: the same packet always gets the same result.
"""

import re
from datetime import date

from pydantic import BaseModel

from lebenflo.extract.fields import REQUIRED_DOC_TYPES, ExtractedDocument

INCOME_GAP_LIMIT = 0.10
CONFIDENCE_THRESHOLD = 0.80

# Fields the rules and the underwriter rely on. Low confidence on these -> human review.
DECISION_FIELDS = {
    "pay_stub": ["employee_name", "pay_period_start", "pay_period_end", "gross_pay"],
    "w2": ["employee_name", "wages"],
    "bank_statement": ["account_holder_name", "ending_balance"],
    "drivers_license": ["first_name", "last_name", "date_of_expiration"],
}


class Finding(BaseModel):
    rule_id: str
    message: str
    details: dict = {}


def normalize_name(name: str) -> str:
    """'BEA  Pennywhistle' -> 'bea pennywhistle' (case, spacing, punctuation ignored)."""
    return " ".join(re.sub(r"[^a-z ]", "", name.lower()).split())


def names_by_document(docs: dict[str, ExtractedDocument]) -> dict[str, str]:
    names = {}
    for doc_type, doc in docs.items():
        if doc_type == "drivers_license":
            first, last = doc.value("first_name"), doc.value("last_name")
            name = f"{first} {last}" if first and last else None
        else:
            name = doc.value(
                "account_holder_name" if doc_type == "bank_statement" else "employee_name"
            )
        if name:
            names[doc_type] = str(name)
    return names


def check_name_match(docs: dict[str, ExtractedDocument]) -> Finding | None:
    names = names_by_document(docs)
    if len({normalize_name(n) for n in names.values()}) > 1:
        return Finding(
            rule_id="V-001",
            message="Applicant name differs across documents",
            details={"names": names},
        )
    return None


def periods_per_year(start: str, end: str) -> int:
    """Infer pay frequency from the length of the pay period."""
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if days <= 8:
        return 52  # weekly
    if days <= 14:
        return 26  # biweekly
    if days <= 16:
        return 24  # semimonthly
    return 12  # monthly


def check_income_gap(docs: dict[str, ExtractedDocument]) -> Finding | None:
    stub, w2 = docs.get("pay_stub"), docs.get("w2")
    if not stub or not w2:
        return None  # V-003 reports the missing document
    gross, wages = stub.value("gross_pay"), w2.value("wages")
    start, end = stub.value("pay_period_start"), stub.value("pay_period_end")
    if not (gross and wages and start and end):
        return None  # V-004 reports the unreadable field
    periods = periods_per_year(start, end)
    annualized = round(float(gross) * periods, 2)
    gap = abs(annualized - float(wages)) / float(wages)
    if gap > INCOME_GAP_LIMIT:
        return Finding(
            rule_id="V-002",
            message=f"Annualized pay stub income differs from W-2 wages by {gap:.0%}",
            details={
                "annualized_pay_stub": annualized,
                "periods_per_year": periods,
                "w2_wages": wages,
                "gap": round(gap, 4),
            },
        )
    return None


def check_missing_documents(docs: dict[str, ExtractedDocument]) -> Finding | None:
    missing = [d for d in REQUIRED_DOC_TYPES if d not in docs]
    if missing:
        return Finding(
            rule_id="V-003",
            message=f"Missing required document(s): {', '.join(missing)}",
            details={"missing": missing},
        )
    return None


def check_confidence(docs: dict[str, ExtractedDocument]) -> Finding | None:
    low = {}
    for doc_type, doc in docs.items():
        for name in DECISION_FIELDS[doc_type]:
            field = doc.fields.get(name)
            if field is None or field.value is None or field.confidence < CONFIDENCE_THRESHOLD:
                low[f"{doc_type}.{name}"] = field.confidence if field else 0.0
    if low:
        return Finding(
            rule_id="V-004",
            message=f"{len(low)} field(s) below {CONFIDENCE_THRESHOLD:.2f} confidence",
            details={"fields": low},
        )
    return None


RULES = [check_name_match, check_income_gap, check_missing_documents, check_confidence]


def run_rules(docs: dict[str, ExtractedDocument]) -> list[Finding]:
    return [f for rule in RULES if (f := rule(docs)) is not None]
