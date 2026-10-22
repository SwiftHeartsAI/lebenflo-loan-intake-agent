"""Load agent results into SQL tables and build the analytics views in sql/.

DuckDB is an in-process SQL database, so the demo needs no server. The schema and views are
plain, portable SQL files, so the same pipeline could target Azure SQL or Snowflake by swapping
the connection.

Usage:  uv run python -m lebenflo.warehouse     (writes data/warehouse.duckdb)
"""

import json

import duckdb

from lebenflo.config import GROUND_TRUTH_DIR, RUNS_DIR, SQL_DIR, WAREHOUSE_DB
from lebenflo.eval.__main__ import values_match
from lebenflo.validate.rules import DECISION_FIELDS, periods_per_year

TABLES = ["packets", "documents", "fields", "findings"]
# View name -> ORDER BY used when displaying it (SQL Server doesn't allow ORDER BY inside a view).
VIEWS = {
    "v_exception_rate_by_rule": "packets_flagged DESC",
    "v_field_quality": "accuracy_pct, avg_confidence",
    "v_outcome_vs_expected": "packet_type",
    "v_extraction_path": "doc_type",
    "v_loan_to_income": "loan_to_income_pct DESC",
}


def annualized_income(state: dict) -> float | None:
    stub = state["documents"].get("pay_stub", {}).get("fields", {})
    gross, start, end = (
        stub.get(k, {}).get("value") for k in ("gross_pay", "pay_period_start", "pay_period_end")
    )
    return (
        round(float(gross) * periods_per_year(start, end), 2) if gross and start and end else None
    )


def collect_rows(states: list[dict]) -> dict[str, list[tuple]]:
    """Flatten agent results + ground truth into rows for each table."""
    rows: dict[str, list[tuple]] = {t: [] for t in TABLES}
    for state in states:
        pid = state["packet_id"]
        truth = json.loads((GROUND_TRUTH_DIR / f"{pid}.json").read_text())
        app = truth["application"]
        rows["packets"].append((
            pid, truth["applicant"]["full_name"], app["loan_amount"], app["loan_purpose"],
            annualized_income(state), state["outcome"], truth["flaw"], truth["expected_outcome"],
        ))  # fmt: skip
        for doc_type, doc in state["documents"].items():
            rows["documents"].append((pid, doc_type, doc["method"], doc["model_id"], doc["source"]))
            expected_fields = truth["documents"].get(doc_type, {}).get("fields", {})
            for name, f in doc["fields"].items():
                expected = expected_fields.get(name)
                rows["fields"].append((
                    pid, doc_type, name,
                    None if f["value"] is None else str(f["value"]),
                    None if expected is None else str(expected),
                    round(f["confidence"], 4),
                    int(values_match(expected, f["value"])),
                    int(name in DECISION_FIELDS[doc_type]),
                ))  # fmt: skip
        for finding in state["findings"]:
            rows["findings"].append((pid, finding["rule_id"], finding["message"]))
    return rows


def sql_statements(filename: str) -> list[str]:
    """Split a .sql file into statements (comments removed)."""
    lines = [
        ln
        for ln in (SQL_DIR / filename).read_text().splitlines()
        if not ln.strip().startswith("--")
    ]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def build_warehouse(states: list[dict], db_path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """Create the lebenflo schema from sql/, insert the rows, and create the views."""
    con = duckdb.connect(db_path)
    con.execute("CREATE SCHEMA IF NOT EXISTS lebenflo")
    for view in VIEWS:
        con.execute(f"DROP VIEW IF EXISTS lebenflo.{view}")
    for table in TABLES:
        con.execute(f"DROP TABLE IF EXISTS lebenflo.{table}")
    for statement in sql_statements("schema.sql"):
        con.execute(statement)
    for table, table_rows in collect_rows(states).items():
        if table_rows:
            marks = ", ".join(["?"] * len(table_rows[0]))
            con.executemany(f"INSERT INTO lebenflo.{table} VALUES ({marks})", table_rows)
    for statement in sql_statements("views.sql"):
        con.execute(statement)
    return con


def load_states() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(RUNS_DIR.glob("P*.json"))]


def main() -> None:
    WAREHOUSE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = build_warehouse(load_states(), str(WAREHOUSE_DB))
    print(con.sql("SELECT * FROM lebenflo.v_exception_rate_by_rule ORDER BY packets_flagged DESC"))
    print(f"Saved {WAREHOUSE_DB}")


if __name__ == "__main__":
    main()
