"""Document Intelligence spans must nest under the agent's `extract` span, not start new traces."""

from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from lebenflo.agent.__main__ import run_packets
from lebenflo.config import get_settings
from lebenflo.extract import docintel
from lebenflo.llm import OfflineLLM


def test_docintel_spans_nest_under_extract(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(docintel, "tracer", provider.get_tracer("test"))
    LangChainInstrumentor().instrument(tracer_provider=provider)
    try:
        run_packets(["P003"], get_settings(), OfflineLLM())
    finally:
        LangChainInstrumentor().uninstrument()

    spans = exporter.get_finished_spans()
    extract = next(s for s in spans if s.name == "extract")
    docintel_spans = [s for s in spans if s.name.startswith("docintel ")]
    assert docintel_spans
    for s in docintel_spans:
        assert s.parent is not None and s.parent.span_id == extract.context.span_id, s.name
