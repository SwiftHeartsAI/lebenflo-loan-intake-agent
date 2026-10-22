"""Streamlit demo for the Lebenflo loan intake agent.

Runs in offline mode: every Azure AI Document Intelligence and Azure OpenAI response is replayed
from data/recorded/ (captured in a live run), so the hosted demo needs no keys and costs nothing,
while showing real model output.

Run locally:  uv run streamlit run streamlit_app.py
"""

import json

import pandas as pd
import streamlit as st

from lebenflo.agent.__main__ import all_packet_ids
from lebenflo.agent.graph import build_graph
from lebenflo.config import (
    AUDIT_LOG,
    GROUND_TRUTH_DIR,
    PACKETS_DIR,
    SQL_DIR,
    Settings,
    get_settings,
)
from lebenflo.eval.__main__ import evaluate, values_match
from lebenflo.governance.pii import mask_pii
from lebenflo.llm import OfflineLLM
from lebenflo.validate.rules import CONFIDENCE_THRESHOLD, DECISION_FIELDS
from lebenflo.warehouse import VIEWS, build_warehouse

REPO_URL = "https://github.com/SwiftHeartsAI/lebenflo-loan-intake-agent"
NODE_LABELS = {
    "extract": "Extract fields (Document Intelligence prebuilt models, layout + LLM fallback)",
    "validate": "Validate (rules V-001 to V-004)",
    "decide": "Decide (approve for underwriting or escalate, never decline)",
    "memo": "Write memo (LLM summary of PII-masked facts)",
}

st.set_page_config(page_title="Lebenflo Loan Intake Agent", page_icon="🏦", layout="wide")


# ---------- cached data ----------


def offline_settings() -> Settings:
    """Always offline in the app: replay recordings, never call Azure, no tracing endpoint."""
    s = get_settings()
    return Settings(**{**s.__dict__, "mode": "offline", "phoenix_endpoint": ""})


@st.cache_resource
def agent():
    return build_graph(offline_settings(), OfflineLLM())


@st.cache_data
def ground_truth(packet_id: str) -> dict:
    return json.loads((GROUND_TRUTH_DIR / f"{packet_id}.json").read_text())


@st.cache_data
def run_all() -> list[dict]:
    return [agent().invoke({"packet_id": pid}) for pid in all_packet_ids()]


@st.cache_resource
def warehouse():
    return build_warehouse(run_all())


def packet_label(pid: str) -> str:
    t = ground_truth(pid)
    flaw = f" · injected flaw: {t['flaw'].replace('_', ' ')}" if t["flaw"] else " · clean"
    return f"{pid} – {t['applicant']['full_name']}{flaw}"


def view_sql(view: str) -> str:
    """The CREATE VIEW statement for one view, with its comment, from sql/views.sql."""
    text = (SQL_DIR / "views.sql").read_text()
    start = text.find(f"CREATE VIEW lebenflo.{view}")
    block_start = text.rfind("\n\n", 0, start) + 2
    return text[block_start : text.find(";", start) + 1]


# ---------- sidebar ----------

with st.sidebar:
    st.markdown("### 🏦 Lebenflo Loan Intake Agent")
    st.warning(
        "**Lebenflo Credit Union is fictional.** All people, employers, SSNs and documents "
        "are synthetic test data."
    )
    st.markdown(
        "An AI workflow agent that reads a member's loan packet, cross-checks the documents, "
        "and routes it to underwriting or to a human reviewer. **It never declines a loan.**"
    )
    st.info(
        "**Demo mode:** replays the real Azure responses recorded in a live run. "
        "No keys needed, no live calls."
    )
    st.markdown(f"[Source code on GitHub]({REPO_URL})")

st.title("Loan Document Intake Agent")
st.caption(
    "Azure AI Document Intelligence · Azure OpenAI (AI Foundry) · LangGraph · SQL analytics · "
    "Arize Phoenix · PII masking & audit trail"
)

tab_demo, tab_eval, tab_sql, tab_gov, tab_arch = st.tabs(
    ["🧾 Run intake", "📊 Evaluation", "🗄️ SQL analytics", "🛡️ Governance", "🏗️ How it works"]
)

# ---------- tab 1: run the agent on one packet ----------

