from lebenflo.extract.fields import ExtractedDocument, ExtractedField, fields_from_result
from lebenflo.governance.pii import mask_pii
from lebenflo.validate.rules import run_rules


def doc(doc_type: str, confidence: float = 0.95, **values) -> ExtractedDocument:
    return ExtractedDocument(
        doc_type=doc_type,
        file=f"{doc_type}.pdf",
        model_id="test",
        method="prebuilt",
        source="test",
        fields={k: ExtractedField(value=v, confidence=confidence) for k, v in values.items()},
    )


def clean_packet(**overrides) -> dict[str, ExtractedDocument]:
    docs = {
        "pay_stub": doc(
            "pay_stub",
            employee_name="Bea Pennywhistle",
            gross_pay=2000.0,
            pay_period_start="2026-09-16",
            pay_period_end="2026-09-30",
        ),  # x24 = 48,000
        "w2": doc("w2", employee_name="Bea Pennywhistle", wages=47000.0),
        "bank_statement": doc(
            "bank_statement", account_holder_name="Bea Pennywhistle", ending_balance=1200.0
        ),
        "drivers_license": doc(
            "drivers_license",
            first_name="BEA",
            last_name="PENNYWHISTLE",
            date_of_expiration="2030-01-01",
        ),
    }
    docs.update(overrides)
    return docs


def rule_ids(docs) -> list[str]:
    return [f.rule_id for f in run_rules(docs)]


def test_clean_packet_has_no_findings():
    assert rule_ids(clean_packet()) == []  # also shows case differences are not a mismatch


def test_v001_name_mismatch():
    docs = clean_packet(w2=doc("w2", employee_name="Beatrice Pennywhistle", wages=47000.0))
    assert rule_ids(docs) == ["V-001"]


def test_v002_income_gap():
    docs = clean_packet(w2=doc("w2", employee_name="Bea Pennywhistle", wages=30000.0))
    assert rule_ids(docs) == ["V-002"]


def test_v003_missing_document():
    docs = clean_packet()
    del docs["bank_statement"]
    assert rule_ids(docs) == ["V-003"]


def test_v004_low_confidence():
    docs = clean_packet(
        w2=doc("w2", confidence=0.55, employee_name="Bea Pennywhistle", wages=47000.0)
    )
    assert rule_ids(docs) == ["V-004"]


def test_mask_pii():
    text = "SSN 970-47-6925, acct 0031831063, DOB: 07/03/1972, pay date 10/03/2026"
    masked = mask_pii(text)
    assert "970-47-6925" not in masked and "0031831063" not in masked and "1972" not in masked
    assert "[ACCOUNT ****1063]" in masked and "10/03/2026" in masked  # other dates untouched


def test_fields_from_nested_w2_result():
    result = {
        "documents": [
            {
                "fields": {
                    "Employee": {
                        "type": "object",
                        "valueObject": {
                            "Name": {
                                "type": "string",
                                "valueString": "Bea  Pennywhistle",
                                "confidence": 0.9,
                            }
                        },
                    },
                    "WagesTipsAndOtherCompensation": {
                        "type": "number",
                        "valueNumber": 47000,
                        "confidence": 0.8,
                    },
                }
            }
        ]
    }
    fields = fields_from_result("w2", result)
    assert fields["employee_name"].value == "Bea Pennywhistle"
    assert fields["wages"].value == 47000.0
    assert fields["tax_year"].value is None and fields["tax_year"].confidence == 0.0
