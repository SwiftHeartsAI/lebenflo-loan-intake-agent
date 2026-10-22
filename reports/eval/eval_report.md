# Evaluation report

Run at 2026-10-22T14:04:45.661688+00:00 · extraction sources: {'azure': 39}

## Summary
| Metric | Value |
|---|---|
| Field-level extraction accuracy | 92.2% (244 fields) |
| Outcome accuracy | 30.0% |
| Flawed packets escalated | 3/3 |
| Flawed packets caught by their expected rule | 3/3 |
| Clean packets approved for underwriting | 0/7 |
| Exactly the expected rule IDs (no extras) | 10.0% |
| Findings by rule | {'V-004': 9, 'V-001': 1, 'V-002': 1, 'V-003': 1} |

## Per packet
| Packet | Flaw | Expected | Actual | Rules | OK |
|---|---|---|---|---|---|
| P001 | - | APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN | V-004 | ❌ |
| P002 | - | APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN | V-004 | ❌ |
| P003 | name_mismatch | ESCALATE_TO_HUMAN | ESCALATE_TO_HUMAN | V-001, V-004 | ❌ |
| P004 | - | APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN | V-004 | ❌ |
| P005 | - | APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN | V-004 | ❌ |
| P006 | income_gap | ESCALATE_TO_HUMAN | ESCALATE_TO_HUMAN | V-002, V-004 | ❌ |
| P007 | - | APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN | V-004 | ❌ |
| P008 | - | APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN | V-004 | ❌ |
| P009 | missing_document | ESCALATE_TO_HUMAN | ESCALATE_TO_HUMAN | V-003 | ✅ |
| P010 | - | APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN | V-004 | ❌ |

## Per field accuracy
| Field | Accuracy |
|---|---|
| bank_statement.account_holder_name | 100% |
| bank_statement.account_number | 100% |
| bank_statement.beginning_balance | 100% |
| bank_statement.ending_balance | 100% |
| bank_statement.statement_end | 100% |
| bank_statement.statement_start | 100% |
| drivers_license.date_of_birth | 90% |
| drivers_license.date_of_expiration | 90% |
| drivers_license.document_number | 30% |
| drivers_license.first_name | 100% |
| drivers_license.last_name | 100% |
| pay_stub.employee_name | 100% |
| pay_stub.employee_ssn | 100% |
| pay_stub.employer_name | 100% |
| pay_stub.gross_pay | 100% |
| pay_stub.net_pay | 100% |
| pay_stub.pay_date | 100% |
| pay_stub.pay_period_end | 100% |
| pay_stub.pay_period_start | 100% |
| pay_stub.ytd_gross_pay | 100% |
| w2.employee_name | 100% |
| w2.employee_ssn | 0% |
| w2.employer_name | 100% |
| w2.tax_year | 100% |
| w2.wages | 100% |
