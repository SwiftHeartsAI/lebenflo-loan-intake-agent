"""Send traces to a local Arize Phoenix server.

Start Phoenix first:  uv run phoenix serve   (UI at http://localhost:6006)
OpenInference auto-instruments LangGraph/LangChain and the OpenAI client, so every graph node
and LLM call shows up as a span; our Document Intelligence calls add their own spans.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from openinference.instrumentation.langchain import LangChainInstrumentor, get_current_span
from opentelemetry import trace

from lebenflo.config import Settings

_registered = False


@contextmanager
def inside_graph_node() -> Iterator[None]:
    """Make the running LangGraph node's span the parent of spans started inside it.

    OpenInference records each node as a span but doesn't set it as OpenTelemetry's current
    span, so without this the Document Intelligence and OpenAI spans start their own traces
    instead of nesting under `extract` / `memo` in Phoenix.
    """
    # Checked first: get_current_span() logs a warning when LangChain isn't instrumented.
    instrumented = LangChainInstrumentor().is_instrumented_by_opentelemetry
    span = get_current_span() if instrumented else None
    if span is None:  # tracing off, or not running inside the graph
        yield
        return
    with trace.use_span(span, end_on_exit=False):
        yield


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
