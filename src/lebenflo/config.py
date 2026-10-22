"""Settings and project paths.

Settings come from environment variables, optionally loaded from a `.env` file in the
repo root. We parse `.env` ourselves (a few lines) instead of adding a dependency.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKETS_DIR = ROOT / "data" / "synthetic" / "packets"
GROUND_TRUTH_DIR = ROOT / "data" / "synthetic" / "ground_truth"
RECORDED_DIR = ROOT / "data" / "recorded"
AUDIT_LOG = ROOT / "data" / "audit" / "audit_log.jsonl"
RUNS_DIR = ROOT / "reports" / "runs"
EVAL_DIR = ROOT / "reports" / "eval"
POLICY_FILE = ROOT / "policy" / "lending_policy.md"
POLICY_INDEX = RECORDED_DIR / "policy_search.json"  # recorded Azure AI Search results
LLM_RECORDINGS = RECORDED_DIR / "llm"
WAREHOUSE_DB = ROOT / "data" / "warehouse.duckdb"
AZURE_SQL_SNAPSHOT = RECORDED_DIR / "azure_sql_views.json"  # view results read back from Azure SQL
SQL_DIR = ROOT / "sql"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    mode: str  # "offline" or "live"
    docintel_endpoint: str
    docintel_key: str
    openai_endpoint: str
    openai_key: str
    openai_api_version: str
    openai_chat_deployment: str
    openai_embedding_deployment: str
    search_endpoint: str
    search_key: str
    search_index: str
    sql_server: str
    sql_database: str
    sql_user: str
    sql_password: str
    phoenix_endpoint: str

    @property
    def live(self) -> bool:
        return self.mode == "live"


def get_settings() -> Settings:
    load_dotenv()
    env = os.environ.get
    return Settings(
        mode=env("LEBENFLO_MODE", "offline").lower(),
        docintel_endpoint=env("AZURE_DOCINTEL_ENDPOINT", ""),
        docintel_key=env("AZURE_DOCINTEL_KEY", ""),
        openai_endpoint=env("AZURE_OPENAI_ENDPOINT", ""),
        openai_key=env("AZURE_OPENAI_API_KEY", ""),
        openai_api_version=env("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        openai_chat_deployment=env("AZURE_OPENAI_CHAT_DEPLOYMENT", ""),
        openai_embedding_deployment=env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""),
        search_endpoint=env("AZURE_SEARCH_ENDPOINT", ""),
        search_key=env("AZURE_SEARCH_API_KEY", ""),
        search_index=env("AZURE_SEARCH_INDEX", "lebenflo-policy"),
        sql_server=env("AZURE_SQL_SERVER", ""),
        sql_database=env("AZURE_SQL_DATABASE", "lebenflo"),
        sql_user=env("AZURE_SQL_USER", ""),
        sql_password=env("AZURE_SQL_PASSWORD", ""),
        phoenix_endpoint=env("PHOENIX_COLLECTOR_ENDPOINT", ""),
    )