with tab_demo:
    ids = all_packet_ids()
    col_pick, col_btn = st.columns([4, 1], vertical_alignment="bottom")
    pid = col_pick.selectbox(
        "Loan application packet", ids, index=ids.index("P003"), format_func=packet_label
    )
    run = col_btn.button("▶ Run intake agent", type="primary", use_container_width=True)

    if run or st.session_state.get("last_pid") == pid:
        if run:
            state: dict = {"packet_id": pid}
            with st.status("Running the LangGraph workflow…", expanded=True) as status:
                for update in agent().stream({"packet_id": pid}, stream_mode="updates"):
                    for node, change in update.items():
                        state.update(change)
                        st.write(f"✅ {NODE_LABELS.get(node, node)}")
                status.update(label="Workflow complete", state="complete", expanded=False)
            st.session_state.update(last_pid=pid, last_state=state)
        state = st.session_state["last_state"]
        truth = ground_truth(pid)

        if state["outcome"] == "APPROVE_FOR_UNDERWRITING":
            st.success(f"**{state['outcome']}**: all intake checks passed.")
        else:
            st.warning(f"**{state['outcome']}**: a human reviewer must look at this packet.")
        for reason in state["reasons"]:
            rule_id, message = reason.split(":", 1)
            st.markdown(f"- `{rule_id}` {message.strip()}")
        st.caption(
            f"Ground truth: injected flaw = {truth['flaw'] or 'none'}, "
            f"expected outcome = {truth['expected_outcome']}, expected rule = "
            f"{', '.join(truth['expected_reasons']) or 'none'}"
        )

        left, right = st.columns([1, 1])
        with left:
            st.subheader("Documents")
            present = sorted(state["documents"])
            missing = [d for d in DECISION_FIELDS if d not in present]
            if missing:
                st.error(f"Missing from packet: {', '.join(missing)}")
            doc_type = st.radio(
                "Document",
                present,
                horizontal=True,
                key=f"doc_{pid}",
                format_func=lambda d: d.replace("_", " "),
            )
            st.pdf(str(PACKETS_DIR / pid / f"{doc_type}.pdf"), height=520)

        with right:
            st.subheader("Extracted fields")
            doc = state["documents"][doc_type]
            st.caption(
                f"Model: `{doc['model_id']}` · method: {doc['method']} · "
                f"source: {doc['source']} (recorded Azure response)"
            )
            truth_fields = truth["documents"].get(doc_type, {}).get("fields", {})
            df = pd.DataFrame(
                [
                    {
                        "field": name,
                        "extracted": str(f["value"]),
                        "confidence": round(f["confidence"], 3),
                        "used by rules": name in DECISION_FIELDS[doc_type],
                        "matches ground truth": values_match(truth_fields.get(name), f["value"]),
                    }
                    for name, f in doc["fields"].items()
                ]
            )
            low = "background-color: rgba(255,170,0,.25)"
            st.dataframe(
                df.style.apply(
                    lambda r: [low if r["confidence"] < CONFIDENCE_THRESHOLD else ""] * len(r),
                    axis=1,
                ),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                f"Highlighted rows are below the {CONFIDENCE_THRESHOLD:.2f} confidence threshold. "
                "SSNs appear here because this is synthetic data, but they are masked before any "
                "text is sent to the LLM."
            )

        st.subheader("Intake memo")
        with st.container(border=True):
            st.markdown(state["memo"].replace("$", "\\$"))  # "$" would start LaTeX

# ---------- tab 2: evaluation ----------

