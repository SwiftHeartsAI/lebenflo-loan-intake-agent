"""Extract every document in a packet.

1. Classify: by file name (pay_stub.pdf -> pay_stub). Our intake portal would ask members to
   upload each document into a labelled slot; production could add a DI custom classifier.
2. Run the matching prebuilt model.
3. If the prebuilt model found less than 60% of the fields, fall back to prebuilt-layout
   (plain OCR text) and ask the LLM to pull the fields out of the masked text.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from lebenflo.config import Settings
from lebenflo.extract.docintel import analyze, recording_path
from lebenflo.extract.fields import (
    FIELD_MAP,
    LAYOUT_MODEL_ID,
    MODEL_IDS,
    ExtractedDocument,
    ExtractedField,
    fields_from_result,
    found_ratio,
    normalize,
)
from lebenflo.governance.audit import log_event, sha256
from lebenflo.governance.pii import mask_pii
from lebenflo.llm import LLM

FALLBACK_THRESHOLD = 0.6
# Masked before the LLM sees the text, so the fallback cannot extract them.
PII_FIELDS = {"employee_ssn", "account_number", "date_of_birth"}


def extract_packet(packet_dir: Path, settings: Settings, llm: LLM) -> dict[str, ExtractedDocument]:
    documents = {}
    for pdf in sorted(packet_dir.glob("*.pdf")):
        doc_type = pdf.stem
        if doc_type not in MODEL_IDS:
            continue  # unknown upload; a reviewer would see it in the packet
        doc = extract_document(pdf, packet_dir.name, doc_type, settings, llm)
        documents[doc_type] = doc
        log_event(
            packet_dir.name,
            "extract",
            "docintel",
            model=doc.model_id,
            input_hash=sha256(pdf.read_bytes()),
            detail={
                "doc_type": doc_type,
                "method": doc.method,
                "source": doc.source,
                "confidence": {k: f.confidence for k, f in doc.fields.items()},
            },
        )
    return documents


def extract_document(
    pdf: Path, packet_id: str, doc_type: str, settings: Settings, llm: LLM
) -> ExtractedDocument:
    model_id = MODEL_IDS[doc_type]
    recorded = analyze(pdf, packet_id, doc_type, model_id, settings)
    fields = fields_from_result(doc_type, recorded["result"])
    if found_ratio(fields) >= FALLBACK_THRESHOLD:
        return ExtractedDocument(
            doc_type=doc_type,
            file=pdf.name,
            model_id=model_id,
            method="prebuilt",
            source=recorded["_source"],
            fields=fields,
        )
    return extract_with_layout_and_llm(pdf, packet_id, doc_type, settings, llm)


def extract_with_layout_and_llm(
    pdf: Path, packet_id: str, doc_type: str, settings: Settings, llm: LLM
) -> ExtractedDocument:
    layout = analyze(pdf, packet_id, doc_type, LAYOUT_MODEL_ID, settings)
    text = layout["result"].get("content", "")
    # The LLM gives no calibrated confidence, so we use how confidently the OCR read the page.
    words = [w for p in layout["result"].get("pages", []) for w in p.get("words", [])]
    ocr_confidence = round(mean(w.get("confidence", 0.0) for w in words), 3) if words else 0.0

    wanted = {
        name: kind for name, (_, kind) in FIELD_MAP[doc_type].items() if name not in PII_FIELDS
    }
    answer = llm_extract(packet_id, doc_type, text, wanted, settings, llm)

    fields = {}
    for name, (_, kind) in FIELD_MAP[doc_type].items():
        value = normalize(answer.get(name), kind) if name in wanted else None
        fields[name] = ExtractedField(
            value=value, confidence=ocr_confidence if value is not None else 0.0
        )
    return ExtractedDocument(
        doc_type=doc_type,
        file=pdf.name,
        model_id=f"{LAYOUT_MODEL_ID}+llm",
        method="layout+llm",
        source=layout["_source"],
        fields=fields,
    )


def llm_extract(
    packet_id: str, doc_type: str, text: str, wanted: dict[str, str], settings: Settings, llm: LLM
) -> dict:
    """Ask the LLM for the fields as JSON. Responses are recorded like DI responses."""
    path = recording_path(packet_id, doc_type, "llm-extraction")
    if not settings.live:
        return json.loads(path.read_text())["response"] if path.exists() else {}
    system = (
        "You extract fields from a loan document. Reply with one JSON object using exactly "
        "these keys; use null when a value is not present. Dates as YYYY-MM-DD, amounts as "
        f"plain numbers. Keys and types: {json.dumps(wanted)}"
    )
    user = mask_pii(text)
    response = json.loads(llm.complete(system, user, json_mode=True) or "{}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "_model": llm.name,
                "_recorded_at": datetime.now(UTC).isoformat(),
                "prompt_sha256": sha256(system + user),
                "response": response,
            },
            indent=1,
        )
    )
    return response
