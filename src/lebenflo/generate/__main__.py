"""Generate the synthetic packets and their ground-truth answer keys.

Usage:  uv run python -m lebenflo.generate [--count 10] [--seed 42]
"""

import argparse
import json
import random
import shutil
from pathlib import Path

from lebenflo.config import GROUND_TRUTH_DIR, PACKETS_DIR
from lebenflo.generate.pdfs import DRAWERS
from lebenflo.generate.profiles import FLAW_TO_RULE, MISSING_DOC_TYPE, Applicant, make_applicant

OUTCOME_APPROVE = "APPROVE_FOR_UNDERWRITING"
OUTCOME_ESCALATE = "ESCALATE_TO_HUMAN"


def ground_truth(a: Applicant) -> dict:
    """The answer key the eval compares the pipeline against."""
    documents = {
        doc_type: {
            "file": f"{doc_type}.pdf",
            "fields": {k: v for k, v in fields.items() if not k.startswith("_")},
        }
        for doc_type, fields in a.documents.items()
    }
    return {
        "packet_id": a.packet_id,
        "synthetic": True,
        "applicant": {
            "full_name": a.full_name,
            "date_of_birth": a.dob.isoformat(),
            "ssn": a.ssn,
            "address": a.address,
            "employer": a.employer,
            "annual_salary": a.annual_salary,
            "pay_frequency": a.pay_frequency,
        },
        "application": {"loan_amount": a.loan_amount, "loan_purpose": a.loan_purpose},
        "documents": documents,
        "flaw": a.flaw,
        "missing_documents": [MISSING_DOC_TYPE] if a.flaw == "missing_document" else [],
        "expected_outcome": OUTCOME_ESCALATE if a.flaw else OUTCOME_APPROVE,
        "expected_reasons": [FLAW_TO_RULE[a.flaw]] if a.flaw else [],
    }


def generate(
    count: int = 10,
    seed: int = 42,
    packets_dir: Path = PACKETS_DIR,
    truth_dir: Path = GROUND_TRUTH_DIR,
) -> list[dict]:
    rng = random.Random(seed)  # one seeded RNG -> identical output on every run
    shutil.rmtree(packets_dir, ignore_errors=True)
    shutil.rmtree(truth_dir, ignore_errors=True)
    truth_dir.mkdir(parents=True)
    results = []
    for i in range(1, count + 1):
        a = make_applicant(i, rng)
        packet_dir = packets_dir / a.packet_id
        packet_dir.mkdir(parents=True)
        for doc_type, fields in a.documents.items():
            DRAWERS[doc_type](a, fields, packet_dir / f"{doc_type}.pdf")
        # The application form itself is structured data, so it is plain JSON (no SSN in it).
        (packet_dir / "application.json").write_text(
            json.dumps(
                {
                    "packet_id": a.packet_id,
                    "applicant_name": a.full_name,
                    **ground_truth(a)["application"],
                },
                indent=2,
            )
        )
        truth = ground_truth(a)
        (truth_dir / f"{a.packet_id}.json").write_text(json.dumps(truth, indent=2))
        results.append(truth)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    results = generate(args.count, args.seed)
    flawed = [t["packet_id"] for t in results if t["flaw"]]
    print(f"Generated {len(results)} packets in {PACKETS_DIR} ({len(flawed)} flawed: {flawed})")


if __name__ == "__main__":
    main()
