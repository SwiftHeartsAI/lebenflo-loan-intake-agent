-- Analytics views an intake manager (or a Power BI report) would use.
-- Portable SQL: no ORDER BY inside views (SQL Server disallows it), explicit GROUP BY columns,
-- one statement per view.

-- How often each rule fires, as a share of all packets.
CREATE VIEW lebenflo.v_exception_rate_by_rule AS
SELECT
    f.rule_id,
    COUNT(DISTINCT f.packet_id) AS packets_flagged,
    ROUND(COUNT(DISTINCT f.packet_id) * 100.0 / (SELECT COUNT(*) FROM lebenflo.packets), 1) AS pct_of_packets
FROM lebenflo.findings f
GROUP BY f.rule_id;

-- Extraction quality per field: accuracy vs ground truth, and how often confidence is too low.
CREATE VIEW lebenflo.v_field_quality AS
SELECT
    doc_type,
    field,
    is_decision_field,
    ROUND(AVG(confidence), 3)                                 AS avg_confidence,
    MIN(confidence)                                           AS min_confidence,
    ROUND(AVG(CASE WHEN is_correct = 1 THEN 100.0 ELSE 0 END), 1) AS accuracy_pct,
    SUM(CASE WHEN confidence < 0.80 THEN 1 ELSE 0 END)        AS below_threshold
FROM lebenflo.fields
GROUP BY doc_type, field, is_decision_field;

-- Was the flaw we injected caught? (confusion-style view over the ground truth)
CREATE VIEW lebenflo.v_outcome_vs_expected AS
SELECT
    COALESCE(injected_flaw, 'clean') AS packet_type,
    expected_outcome,
    outcome,
    COUNT(*)                         AS packets
FROM lebenflo.packets
GROUP BY COALESCE(injected_flaw, 'clean'), expected_outcome, outcome;

-- Which extraction path each document type took.
CREATE VIEW lebenflo.v_extraction_path AS
SELECT doc_type, method, model_id, COUNT(*) AS documents
FROM lebenflo.documents
GROUP BY doc_type, method, model_id;

-- Loan amount as a share of annual income: an intake-time affordability indicator.
-- (Not DTI: true DTI needs monthly debt payments, which underwriting collects.)
CREATE VIEW lebenflo.v_loan_to_income AS
SELECT
    packet_id,
    loan_purpose,
    loan_amount,
    annualized_income,
    ROUND(loan_amount * 100.0 / NULLIF(annualized_income, 0), 1) AS loan_to_income_pct,
    outcome
FROM lebenflo.packets;
