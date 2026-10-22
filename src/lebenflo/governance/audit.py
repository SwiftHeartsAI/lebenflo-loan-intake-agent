"""Append-only audit log (JSON Lines): one line per pipeline decision.

Records who/what/when/why, the model used and confidence. Inputs are stored as SHA-256
hashes, never raw PII, so the log can be shared with auditors safely.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from lebenflo.config import AUDIT_LOG


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def log_event(
    packet_id: str,
    step: str,
    actor: str,
    detail: dict,
    model: str | None = None,
    input_hash: str | None = None,
    path: Path = AUDIT_LOG,
) -> dict:
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "packet_id": packet_id,
        "step": step,  # extract / validate / decide / memo
        "actor": actor,  # e.g. "docintel", "rules-engine", "llm", "agent"
        "model": model,
        "input_sha256": input_hash,
        "detail": detail,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")
    return event
