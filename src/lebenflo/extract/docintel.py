"""Document Intelligence calls with record/replay.

live mode:    send the PDF to Azure, save the raw JSON response to data/recorded/.
offline mode: read that saved response instead. Tests, CI and the demo need no Azure access.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from opentelemetry import trace

from lebenflo.config import RECORDED_DIR, Settings

tracer = trace.get_tracer("lebenflo.extract")


def recording_path(packet_id: str, doc_type: str, model_id: str, root: Path = RECORDED_DIR) -> Path:
    return root / packet_id / f"{doc_type}.{model_id}.json"


def analyze(pdf: Path, packet_id: str, doc_type: str, model_id: str, settings: Settings) -> dict:
    """Return the analyze result as a JSON dict, plus `_source` ("azure" or "simulated")."""
    path = recording_path(packet_id, doc_type, model_id)
    with tracer.start_as_current_span(
        f"docintel {model_id}",
        attributes={
            "openinference.span.kind": "TOOL",
            "docintel.model_id": model_id,
            "lebenflo.packet_id": packet_id,
            "lebenflo.mode": settings.mode,
        },
    ):
        if settings.live:
            result = {
                "_source": "azure",
                "_model_id": model_id,
                "_recorded_at": datetime.now(UTC).isoformat(),
                "result": call_azure(pdf, model_id, settings),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=1))
            return result
        if not path.exists():
            raise FileNotFoundError(
                f"No recording at {path}. Run once with LEBENFLO_MODE=live, "
                "or create simulated recordings with `python -m lebenflo.extract.simulate`."
            )
        return json.loads(path.read_text())


def call_azure(pdf: Path, model_id: str, settings: Settings) -> dict:
    # Imported here so offline mode doesn't need the Azure SDK configured.
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    if not settings.docintel_endpoint or not settings.docintel_key:
        raise RuntimeError(
            "Set AZURE_DOCINTEL_ENDPOINT and AZURE_DOCINTEL_KEY in .env for live mode"
        )
    client = DocumentIntelligenceClient(
        settings.docintel_endpoint, AzureKeyCredential(settings.docintel_key)
    )
    with pdf.open("rb") as f:
        poller = client.begin_analyze_document(model_id, f, content_type="application/octet-stream")
    return poller.result().as_dict()
