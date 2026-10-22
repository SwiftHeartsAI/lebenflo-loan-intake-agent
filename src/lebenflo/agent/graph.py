"""The intake agent: a LangGraph workflow  extract -> validate -> decide -> memo.

Design choice: the *decision* is deterministic (rules), and the LLM only writes a plain-English
summary for the reviewer. The agent can never decline a loan; it either passes the packet on to
underwriting or escalates it to a human, with rule IDs as reasons.
"""

import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from lebenflo.config import PACKETS_DIR, Settings
from lebenflo.extract.fields import ExtractedDocument
from lebenflo.extract.pipeline import extract_packet
from lebenflo.governance.audit import log_event, sha256
from lebenflo.governance.pii import mask_account
from lebenflo.llm import LLM
from lebenflo.validate.rules import DECISION_FIELDS, Finding, periods_per_year, run_rules

APPROVE = "APPROVE_FOR_UNDERWRITING"
ESCALATE = "ESCALATE_TO_HUMAN"


class IntakeState(TypedDict, total=False):
    packet_id: str
    documents: dict[str, dict]  # doc_type -> ExtractedDocument (as dict, so state is JSON)
    findings: list[dict]
    outcome: str
    reasons: list[str]
    memo: str


def load_docs(state: IntakeState) -> dict[str, ExtractedDocument]:
    return {k: ExtractedDocument(**v) for k, v in state["documents"].items()}


def build_graph(settings: Settings, llm: LLM, packets_dir: Path = PACKETS_DIR):
    def extract(state: IntakeState) -> IntakeState:
        docs = extract_packet(packets_dir / state["packet_id"], settings, llm)
        return {"documents": {k: d.model_dump() for k, d in docs.items()}}

    def validate(state: IntakeState) -> IntakeState:
        findings = run_rules(load_docs(state))
        # Rule IDs and messages only: details can contain names, which stay out of the log.
        log_event(
            state["packet_id"],
            "validate",
            "rules-engine",
            detail={"findings": [{"rule_id": f.rule_id, "message": f.message} for f in findings]},
        )
        return {"findings": [f.model_dump() for f in findings]}

    def decide(state: IntakeState) -> IntakeState:
        # Any finding -> a human looks at it. There is deliberately no "decline" branch.
        reasons = [f"{f['rule_id']}: {f['message']}" for f in state["findings"]]
        outcome = ESCALATE if reasons else APPROVE
        log_event(
            state["packet_id"], "decide", "agent", detail={"outcome": outcome, "reasons": reasons}
        )
        return {"outcome": outcome, "reasons": reasons}

    def memo(state: IntakeState) -> IntakeState:
        facts = memo_facts(state, packets_dir)
        system = (
            "You write a short intake summary for a credit union loan reviewer. Use only the "
            "facts given. Do not recommend approval or decline; explain what was checked and "
            "what the reviewer should look at. 3-5 sentences."
        )
        user = json.dumps(facts, indent=1)
        summary = llm.complete(system, user)
        log_event(
            state["packet_id"],
            "memo",
            "llm",
            model=llm.name,
            input_hash=sha256(system + user),
            detail={"chars": len(summary)},
        )
        return {"memo": render_memo(state, facts, summary)}

    graph = StateGraph(IntakeState)
    graph.add_node("extract", extract)
    graph.add_node("validate", validate)
    graph.add_node("decide", decide)
    graph.add_node("memo", memo)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "validate")
    graph.add_edge("validate", "decide")
    graph.add_edge("decide", "memo")
    graph.add_edge("memo", END)
    return graph.compile()


def memo_facts(state: IntakeState, packets_dir: Path) -> dict:
    """The only data the LLM sees: no SSN, no DOB, account number masked."""
    docs = load_docs(state)
    application = json.loads((packets_dir / state["packet_id"] / "application.json").read_text())
    stub, w2, bank = docs.get("pay_stub"), docs.get("w2"), docs.get("bank_statement")
    annualized = None
    if (
        stub
        and stub.value("gross_pay")
        and stub.value("pay_period_start")
        and stub.value("pay_period_end")
    ):
        periods = periods_per_year(stub.value("pay_period_start"), stub.value("pay_period_end"))
        annualized = round(float(stub.value("gross_pay")) * periods, 2)
    return {
        "packet_id": state["packet_id"],
        "applicant_name": application["applicant_name"],
        "loan_amount": application["loan_amount"],
        "loan_purpose": application["loan_purpose"],
        "employer": stub.value("employer_name") if stub else None,
        "annualized_pay_stub_income": annualized,
        "w2_wages": w2.value("wages") if w2 else None,
        "bank_account": mask_account(str(bank.value("account_number")))
        if bank and bank.value("account_number")
        else None,
        "bank_ending_balance": bank.value("ending_balance") if bank else None,
        "documents_received": sorted(docs),
        "outcome": state["outcome"],
        "findings": [Finding(**f).model_dump() for f in state["findings"]],
    }


def render_memo(state: IntakeState, facts: dict, summary: str) -> str:
    docs = load_docs(state)
    lines = [
        f"# Intake memo – packet {state['packet_id']}",
        "",
        "_Lebenflo Credit Union is fictional. All data is synthetic._",
        "",
        f"**Outcome:** `{state['outcome']}`",
        "",
        "**Reasons:** " + ("none – all checks passed" if not state["reasons"] else ""),
        *[f"- {r}" for r in state["reasons"]],
        "",
        "## Documents",
        "| Document | Method | Source | Lowest confidence (fields the rules use) |",
        "|---|---|---|---|",
        *[
            f"| {d.doc_type} | {d.model_id} | {d.source} | "
            f"{min(d.fields[n].confidence for n in DECISION_FIELDS[d.doc_type]):.2f} |"
            for d in docs.values()
        ],
        "",
        "## Key figures",
        f"- Applicant: {facts['applicant_name']} · Loan: ${facts['loan_amount']:,.0f} ({facts['loan_purpose']})",
        f"- Employer: {facts['employer']}",
        f"- Annualized pay stub income: {money(facts['annualized_pay_stub_income'])} · "
        f"W-2 wages: {money(facts['w2_wages'])}",
        f"- Bank account: {facts['bank_account']} · ending balance {money(facts['bank_ending_balance'])}",
        "",
        "## Summary for the reviewer",
        summary,
        "",
        "_This agent never declines an application. Any adverse decision is made by a human reviewer._",
    ]
    return "\n".join(lines)


def money(x) -> str:
    return f"${float(x):,.2f}" if x is not None else "n/a"
