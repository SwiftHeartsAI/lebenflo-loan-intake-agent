"""Load agent results into SQL tables and build the analytics views in sql/.

Two targets, same SQL files:
- Azure SQL Database (live): the real warehouse, loaded with pymssql.
- DuckDB (offline): an in-process copy for tests and the public demo, so the database itself
  is never exposed to the internet.

After an Azure SQL load, the view results are read back from Azure SQL and saved to
data/recorded/azure_sql_views.json, so the demo can show what Azure SQL returned.

Usage:  uv run python -m lebenflo.warehouse              # DuckDB file (data/warehouse.duckdb)
        uv run python -m lebenflo.warehouse --azure-sql  # also load Azure SQL Database
"""

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal

import duckdb

from lebenflo.config import (
    AZURE_SQL_SNAPSHOT,
    GROUND_TRUTH_DIR,
    RUNS_DIR,
    SQL_DIR,
    WAREHOUSE_DB,
    Settings,
    get_settings,
)
from lebenflo.eval.__main__ import values_match
from lebenflo.validate.rules import DECISION_FIELDS, periods_per_year

TABLES = ["packets", "documents", "fields", "findings", "policy_refs"]
# View name -> ORDER BY used when displaying it (T-SQL doesn't allow ORDER BY inside a view).
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
        for ref in state.get("policy_refs", []):
            for rank, m in enumerate(ref["matches"], start=1):
                rows["policy_refs"].append((pid, ref["query"], rank, m["section_id"], m["score"]))
    return rows


def sql_statements(filename: str) -> list[str]:
    """Split a .sql file into statements (comments removed)."""
    lines = [
        ln
        for ln in (SQL_DIR / filename).read_text().splitlines()
        if not ln.strip().startswith("--")
    ]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def load(con, rows: dict[str, list[tuple]], placeholder: str) -> None:
    """Drop and recreate everything in the lebenflo schema, insert rows, create views."""
    cur = con.cursor()
    for view in VIEWS:
        cur.execute(f"DROP VIEW IF EXISTS lebenflo.{view}")
    for table in TABLES:
        cur.execute(f"DROP TABLE IF EXISTS lebenflo.{table}")
    for statement in sql_statements("schema.sql"):
        cur.execute(statement)
    for table, table_rows in rows.items():
        if table_rows:
            marks = ", ".join([placeholder] * len(table_rows[0]))
            cur.executemany(f"INSERT INTO lebenflo.{table} VALUES ({marks})", table_rows)
    for statement in sql_statements("views.sql"):
        cur.execute(statement)  # T-SQL needs each CREATE VIEW in its own batch
    con.commit()


def build_duckdb(states: list[dict], db_path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(db_path)
    con.execute("CREATE SCHEMA IF NOT EXISTS lebenflo")
    load(con, collect_rows(states), placeholder="?")
    return con


def load_azure_sql(states: list[dict], settings: Settings) -> dict:
    """Load Azure SQL Database, read every view back, and record the results."""
    import pymssql

    if not (settings.sql_server and settings.sql_user and settings.sql_password):
        raise RuntimeError("Set AZURE_SQL_SERVER, AZURE_SQL_USER and AZURE_SQL_PASSWORD in .env")
    con = pymssql.connect(
        server=settings.sql_server,
        user=settings.sql_user,
        password=settings.sql_password,
        database=settings.sql_database,
        login_timeout=60,  # a serverless database may need time to resume from auto-pause
    )
    cur = con.cursor()
    cur.execute("IF SCHEMA_ID('lebenflo') IS NULL EXEC('CREATE SCHEMA lebenflo')")
    load(con, collect_rows(states), placeholder="%s")

    cur.execute("SELECT @@VERSION")
    version = cur.fetchone()[0].splitlines()[0]
    snapshot = {
        "engine": version,
        "server": settings.sql_server.split(".")[0],
        "database": settings.sql_database,
        "loaded_at": datetime.now(UTC).isoformat(),
        "row_counts": {},
        "views": {},
    }
    for table in TABLES:
        cur.execute(f"SELECT COUNT(*) FROM lebenflo.{table}")
        snapshot["row_counts"][table] = cur.fetchone()[0]
    for view, order in VIEWS.items():
        cur.execute(f"SELECT * FROM lebenflo.{view} ORDER BY {order}")
        snapshot["views"][view] = {
            "columns": [c[0] for c in cur.description],
            "rows": [
                [float(v) if isinstance(v, Decimal) else v for v in r] for r in cur.fetchall()
            ],
        }
    con.close()
    AZURE_SQL_SNAPSHOT.write_text(json.dumps(snapshot, indent=1))
    return snapshot


def load_states() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(RUNS_DIR.glob("P*.json"))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--azure-sql", action="store_true", help="also load Azure SQL Database")
    args = parser.parse_args()
    states = load_states()
    WAREHOUSE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = build_duckdb(states, str(WAREHOUSE_DB))
    print(con.sql("SELECT * FROM lebenflo.v_exception_rate_by_rule ORDER BY packets_flagged DESC"))
    if args.azure_sql:
        snap = load_azure_sql(states, get_settings())
        print(f"Loaded Azure SQL ({snap['engine']}): {snap['row_counts']}")


if __name__ == "__main__":
    main()
