"""Streamlit demo for the Lebenflo loan intake agent.

Runs in offline mode: every Azure AI Document Intelligence, Azure OpenAI and embedding response
is replayed from data/recorded/ (captured in a live run), so the hosted demo needs no keys and
costs nothing, while showing real model output.

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
    POLICY_FILE,
    SQL_DIR,
    Settings,
    get_settings,
)
from lebenflo.eval.__main__ import evaluate, values_match
from lebenflo.governance.pii import mask_pii
from lebenflo.llm import OfflineLLM
from lebenflo.rag.policy import (
    EXPECTED_SECTION,
    RULE_QUERIES,
    index_is_current,
    load_index,
    retrieve,
)
from lebenflo.validate.rules import CONFIDENCE_THRESHOLD, DECISION_FIELDS
from lebenflo.warehouse import build_warehouse

REPO_URL = "https://github.com/SwiftHeartsAI/lebenflo-loan-intake-agent"
NODE_LABELS = {
    "extract": "Extract fields (Document Intelligence prebuilt models, layout + LLM fallback)",
    "validate": "Validate (rules V-001 to V-004)",
    "policy_check": "Policy check (RAG over the lending policy)",
    "decide": "Decide (approve for underwriting or escalate, never decline)",
    "memo": "Write memo (LLM summary of PII-masked facts)",
}
RULE_NAMES = {
    "V-001": "Name mismatch across documents",
    "V-002": "Pay stub vs W-2 income gap > 10%",
    "V-003": "Required document missing",
    "V-004": f"Decision field below {CONFIDENCE_THRESHOLD:.2f} confidence",
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


# ---------- sidebar ----------

with st.sidebar:
    st.markdown("### 🏦 Lebenflo Loan Intake Agent")
    st.warning(
        "**Lebenflo Credit Union is fictional.** All people, employers, SSNs and documents "
        "are synthetic test data."
    )
    st.markdown(
        "An AI workflow agent that reads a member's loan packet, cross-checks the documents "
        "against each other and the lending policy, and routes it to underwriting or to a human. "
        "**It never declines a loan.**"
    )
    st.info(
        "**Demo mode:** replays the real Azure responses recorded in a live run. "
        "No keys needed, no live calls."
    )
    st.markdown(f"[Source code on GitHub]({REPO_URL})")

st.title("Loan Document Intake Agent")
st.caption(
    "Azure AI Document Intelligence · Azure OpenAI (AI Foundry) · LangGraph · RAG · "
    "DuckDB SQL · Arize Phoenix · PII masking & audit trail"
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
            st.markdown(f"- `{reason.split(':')[0]}` {reason.split(':', 1)[1].strip()}")
        expected = truth["expected_outcome"]
        st.caption(
            f"Ground truth: injected flaw = {truth['flaw'] or 'none'}, "
            f"expected outcome = {expected}, expected rule = "
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
            rows = [
                {
                    "field": name,
                    "extracted": f["value"],
                    "confidence": round(f["confidence"], 3),
                    "used by rules": name in DECISION_FIELDS[doc_type],
                    "matches ground truth": values_match(truth_fields.get(name), f["value"]),
                }
                for name, f in doc["fields"].items()
            ]
            df = pd.DataFrame(rows)
            df["extracted"] = df["extracted"].astype(str)
            st.dataframe(
                df.style.apply(
                    lambda r: (
                        ["background-color: rgba(255,170,0,.25)"] * len(r)
                        if r["confidence"] < CONFIDENCE_THRESHOLD
                        else [""] * len(r)
                    ),
                    axis=1,
                ),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                f"Highlighted rows are below the {CONFIDENCE_THRESHOLD:.2f} confidence threshold. "
                "SSNs appear here because this is synthetic data, but they are masked "
                "before any text is sent to the LLM."
            )

            st.subheader("Policy check (RAG)")
            if not state.get("policy_refs"):
                st.info("Policy index not built yet.")
            for ref in state.get("policy_refs", []):
                top = ref["matches"][0]
                with st.expander(
                    f"{ref['query']} → {top['section_id']} {top['title']} "
                    f"(similarity {top['score']:.3f})"
                ):
                    st.markdown(f"**Query:** _{RULE_QUERIES[ref['query']]}_")
                    for m in ref["matches"]:
                        st.markdown(
                            f"**{m['section_id']} {m['title']}** · score {m['score']:.3f}\n\n{m['text']}"
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
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Field-level extraction accuracy",
        f"{f['overall']:.1%}",
        help=f"{f['fields_checked']} fields",
    )
    c2.metric("Flawed packets caught (right rule)", e["flawed_caught_by_expected_rule"])
    c3.metric("Clean packets passed to underwriting", e["clean_approved"])
    index = load_index()
    if index:
        hits = sum(retrieve(index, k, 1)[0]["section_id"] == v for k, v in EXPECTED_SECTION.items())
        c4.metric("RAG retrieval hit@1", f"{hits}/{len(EXPECTED_SECTION)}")

    st.markdown("#### What the numbers say")
    st.markdown(
        "- **No flaw was missed.** Name mismatch, income gap and missing document were each "
        "escalated for the right rule.\n"
        "- **The agent is over-cautious.** Document Intelligence reads the bank statement's ending "
        "balance correctly every time, but at **0.737 confidence**, just under the 0.80 threshold, so "
        "V-004 sends clean packets to a human. That's the safe failure mode, and the fix is per-field "
        "calibration. I did not tune the threshold on these same 10 packets, because that would be "
        "overfitting the test set.\n"
        "- **The confidence gate caught a real error.** On P008 the model swapped day and month on "
        "the license dates (at 0.49–0.72 confidence), and V-004 escalated it.\n"
        "- **The W-2 fell back to layout + LLM** on every packet (the prebuilt model didn't recognise "
        "the synthetic layout). The LLM read wages and names 100% correctly; the SSN is masked "
        "before the LLM, so it is deliberately not extracted."
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
    if index:
        st.markdown("#### RAG retrieval")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "query (rule)": k,
                        "expected section": v,
                        "retrieved #1": (top := retrieve(index, k, 2))[0]["section_id"],
                        "score #1": top[0]["score"],
                        "retrieved #2": top[1]["section_id"],
                        "score #2": top[1]["score"],
                        "hit@1": top[0]["section_id"] == v,
                    }
                    for k, v in EXPECTED_SECTION.items()
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        if not index_is_current(index):
            st.warning("The policy text changed after it was embedded; rebuild the index.")

# ---------- tab 3: SQL analytics ----------

with tab_sql:
    st.markdown(
        "Agent results are loaded into **DuckDB** tables (`packets`, `documents`, `fields`, "
        "`findings`, `policy_refs`). The analytics views are plain SQL in "
        "[`sql/views.sql`](" + REPO_URL + "/blob/main/sql/views.sql), the same SQL you'd "
        "run on Snowflake or feed into Power BI."
    )
    con = warehouse()
    views = {
        "Exception rate by rule": "v_exception_rate_by_rule",
        "Field quality (accuracy & confidence)": "v_field_quality",
        "Outcome vs expected (ground truth)": "v_outcome_vs_expected",
        "Extraction path by document type": "v_extraction_path",
        "Loan-to-income by packet": "v_loan_to_income",
    }
    choice = st.selectbox("View", list(views))
    view_sql = (SQL_DIR / "views.sql").read_text()
    start = view_sql.find(f"CREATE VIEW {views[choice]}")
    block_start = view_sql.rfind("\n\n", 0, start) + 2
    st.code(view_sql[block_start : view_sql.find(";", start) + 1], language="sql")
    result = con.sql(f"SELECT * FROM {views[choice]}").df()
    st.dataframe(result, hide_index=True, use_container_width=True)
    if choice == "Exception rate by rule":
        st.bar_chart(result, x="rule_id", y="packets_flagged")

    st.markdown("#### Try your own query")
    query = st.text_area(
        "Read-only SQL",
        "SELECT rule_id, COUNT(*) AS n\nFROM findings\nGROUP BY rule_id\nORDER BY n DESC",
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
        "Document Intelligence has to read raw documents, but **no SSN, account number or "
        "date of birth ever reaches the LLM**. Every prompt passes through one function, "
        "`mask_pii()`, and a test asserts that no packet's SSN, DOB or account number "
        "appears in any prompt."
    )
    sample = st.text_area(
        "Text going to the LLM",
        "Employee Bea Pennywhistle, SSN 970-47-6925, "
        "account 0031831063, DOB: 07/03/1972, pay date 10/03/2026.",
    )
    st.code(mask_pii(sample), language=None)

    st.markdown("#### Audit trail")
    st.markdown(
        "Every step writes a JSON line: time, step, actor, model, confidence, and the "
        "**SHA-256 hash** of the input instead of the raw document."
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
        "decision (policy LP-10).\n"
        "- **No automated declines.** Adverse action is a human decision with ECOA notices (LP-7).\n"
        "- **Uncertainty means escalation.** Low-confidence values go to a person (LP-6).\n"
        "- **Grounded summaries.** The memo cites the policy sections retrieved for each finding.\n"
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
  policy [label="policy_check\\nRAG: embeddings +\\ncosine search"];
  decide [label="decide\\napprove for UW /\\nescalate"];
  memo [label="memo\\nLLM summary\\n(PII masked)", fillcolor="#f3eefb"];
  audit [label="Audit log\\n(hashes, no PII)", shape=cylinder, fillcolor="#eef8ee"];
  wh [label="DuckDB\\nSQL views", shape=cylinder, fillcolor="#eef8ee"];
  phoenix [label="Arize Phoenix\\ntraces", fillcolor="#eef8ee"];
  pdfs -> extract -> validate -> policy -> decide -> memo;
  extract -> fallback [style=dashed, label="< 60% fields"]; fallback -> validate [style=dashed];
  memo -> wh; {extract validate policy decide memo} -> audit [style=dotted, color=gray];
  memo -> phoenix [style=dotted, color=gray];
}
""")
    st.markdown("#### Components")
    st.dataframe(
        pd.DataFrame(
            [
                (
                    "Intelligent document processing",
                    "Azure AI Document Intelligence v4.0: prebuilt-payStub.us, prebuilt-tax.us.w2, prebuilt-bankStatement.us, prebuilt-idDocument, prebuilt-layout",
                    "src/lebenflo/extract/",
                ),
                (
                    "Generative AI",
                    "Azure OpenAI via Azure AI Foundry (chat model for the fallback extraction and the memo)",
                    "src/lebenflo/llm.py",
                ),
                (
                    "Workflow agent",
                    "LangGraph state graph: extract → validate → policy_check → decide → memo",
                    "src/lebenflo/agent/graph.py",
                ),
                (
                    "RAG / semantic search",
                    "Azure OpenAI embeddings (text-embedding-3-small) over a chunked lending policy, cosine similarity, cited sections",
                    "src/lebenflo/rag/ · policy/",
                ),
                (
                    "Python + SQL data pipeline",
                    "Results loaded into DuckDB tables, analytics views in SQL (portable to Snowflake)",
                    "src/lebenflo/warehouse.py · sql/",
                ),
                (
                    "Evaluation & observability",
                    "Ground-truth eval (field accuracy, escalation accuracy, retrieval hit@1); Arize Phoenix tracing via OpenInference",
                    "src/lebenflo/eval/ · src/lebenflo/tracing.py",
                ),
                (
                    "Data governance",
                    "PII masking before the LLM, hashed audit log, synthetic data, no auto-decline",
                    "src/lebenflo/governance/",
                ),
                (
                    "CI/CD & source control",
                    "GitHub Actions: ruff + pytest on every push, fully offline (recorded responses)",
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
        "In **live** mode every Azure response (Document Intelligence, chat and embeddings) is "
        "saved to `data/recorded/`. **Offline** mode replays them by prompt hash. That's how "
        "this hosted demo shows real model output with no keys, and how tests and CI run "
        "without cloud access."
    )
    st.markdown("#### What I'd add for production")
    st.markdown(
        "Human-in-the-loop `interrupt()` with a checkpointer, so escalations pause for a reviewer's "
        "decision · Azure AI Search for hybrid retrieval over larger policy sets · Snowflake as the "
        "warehouse with Power BI on the views · FastAPI endpoints for the loan origination system · "
        "per-field confidence calibration · Presidio for free-text PII · Key Vault + managed "
        "identity · queue-based workers (Service Bus + Container Apps) for scale."
    )
    with st.expander("Lebenflo lending policy (fictional), the RAG corpus"):
        st.markdown(POLICY_FILE.read_text())
