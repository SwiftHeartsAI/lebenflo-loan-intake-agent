"""Build the policy index in Azure AI Search and record the retrieval results (live mode).

Usage:  uv run python -m lebenflo.rag
Writes data/recorded/policy_search.json, which the agent, tests and the hosted demo replay.
"""

from lebenflo.config import POLICY_INDEX, get_settings
from lebenflo.rag.policy import EXPECTED_SECTION, build_index, retrieve


def main() -> None:
    index = build_index(get_settings())
    print(
        f"Indexed {len(index['chunks'])} policy sections in Azure AI Search "
        f"'{index['search_service']}/{index['search_index']}' ({index['embedding_model']})"
    )
    for key, expected in EXPECTED_SECTION.items():
        top = retrieve(index, key, k=2)
        mark = "OK" if top[0]["section_id"] == expected else "MISS"
        print(
            f"{key:<8} -> {top[0]['section_id']} ({top[0]['score']:.4f}), "
            f"{top[1]['section_id']} ({top[1]['score']:.4f})  expected {expected} {mark}"
        )
    print(f"Saved {POLICY_INDEX}")


if __name__ == "__main__":
    main()
