"""Turn a raw Document Intelligence result into our own typed fields.

Each prebuilt model has its own field names (and the W-2 and bank statement nest some of
them), so FIELD_MAP translates "our name" -> "path in the DI result". Downstream code only
ever sees our names, which keeps validation independent of the vendor schema.
"""

import re
from datetime import datetime

from pydantic import BaseModel

REQUIRED_DOC_TYPES = ["pay_stub", "w2", "bank_statement", "drivers_license"]

# Prebuilt model per document type (Document Intelligence API v4.0, 2024-11-30 GA).
MODEL_IDS = {
    "pay_stub": "prebuilt-payStub.us",
    "w2": "prebuilt-tax.us.w2",
    "bank_statement": "prebuilt-bankStatement.us",
    "drivers_license": "prebuilt-idDocument",
}
LAYOUT_MODEL_ID = "prebuilt-layout"

# our field -> (DI field path, type). "Accounts.0.X" means first item of the Accounts array.
FIELD_MAP: dict[str, dict[str, tuple[str, str]]] = {
    "pay_stub": {
        "employee_name": ("EmployeeName", "string"),
        "employer_name": ("EmployerName", "string"),
        "employee_ssn": ("EmployeeSSN", "string"),
        "pay_period_start": ("PayPeriodStartDate", "date"),
        "pay_period_end": ("PayPeriodEndDate", "date"),
        "pay_date": ("PayDate", "date"),
        "gross_pay": ("CurrentPeriodGrossPay", "number"),
        "ytd_gross_pay": ("YearToDateGrossPay", "number"),
        "net_pay": ("CurrentPeriodNetPay", "number"),
    },
    "w2": {
        "employee_name": ("Employee.Name", "string"),
        "employee_ssn": ("Employee.SocialSecurityNumber", "string"),
        "employer_name": ("Employer.Name", "string"),
        "wages": ("WagesTipsAndOtherCompensation", "number"),
        "tax_year": ("TaxYear", "string"),
    },
    "bank_statement": {
        "account_holder_name": ("AccountHolderName", "string"),
        "account_number": ("Accounts.0.AccountNumber", "string"),
        "beginning_balance": ("Accounts.0.BeginningBalance", "number"),
        "ending_balance": ("Accounts.0.EndingBalance", "number"),
        "statement_start": ("StatementStartDate", "date"),
        "statement_end": ("StatementEndDate", "date"),
    },
    "drivers_license": {
        "first_name": ("FirstName", "string"),
        "last_name": ("LastName", "string"),
        "document_number": ("DocumentNumber", "string"),
        "date_of_birth": ("DateOfBirth", "date"),
        "date_of_expiration": ("DateOfExpiration", "date"),
    },
}


class ExtractedField(BaseModel):
    value: str | float | None
    confidence: float  # 0..1; 0 when the field was not found


class ExtractedDocument(BaseModel):
    doc_type: str
    file: str
    model_id: str  # which model produced the fields, e.g. prebuilt-payStub.us
    method: str  # "prebuilt" or "layout+llm" (fallback)
    source: str  # "azure" (real call or replay of one) or "simulated"
    fields: dict[str, ExtractedField]

    def value(self, name: str):
        f = self.fields.get(name)
        return f.value if f else None


def get_path(fields: dict, path: str) -> dict | None:
    """Walk a DI field path like 'Employee.Name' or 'Accounts.0.AccountNumber'."""
    node: dict | None = {"valueObject": fields}
    for part in path.split("."):
        if node is None:
            return None
        if part.isdigit():
            items = node.get("valueArray") or []
            node = items[int(part)] if int(part) < len(items) else None
        else:
            node = (node.get("valueObject") or {}).get(part)
    return node


def raw_value(field: dict):
    """DI puts the typed value in a type-specific key; fall back to the raw text."""
    for key in ("valueString", "valueDate", "valueNumber", "valueInteger"):
        if key in field:
            return field[key]
    if "valueCurrency" in field:
        return field["valueCurrency"].get("amount")
    return field.get("content")


def normalize(value, kind: str):
    """Coerce to our canonical form: ISO dates, floats, trimmed strings."""
    if value is None or value == "":
        return None
    if kind == "number":
        if isinstance(value, int | float):
            return round(float(value), 2)
        cleaned = re.sub(r"[^\d.\-]", "", str(value))
        return round(float(cleaned), 2) if cleaned else None
    if kind == "date":
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        return None
    return " ".join(str(value).split())


def fields_from_result(doc_type: str, result: dict) -> dict[str, ExtractedField]:
    """Map a prebuilt-model result (as a JSON dict) onto our field names."""
    documents = result.get("documents") or []
    di_fields = documents[0].get("fields", {}) if documents else {}
    out = {}
    for name, (path, kind) in FIELD_MAP[doc_type].items():
        node = get_path(di_fields, path)
        value = normalize(raw_value(node), kind) if node else None
        confidence = float(node.get("confidence") or 0.0) if node and value is not None else 0.0
        out[name] = ExtractedField(value=value, confidence=confidence)
    return out


def found_ratio(fields: dict[str, ExtractedField]) -> float:
    return sum(f.value is not None for f in fields.values()) / max(len(fields), 1)
