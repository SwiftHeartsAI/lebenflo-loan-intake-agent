"""Create SIMULATED Document Intelligence recordings from the ground truth.

Why: so the pipeline, tests and CI run before any Azure resource exists. These files have
the same JSON shape as real DI responses but are marked `"_source": "simulated"`, and every
eval report says which source it used. Simulated accuracy is ~100% by construction and is
NOT a measure of Document Intelligence; rerun with LEBENFLO_MODE=live for real numbers.

Real ("azure") recordings are never overwritten.

Usage:  uv run python -m lebenflo.extract.simulate
"""

import json
import random

from lebenflo.config import GROUND_TRUTH_DIR, RECORDED_DIR
from lebenflo.extract.docintel import recording_path
from lebenflo.extract.fields import FIELD_MAP, MODEL_IDS

VALUE_KEY = {"string": "valueString", "date": "valueDate", "number": "valueNumber"}


def set_path(fields: dict, path: str, leaf: dict) -> None:
    """Inverse of fields.get_path for object paths like 'Employee.Name'."""
    *parents, last = path.split(".")
    container = fields
    for part in parents:
        container = container.setdefault(part, {"type": "object", "valueObject": {}})["valueObject"]
    container[last] = leaf


def simulated_result(doc_type: str, truth_fields: dict, rng: random.Random) -> dict:
    fields: dict = {}
    for name, (path, kind) in FIELD_MAP[doc_type].items():
        value = truth_fields[name]
        leaf = {
            "type": kind,
            VALUE_KEY[kind]: value,
            "content": str(value),
            "confidence": round(rng.uniform(0.86, 0.99), 3),
        }
        if ".0." in path:  # array of objects, e.g. Accounts.0.AccountNumber
            array_name, _, child = path.split(".", 2)
            node = fields.setdefault(array_name, {"type": "array", "valueArray": []})
            if not node["valueArray"]:
                node["valueArray"].append({"type": "object", "valueObject": {}})
            set_path(node["valueArray"][0]["valueObject"], child, leaf)
        else:
            set_path(fields, path, leaf)
    return {"modelId": MODEL_IDS[doc_type], "documents": [{"docType": doc_type, "fields": fields}]}


def main(seed: int = 7) -> None:
    rng = random.Random(seed)
    written = skipped = 0
    for truth_file in sorted(GROUND_TRUTH_DIR.glob("*.json")):
        truth = json.loads(truth_file.read_text())
        for doc_type, doc in truth["documents"].items():
            path = recording_path(truth["packet_id"], doc_type, MODEL_IDS[doc_type])
            if path.exists() and json.loads(path.read_text()).get("_source") == "azure":
                skipped += 1
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "_source": "simulated",
                        "_model_id": MODEL_IDS[doc_type],
                        "result": simulated_result(doc_type, doc["fields"], rng),
                    },
                    indent=1,
                )
            )
            written += 1
    print(f"Wrote {written} simulated recordings to {RECORDED_DIR} (kept {skipped} real ones)")


if __name__ == "__main__":
    main()
