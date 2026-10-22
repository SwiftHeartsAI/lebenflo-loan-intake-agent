# Lebenflo Loan Document Intake Agent

> **Lebenflo Credit Union is fictional, and all data in this repo is synthetic.**
> Every document is watermarked "SAMPLE – SYNTHETIC TEST DATA". Names and employers are
> invented, and SSNs use the 900–999 area range, which is never issued.

An AI workflow agent that reads a member's loan application packet (pay stub, W-2, bank
statement, driver's license), cross-checks the documents, and writes an intake memo. It either
passes the packet to underwriting or escalates it to a human reviewer, with rule IDs as reasons.
**It never declines a loan.**

```
PDFs ──► extract (Azure AI Document Intelligence prebuilt models; layout + LLM fallback)
     ──► validate (rules V-001…V-004)
     ──► decide (APPROVE_FOR_UNDERWRITING | ESCALATE_TO_HUMAN)
     ──► memo (LLM summary of PII-masked facts)
         every step → audit log (JSONL) + Phoenix trace
```

## Quick start (offline: no Azure needed)

```bash
uv sync
uv run python -m lebenflo.generate          # 10 synthetic packets + ground truth
uv run python -m lebenflo.extract.simulate  # simulated DI recordings (until you run live)
uv run python -m lebenflo.agent             # run the agent, memos in reports/runs/
uv run python -m lebenflo.eval              # metrics in reports/eval/
uv run pytest
```

Tracing: run `uv run phoenix serve` in another terminal, then open http://localhost:6006.
Traces go to the `lebenflo-loan-intake` project.

## Live mode (real Azure)

1. `cp .env.example .env` and fill in the values (see below), then set `LEBENFLO_MODE=live`.
2. `uv run python -m lebenflo.eval`. This calls Azure and saves every raw response to
   `data/recorded/`.
3. Set `LEBENFLO_MODE=offline` again. The demo now replays the **real** recordings.

| Variable | Where to find it |
|---|---|
| `AZURE_DOCINTEL_ENDPOINT` | Document Intelligence resource → Keys and Endpoint → Endpoint |
| `AZURE_DOCINTEL_KEY` | same page → KEY 1 |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource → Keys and Endpoint (`https://<name>.openai.azure.com/`) |
| `AZURE_OPENAI_API_KEY` | same page → KEY 1 |
| `AZURE_OPENAI_API_VERSION` | `2024-10-21` (GA) |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | the *deployment name* you gave the chat model in AI Foundry |

## Rules

| ID | Escalates when |
|---|---|
| V-001 | Applicant name differs across documents |
| V-002 | Annualized pay stub income differs from W-2 wages by more than 10% |
| V-003 | A required document is missing |
| V-004 | A decision field was read with confidence below 0.80, or not read at all |

## Results

Live run against Azure AI Document Intelligence and Azure OpenAI. The raw responses are recorded,
so `uv run python -m lebenflo.eval` reproduces these offline. Full report:
[reports/eval/eval_report.md](reports/eval/eval_report.md).

| Metric | Result |
|---|---|
| Field-level extraction accuracy | 92.2% (225/244) |
| Flawed packets escalated for their expected rule | 3/3 |
| Clean packets approved for underwriting | 0/7 (V-004: bank statement ending balance read correctly but at 0.74 confidence) |

The agent never missed a flaw, but it is over-cautious:
- **Bank statement ending balance:** read correctly every time but at 0.74 confidence, which
  trips V-004 on every packet. This is a calibration issue, not a misread. The next step is
  per-field thresholds, or corroborating the value (beginning + deposits − withdrawals = ending).
  The threshold was deliberately not tuned on these same 10 packets.
- **W-2:** the prebuilt W-2 model didn't recognise the synthetic layout, so all 10 used the
  layout + LLM fallback. It read name, employer, wages and tax year 100% correctly. The SSN is
  masked before the LLM, so it isn't extracted, by design.
- **Driver's license:** one day/month swap on the date of birth and expiry, at low confidence,
  correctly escalated by V-004. The license number lost its "N" prefix on 7 of 10.

## Layout

```
src/lebenflo/generate/    synthetic packets + ground truth
src/lebenflo/extract/     DI client (record/replay), field mapping, layout+LLM fallback
src/lebenflo/validate/    rules V-001..V-004
src/lebenflo/governance/  PII masking, audit log
src/lebenflo/agent/       LangGraph graph + CLI
src/lebenflo/eval/        evaluation vs ground truth
src/lebenflo/llm.py       Azure OpenAI + fake LLM (all prompts masked here)
```