with tab_eval:
    results = evaluate(run_all())
    e, f = results["escalation"], results["field_accuracy"]
    st.markdown(
        "Every packet has a ground-truth answer key, so the agent is scored objectively. "
        f"Extraction source: **{', '.join(results['extraction_sources'])}** "
        "(real Azure AI Document Intelligence responses)."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Field-level extraction accuracy",
        f"{f['overall']:.1%}",
        help=f"{f['fields_checked']} fields",
    )
    c2.metric("Flawed packets caught (right rule)", e["flawed_caught_by_expected_rule"])
    c3.metric("Clean packets passed to underwriting", e["clean_approved"])

    st.markdown("#### What the numbers say")
    st.markdown(
        "- **No flaw was missed.** Name mismatch, income gap and missing document were each "
        "escalated for the right rule.\n"
        "- **The agent is over-cautious.** Document Intelligence reads the bank statement's ending "
        "balance correctly every time, but at **0.737 confidence**, just under the 0.80 threshold, "
        "so V-004 sends clean packets to a human. That's the safe failure mode, and the fix is "
        "per-field calibration. I did not tune the threshold on these same 10 packets, because "
        "that would be overfitting the test set.\n"
        "- **The confidence gate caught a real error.** On P008 the model swapped day and month on "
        "the license dates (at 0.49–0.72 confidence), and V-004 escalated it.\n"
        "- **The W-2 fell back to layout + LLM** on every packet (the prebuilt model didn't "
        "recognise the synthetic layout). The LLM read wages and names 100% correctly; the SSN is "
        "masked before the LLM, so it is deliberately not extracted."
    )
    st.markdown("#### Per packet")
    st.dataframe(
        pd.DataFrame(results["packets"]).drop(columns=["reasons_correct"]),
        hide_index=True,
        use_container_width=True,
    )
    st.markdown("#### Per field accuracy")
    per_field = pd.DataFrame([{"field": k, "accuracy": v} for k, v in f["per_field"].items()])
    st.bar_chart(per_field, x="field", y="accuracy", horizontal=True, height=620)

# ---------- tab 3: SQL analytics ----------

with tab_sql:
    st.markdown(
        "Agent results are loaded into SQL tables (`packets`, `documents`, `fields`, `findings`) "
        "in a **DuckDB** database. The analytics views are portable SQL in "
        f"[`sql/views.sql`]({REPO_URL}/blob/main/sql/views.sql), written to run on Azure SQL or "
        "Snowflake as well, and ready to feed a Power BI report."
    )
    con = warehouse()
    titles = {
        "v_exception_rate_by_rule": "Exception rate by rule",
        "v_field_quality": "Field quality (accuracy & confidence)",
        "v_outcome_vs_expected": "Outcome vs expected (ground truth)",
        "v_extraction_path": "Extraction path by document type",
        "v_loan_to_income": "Loan-to-income by packet",
    }
    view = st.selectbox("View", list(VIEWS), format_func=titles.get)
    st.code(view_sql(view), language="sql")
    result = con.sql(f"SELECT * FROM lebenflo.{view} ORDER BY {VIEWS[view]}").df()
    st.dataframe(result, hide_index=True, use_container_width=True)
    if view == "v_exception_rate_by_rule":
        st.bar_chart(result, x="rule_id", y="packets_flagged")

    st.markdown("#### Try your own query")
    query = st.text_area(
        "Read-only SQL",
        "SELECT rule_id, COUNT(*) AS n\nFROM lebenflo.findings\nGROUP BY rule_id\nORDER BY n DESC",
        height=110,
    )
    if st.button("Run query"):
        if not query.strip().lower().startswith(("select", "with")):
            st.error("Only SELECT queries are allowed here.")
        else:
            try:
                st.dataframe(con.sql(query).df(), hide_index=True, use_container_width=True)
            except Exception as exc:  # show SQL errors to the user instead of crashing
                st.error(str(exc))

# ---------- tab 4: governance ----------

with tab_gov:
    st.markdown("#### PII masking (try it)")
    st.markdown(
        "Document Intelligence has to read raw documents, but **no SSN, account number or date of "
        "birth ever reaches the LLM**. Every prompt passes through one function, `mask_pii()`, "
        "and a test asserts that no packet's SSN, DOB or account number appears in any prompt."
    )
    sample = st.text_area(
        "Text going to the LLM",
        "Employee Bea Pennywhistle, SSN 970-47-6925, account 0031831063, "
        "DOB: 07/03/1972, pay date 10/03/2026.",
    )
    st.code(mask_pii(sample), language=None)

    st.markdown("#### Audit trail")
    st.markdown(
        "Every step writes a JSON line: time, step, actor, model, confidence, and the **SHA-256 "
        "hash** of the input instead of the raw document."
    )
    if AUDIT_LOG.exists():
        events = [json.loads(line) for line in AUDIT_LOG.read_text().splitlines()[-400:]]
        audit_pid = st.selectbox("Packet", all_packet_ids(), key="audit_pid")
        latest = [ev for ev in events if ev["packet_id"] == audit_pid][-8:]
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        **{k: ev[k] for k in ("timestamp", "step", "actor", "model")},
                        "input_sha256": (ev["input_sha256"] or "")[:16] + "…",
                        "detail": json.dumps(ev["detail"])[:160],
                    }
                    for ev in latest
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("#### Responsible AI choices")
    st.markdown(
        "- **Rules decide, the LLM explains.** Routing is deterministic and every escalation cites "
        "a rule ID, so it is consistent and auditable. The LLM never makes or recommends a credit "
        "decision.\n"
        "- **No automated declines.** Adverse action is a human decision, with the notices fair "
        "lending rules require.\n"
        "- **Uncertainty means escalation.** Values read with low confidence go to a person.\n"
        "- **Synthetic data only.** Never-issued SSN range 900–999, fictional employers, and a "
        "watermark on every page."
    )

