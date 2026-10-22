"""RAG over Lebenflo's (fictional) lending policy, using Azure AI Search.

1. Chunk: split policy/lending_policy.md into one chunk per "## LP-n" section.
2. Embed: Azure OpenAI embeddings (text-embedding-3-small) for every chunk and every query.
3. Index: upload chunks + vectors to an Azure AI Search index (HNSW vector field + text fields).
4. Retrieve: hybrid search, i.e. keyword (BM25) and vector similarity fused with Reciprocal Rank
   Fusion, so exact policy terms ("W-2") and paraphrases ("income doesn't match") both match.
5. Ground: the agent puts the top section per finding in the memo and in the LLM prompt.

The queries are fixed per rule ID (not per packet), so `python -m lebenflo.rag` runs them once
in live mode and records the results. The agent and the hosted demo replay those results, with
no Azure calls.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from lebenflo.config import POLICY_FILE, POLICY_INDEX, Settings
from lebenflo.governance.audit import sha256

# What we "ask" the policy for each kind of finding. APPROVE is used when nothing was found.
RULE_QUERIES = {
    "V-001": "The applicant's name is different on two of the documents. How must a name "
    "discrepancy be handled?",
    "V-002": "Annualized pay stub income does not match the W-2 wages by more than 10 percent.",
    "V-003": "The loan packet is missing a required document such as the bank statement.",
    "V-004": "An extracted value has low confidence from the document reader. Can it be used?",
    "APPROVE": "All intake checks passed. Where is the packet sent next?",
}
# The section a correct retrieval should rank first; used by the eval (retrieval hit rate).
EXPECTED_SECTION = {
    "V-001": "LP-3",
    "V-002": "LP-4",
    "V-003": "LP-2",
    "V-004": "LP-6",
    "APPROVE": "LP-7",
}
TOP_K = 3


@dataclass
class Chunk:
    id: str
    title: str
    text: str


def chunk_policy(text: str) -> list[Chunk]:
    chunks = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        heading, _, body = block.partition("\n")
        section_id, _, title = heading.strip().partition(" ")
        chunks.append(Chunk(id=section_id, title=title.strip(), text=" ".join(body.split())))
    return chunks


def embed(texts: list[str], settings: Settings) -> list[list[float]]:
    from openai import AzureOpenAI

    if not settings.openai_embedding_deployment:
        raise RuntimeError("Set AZURE_OPENAI_EMBEDDING_DEPLOYMENT in .env")
    client = AzureOpenAI(
        azure_endpoint=settings.openai_endpoint,
        api_key=settings.openai_key,
        api_version=settings.openai_api_version,
    )
    response = client.embeddings.create(model=settings.openai_embedding_deployment, input=texts)
    return [d.embedding for d in response.data]


def create_search_index(settings: Settings, dimensions: int):
    """(Re)create the Azure AI Search index: text fields for BM25 + a vector field for HNSW."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    if not (settings.search_endpoint and settings.search_key):
        raise RuntimeError("Set AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_API_KEY in .env")
    index = SearchIndex(
        name=settings.search_index,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="section_id", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="title", type=SearchFieldDataType.String),
            SearchableField(name="text", type=SearchFieldDataType.String),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=dimensions,
                vector_search_profile_name="hnsw-profile",
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[
                VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw")
            ],
        ),
    )
    client = SearchIndexClient(settings.search_endpoint, AzureKeyCredential(settings.search_key))
    if settings.search_index in client.list_index_names():
        # Safety for shared search services: only replace an index this project created.
        existing = {f.name for f in client.get_index(settings.search_index).fields}
        if not {"section_id", "embedding"} <= existing:
            raise RuntimeError(
                f"Index '{settings.search_index}' exists and isn't ours; set AZURE_SEARCH_INDEX "
                "to a different name."
            )
        client.delete_index(settings.search_index)
    client.create_index(index)


def hybrid_search(
    settings: Settings, query: str, vector: list[float], k: int = TOP_K
) -> list[dict]:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.models import VectorizedQuery

    client = SearchClient(
        settings.search_endpoint, settings.search_index, AzureKeyCredential(settings.search_key)
    )
    results = client.search(
        search_text=query,  # keyword (BM25) half of the hybrid query
        vector_queries=[VectorizedQuery(vector=vector, k_nearest_neighbors=k, fields="embedding")],
        select=["section_id", "title", "text"],
        top=k,
    )
    return [
        {
            "section_id": r["section_id"],
            "title": r["title"],
            "text": r["text"],
            "score": round(float(r["@search.score"]), 5),  # RRF-fused hybrid score
        }
        for r in results
    ]


def build_index(settings: Settings) -> dict:
    """Live: embed, index in Azure AI Search, run every rule query, record the results."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    policy_text = POLICY_FILE.read_text()
    chunks = chunk_policy(policy_text)
    chunk_vectors = embed([f"{c.id} {c.title}. {c.text}" for c in chunks], settings)
    query_vectors = embed(list(RULE_QUERIES.values()), settings)

    create_search_index(settings, dimensions=len(chunk_vectors[0]))
    SearchClient(
        settings.search_endpoint, settings.search_index, AzureKeyCredential(settings.search_key)
    ).upload_documents(
        [
            {"id": c.id, "section_id": c.id, "title": c.title, "text": c.text, "embedding": v}
            for c, v in zip(chunks, chunk_vectors, strict=True)
        ]
    )
    wait_until_indexed(settings, len(chunks))

    recorded = {
        "search_service": settings.search_endpoint.split("//")[-1].split(".")[0],
        "search_index": settings.search_index,
        "embedding_model": settings.openai_embedding_deployment,
        "built_at": datetime.now(UTC).isoformat(),
        "policy_sha256": sha256(policy_text),
        "chunks": [c.__dict__ for c in chunks],
        "results": {
            key: {"query": q, "matches": hybrid_search(settings, q, v)}
            for (key, q), v in zip(RULE_QUERIES.items(), query_vectors, strict=True)
        },
    }
    POLICY_INDEX.parent.mkdir(parents=True, exist_ok=True)
    POLICY_INDEX.write_text(json.dumps(recorded, indent=1))
    return recorded


def wait_until_indexed(settings: Settings, expected: int, attempts: int = 20) -> None:
    """Uploads are searchable after a short delay; poll the document count."""
    import time

    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    client = SearchClient(
        settings.search_endpoint, settings.search_index, AzureKeyCredential(settings.search_key)
    )
    for _ in range(attempts):
        if client.get_document_count() >= expected:
            return
        time.sleep(1)


def load_index() -> dict | None:
    if not POLICY_INDEX.exists():
        return None
    return json.loads(POLICY_INDEX.read_text())


def index_is_current(index: dict) -> bool:
    """False if the policy text changed since it was indexed (rebuild with python -m lebenflo.rag)."""
    return index["policy_sha256"] == sha256(POLICY_FILE.read_text())


def retrieve(index: dict, query_key: str, k: int = 2) -> list[dict]:
    """Top-k policy sections for a rule ID (or "APPROVE"), from the recorded search results."""
    return index["results"][query_key]["matches"][:k]
