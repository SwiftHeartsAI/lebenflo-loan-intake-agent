-- Intake results, one row per packet / document / field / finding / policy match.
-- Portable SQL: runs unchanged on Azure SQL Database (T-SQL) and on DuckDB (the local snapshot
-- the public demo uses). Everything lives in its own "lebenflo" schema so it can share a
-- database safely. Flags are SMALLINT 0/1 because T-SQL has no BOOLEAN.

CREATE TABLE lebenflo.packets (
    packet_id         VARCHAR(10) PRIMARY KEY,
    applicant_name    VARCHAR(100),
    loan_amount       DECIMAL(12, 2),
    loan_purpose      VARCHAR(50),
    annualized_income DECIMAL(12, 2),   -- from the pay stub
    outcome           VARCHAR(30),      -- APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN
    injected_flaw     VARCHAR(30),      -- ground truth: what we deliberately broke (NULL = clean)
    expected_outcome  VARCHAR(30)
);

CREATE TABLE lebenflo.documents (
    packet_id VARCHAR(10),
    doc_type  VARCHAR(30),
    method    VARCHAR(20),   -- prebuilt | layout+llm
    model_id  VARCHAR(60),
    source    VARCHAR(20)    -- azure | simulated
);

CREATE TABLE lebenflo.fields (
    packet_id         VARCHAR(10),
    doc_type          VARCHAR(30),
    field             VARCHAR(40),
    extracted         VARCHAR(200),
    expected          VARCHAR(200),
    confidence        DECIMAL(6, 4),
    is_correct        SMALLINT,   -- 1 if it matches the ground truth
    is_decision_field SMALLINT    -- 1 if the rules use it (low confidence triggers V-004)
);

CREATE TABLE lebenflo.findings (
    packet_id VARCHAR(10),
    rule_id   VARCHAR(10),
    message   VARCHAR(200)
);

CREATE TABLE lebenflo.policy_refs (
    packet_id   VARCHAR(10),
    query_key   VARCHAR(10),   -- rule ID, or APPROVE
    match_rank  INTEGER,
    section_id  VARCHAR(10),
    score       DECIMAL(10, 6)
);