# ---------- tab 5: architecture ----------

with tab_arch:
    st.graphviz_chart("""
digraph {
  rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#eef3fb", fontname="Helvetica"];
  pdfs [label="Loan packet PDFs\\n(pay stub, W-2, bank stmt, ID)", fillcolor="#fff6e5"];
  extract [label="extract\\nDocument Intelligence\\nprebuilt models"];
  fallback [label="layout + LLM\\nfallback", fillcolor="#f3eefb"];
  validate [label="validate\\nrules V-001…V-004"];
  decide [label="decide\\napprove for UW /\\nescalate"];
  memo [label="memo\\nLLM summary\\n(PII masked)", fillcolor="#f3eefb"];
  audit [label="Audit log\\n(hashes, no PII)", shape=cylinder, fillcolor="#eef8ee"];
  wh [label="SQL tables\\n+ views", shape=cylinder, fillcolor="#eef8ee"];
  phoenix [label="Arize Phoenix\\ntraces", fillcolor="#eef8ee"];
  pdfs -> extract -> validate -> decide -> memo;
  extract -> fallback [style=dashed, label="< 60% fields"]; fallback -> validate [style=dashed];
  memo -> wh; {extract validate decide memo} -> audit [style=dotted, color=gray];
  memo -> phoenix [style=dotted, color=gray];
}
""")
    st.markdown("#### Components")
    st.dataframe(
        pd.DataFrame(
            [
                (
                    "Intelligent document processing",
                    "Azure AI Document Intelligence v4.0: prebuilt-payStub.us, prebuilt-tax.us.w2, "
                    "prebuilt-bankStatement.us, prebuilt-idDocument, prebuilt-layout",
                    "src/lebenflo/extract/",
                ),
                (
                    "Generative AI",
                    "Azure OpenAI via Azure AI Foundry: fallback extraction and the reviewer memo",
                    "src/lebenflo/llm.py",
                ),
                (
                    "Workflow agent",
                    "LangGraph state graph: extract → validate → decide → memo",
                    "src/lebenflo/agent/graph.py",
                ),
                (
                    "Python + SQL data pipeline",
                    "Results loaded into SQL tables with analytics views (portable SQL)",
                    "src/lebenflo/warehouse.py · sql/",
                ),
                (
                    "Evaluation & observability",
                    "Ground-truth eval (field accuracy, escalation accuracy); Arize Phoenix tracing "
                    "via OpenInference",
                    "src/lebenflo/eval/ · src/lebenflo/tracing.py",
                ),
                (
                    "Data governance",
                    "PII masking before the LLM, hashed audit log, synthetic data, no auto-decline",
                    "src/lebenflo/governance/",
                ),
                (
                    "CI/CD & source control",
                    "GitHub Actions: ruff + pytest on every push, fully offline",
                    ".github/workflows/ci.yml",
                ),
            ],
            columns=["Area", "What's used", "Where"],
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.markdown("#### Record / replay")
    st.markdown(
        "In **live** mode every Azure response (Document Intelligence and Azure OpenAI) is saved to "
        "`data/recorded/`. **Offline** mode replays them, matching LLM calls by prompt hash. That's "
        "how this hosted demo shows real model output with no keys, and how tests and CI run "
        "without cloud access."
    )
    st.markdown("#### What I'd add for production")
    st.markdown(
        "Human-in-the-loop `interrupt()` with a checkpointer, so escalations pause for a reviewer's "
        "decision · a RAG policy check with Azure AI Search, citing the lending-policy section "
        "behind each finding · Azure SQL or Snowflake as the warehouse with Power BI on the views · "
        "FastAPI endpoints for the loan origination system · per-field confidence calibration · "
        "Presidio for free-text PII · Key Vault + managed identity · queue-based workers "
        "(Service Bus + Container Apps) for scale."
    )
