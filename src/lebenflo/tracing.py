"""Send traces to a local Arize Phoenix server.

Start Phoenix first:  uv run phoenix serve   (UI at http://localhost:6006)
OpenInference auto-instruments LangGraph/LangChain and the OpenAI client, so every graph node
and LLM call shows up as a span; our Document Intelligence calls add their own spans.
"""

from lebenflo.config import Settings

_registered = False


def setup_tracing(settings: Settings, project_name: str = "lebenflo-loan-intake") -> bool:
    global _registered
    if _registered or not settings.phoenix_endpoint:
        return _registered
    from phoenix.otel import register

    register(
        project_name=project_name,
        endpoint=settings.phoenix_endpoint.rstrip("/") + "/v1/traces",
        auto_instrument=True,
        verbose=False,
    )
    _registered = True
    return True
