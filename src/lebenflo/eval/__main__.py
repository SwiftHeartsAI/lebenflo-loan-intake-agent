"""Evaluate the agent against the ground truth.

Two questions:
1. Field-level extraction accuracy: did we read each value correctly?
2. Escalation accuracy: did flawed packets get escalated (for the right rule) and clean
   packets go through?

Usage:  uv run python -m lebenflo.eval
Writes reports/eval/eval_results.json and reports/eval/eval_report.md.
"""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime

from lebenflo.agent.__main__ import all_packet_ids, run_packets
from lebenflo.config import EVAL_DIR, GROUND_TRUTH_DIR, get_settings
from lebenflo.llm import get_llm
from lebenflo.tracing import setup_tracing


def values_match(expected, actual) -> bool:
    if actual is None:
        return False
    if isinstance(expected, int | float):
        try:
            return abs(float(expected) - float(actual)) <= 0.01
        except (TypeError, ValueError):
            return False
    return " ".join(str(expected).lower().split()) == " ".join(str(actual).lower().split())


def evaluate(states: list[dict]) -> dict:
    field_hits: dict[str, list[bool]] = defaultdict(list)  # "doc.field" -> [correct?]
    sources: Counter = Counter()
    packets = []
    for state in states:
        truth = json.loads((GROUND_TRUTH_DIR / f"{state['packet_id']}.json").read_text())
        extracted = state["documents"]
        for doc_type, doc in truth["documents"].items():
            got = extracted.get(doc_type, {})
            sources[got.get("source", "not extracted")] += 1
            for name, expected in doc["fields"].items():
                actual = got.get("fields", {}).get(name, {}).get("value")
                field_hits[f"{doc_type}.{name}"].append(values_match(expected, actual))

        actual_rules = sorted({r.split(":")[0] for r in state["reasons"]})
        packets.append(
            {
                "packet_id": state["packet_id"],
                "flaw": truth["flaw"],
                "expected_outcome": truth["expected_outcome"],
                "actual_outcome": state["outcome"],
                "outcome_correct": truth["expected_outcome"] == state["outcome"],
                "expected_reasons": truth["expected_reasons"],
                "actual_reasons": actual_rules,
                "reasons_correct": sorted(truth["expected_reasons"]) == actual_rules,
                # Looser check: was the flaw's own rule among the reasons (extra reasons allowed)?
                "expected_rule_found": set(truth["expected_reasons"]) <= set(actual_rules),
            }
        )

    all_hits = [hit for hits in field_hits.values() for hit in hits]
    flawed = [p for p in packets if p["flaw"]]
    clean = [p for p in packets if not p["flaw"]]
    return {
        "run_at": datetime.now(UTC).isoformat(),
        "extraction_sources": dict(sources),
        "field_accuracy": {
            "overall": round(sum(all_hits) / len(all_hits), 4),
            "fields_checked": len(all_hits),
            "per_field": {k: round(sum(v) / len(v), 4) for k, v in sorted(field_hits.items())},
        },
        "escalation": {
            "outcome_accuracy": round(sum(p["outcome_correct"] for p in packets) / len(packets), 4),
            "flawed_escalated": f"{sum(p['actual_outcome'] == 'ESCALATE_TO_HUMAN' for p in flawed)}/{len(flawed)}",
            "clean_approved": f"{sum(p['actual_outcome'] == 'APPROVE_FOR_UNDERWRITING' for p in clean)}/{len(clean)}",
            "flawed_caught_by_expected_rule": f"{sum(p['expected_rule_found'] for p in flawed)}/{len(flawed)}",
            "reason_accuracy": round(sum(p["reasons_correct"] for p in packets) / len(packets), 4),
            "escalations_by_rule": dict(Counter(r for p in packets for r in p["actual_reasons"])),
        },
        "packets": packets,
    }


def to_markdown(r: dict) -> str:
    simulated = "simulated" in r["extraction_sources"]
    lines = [
        "# Evaluation report",
        "",
        f"Run at {r['run_at']} · extraction sources: {r['extraction_sources']}",
        "",
    ]
    if simulated:
        lines += [
            "> **Note:** some extractions replayed *simulated* recordings built from the ground "
            "truth, so field accuracy for those is ~100% by construction. Run with "
            "`LEBENFLO_MODE=live` to measure real Document Intelligence accuracy.",
            "",
        ]
    e, f = r["escalation"], r["field_accuracy"]
    lines += [
        "## Summary",
        "| Metric | Value |",
        "|---|---|",
        f"| Field-level extraction accuracy | {f['overall']:.1%} ({f['fields_checked']} fields) |",
        f"| Outcome accuracy | {e['outcome_accuracy']:.1%} |",
        f"| Flawed packets escalated | {e['flawed_escalated']} |",
        f"| Flawed packets caught by their expected rule | {e['flawed_caught_by_expected_rule']} |",
        f"| Clean packets approved for underwriting | {e['clean_approved']} |",
        f"| Exactly the expected rule IDs (no extras) | {e['reason_accuracy']:.1%} |",
        f"| Findings by rule | {e['escalations_by_rule']} |",
        "",
        "## Per packet",
        "| Packet | Flaw | Expected | Actual | Rules | OK |",
        "|---|---|---|---|---|---|",
        *[
            f"| {p['packet_id']} | {p['flaw'] or '-'} | {p['expected_outcome']} | {p['actual_outcome']} | "
            f"{', '.join(p['actual_reasons']) or '-'} | {'✅' if p['outcome_correct'] and p['reasons_correct'] else '❌'} |"
            for p in r["packets"]
        ],
        "",
        "## Per field accuracy",
        "| Field | Accuracy |",
        "|---|---|",
        *[f"| {k} | {v:.0%} |" for k, v in f["per_field"].items()],
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    settings = get_settings()
    setup_tracing(settings)
    states = run_packets(all_packet_ids(), settings, get_llm(settings))
    results = evaluate(states)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "eval_results.json").write_text(json.dumps(results, indent=1))
    (EVAL_DIR / "eval_report.md").write_text(to_markdown(results))
    e = results["escalation"]
    print(
        f"Field accuracy {results['field_accuracy']['overall']:.1%} | outcome accuracy "
        f"{e['outcome_accuracy']:.1%} | flawed escalated {e['flawed_escalated']} | "
        f"sources {results['extraction_sources']}"
    )
    print(f"Report: {EVAL_DIR / 'eval_report.md'}")


if __name__ == "__main__":
    main()
