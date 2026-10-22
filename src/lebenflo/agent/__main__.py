"""Run the intake agent on one packet or all of them.

Usage:  uv run python -m lebenflo.agent            # all packets
        uv run python -m lebenflo.agent P003       # one packet
Writes reports/runs/<packet>.json and reports/runs/<packet>_memo.md.
"""

import json
import sys

from lebenflo.agent.graph import build_graph
from lebenflo.config import PACKETS_DIR, RUNS_DIR, Settings, get_settings
from lebenflo.llm import LLM, get_llm
from lebenflo.tracing import setup_tracing


def run_packets(packet_ids: list[str], settings: Settings, llm: LLM) -> list[dict]:
    app = build_graph(settings, llm)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for packet_id in packet_ids:
        state = app.invoke({"packet_id": packet_id}, config={"run_name": f"intake {packet_id}"})
        (RUNS_DIR / f"{packet_id}.json").write_text(json.dumps(state, indent=1, default=str))
        (RUNS_DIR / f"{packet_id}_memo.md").write_text(state["memo"])
        results.append(state)
    return results


def all_packet_ids() -> list[str]:
    return sorted(p.name for p in PACKETS_DIR.iterdir() if p.is_dir())


def main() -> None:
    settings = get_settings()
    setup_tracing(settings)
    ids = sys.argv[1:] or all_packet_ids()
    for state in run_packets(ids, settings, get_llm(settings)):
        reasons = "; ".join(r.split(":")[0] for r in state["reasons"]) or "-"
        print(f"{state['packet_id']}  {state['outcome']:<26} {reasons}")
    print(f"Memos written to {RUNS_DIR}")


if __name__ == "__main__":
    main()
