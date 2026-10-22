"""End-to-end: run the agent offline on the committed packets and check against ground truth."""

import json

from lebenflo.agent.__main__ import all_packet_ids, run_packets
from lebenflo.config import GROUND_TRUTH_DIR, get_settings
from lebenflo.eval.__main__ import evaluate
from lebenflo.llm import FakeLLM


def test_agent_catches_every_flaw_and_never_leaks_pii():
    llm = FakeLLM()
    states = run_packets(all_packet_ids(), get_settings(), llm)
    results = evaluate(states)

    # Every flawed packet is escalated for its own rule. Clean packets may still be escalated
    # (e.g. V-004 low confidence on real Azure output): extra caution is allowed, misses are not.
    for p in results["packets"]:
        if p["flaw"]:
            assert p["actual_outcome"] == "ESCALATE_TO_HUMAN" and p["expected_rule_found"], p
    assert {s["outcome"] for s in states} <= {"APPROVE_FOR_UNDERWRITING", "ESCALATE_TO_HUMAN"}

    # No SSN, account number or DOB from any packet appears in any prompt sent to the LLM.
    prompts = "\n".join(llm.prompts)
    for truth_file in GROUND_TRUTH_DIR.glob("*.json"):
        truth = json.loads(truth_file.read_text())
        assert truth["applicant"]["ssn"] not in prompts
        assert truth["applicant"]["date_of_birth"] not in prompts
        bank = truth["documents"].get("bank_statement")
        if bank:
            assert bank["fields"]["account_number"] not in prompts
