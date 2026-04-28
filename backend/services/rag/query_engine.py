"""
Public search API — the single import point for all agents and routes.

Usage:
    from services.rag.query_engine import search

    results = search("price too high objection", company_id=42, collection="objections")
    for r in results:
        print(r["content"], r["collection"], r["metadata"])
"""
from __future__ import annotations

import logging

from .collections import COLLECTIONS
from .retriever import search_all_collections, search_collection

logger = logging.getLogger(__name__)


def search(
    query: str,
    company_id: int,
    collection: str = "all",
    n_results: int = 5,
) -> list[dict]:
    """
    Hybrid semantic search over the company's knowledge base.

    Args:
        query       : Natural-language search string
        company_id  : Tenant ID — each company's KB is fully isolated
        collection  : One of the 7 collection names, or "all" to search all
        n_results   : Maximum number of results to return

    Returns:
        List of result dicts:
            {
                "content"    : str,   # the matched text chunk
                "collection" : str,   # which collection it came from
                "metadata"   : dict,  # title, tags, chunk_index, …
                "score"      : float, # relevance score (higher = better)
                "source"     : str,   # "vector" | "bm25"
            }
    """
    if not query or not query.strip():
        return []

    if collection == "all":
        results = search_all_collections(query, company_id, n_results=n_results)
    elif collection in COLLECTIONS:
        results = search_collection(query, company_id, collection, n_results=n_results)
        for r in results:
            r.setdefault("collection", collection)
    else:
        logger.warning("[RAG] Unknown collection '%s', falling back to 'all'", collection)
        results = search_all_collections(query, company_id, n_results=n_results)

    return results


def format_for_prompt(results: list[dict], max_chars: int = 3000) -> str:
    """
    Format search results as a compact string suitable for injecting into
    an LLM prompt. Truncates to max_chars to stay within context limits.
    """
    if not results:
        return "No relevant knowledge found."

    parts = []
    total = 0
    for r in results:
        header = f"[{r.get('collection', '?').upper()}] {r.get('metadata', {}).get('title', '')}"
        block = f"{header}\n{r['content']}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)

    return "\n\n---\n\n".join(parts)
