"""
Hybrid retriever: vector search + BM25 keyword search + cross-encoder reranking.

Pipeline per query:
  1. Dense retrieval  — TurboVec cosine similarity, top-20
  2. Sparse retrieval — BM25 over the same collection corpus, top-20
  3. Fusion          — Reciprocal Rank Fusion (RRF) to merge both ranked lists
  4. Rerank          — cross-encoder scores the top-10 and returns top-N

BM25 and the cross-encoder are loaded lazily and are optional:
  - If rank_bm25 is not installed  → vector-only search
  - If CrossEncoder model can't load → skip reranking, return RRF results
"""
from __future__ import annotations

import logging
from typing import Optional

from .collections import COLLECTIONS, get_collection
from .embeddings import embed
from .turbovec_store import get_store

logger = logging.getLogger(__name__)

try:
    from rank_bm25 import BM25Okapi as _BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    logger.warning("[RAG] rank_bm25 not installed — using vector-only retrieval")

# Cross-encoder model — loaded once on first use
_reranker = None
_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"


def _get_reranker():
    global _reranker
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(_RERANKER_MODEL)
            logger.info("[RAG] Cross-encoder reranker loaded: %s", _RERANKER_MODEL)
        except Exception as exc:
            logger.warning("[RAG] CrossEncoder unavailable (%s) — skipping reranking", exc)
            _reranker = False  # sentinel: don't try again
    return _reranker if _reranker else None


# Vector search

def _vector_search(
    company_id: int,
    collection: str,
    query_embedding: list[float],
    n: int = 20,
) -> list[dict]:
    """TurboVec primary, ChromaDB fallback."""
    tv_count = get_store().count(company_id, collection)

    # --- Primary: TurboVec ---
    if tv_count > 0:
        try:
            results = get_store().search(company_id, collection, query_embedding, k=n)
            logger.info(
                "[RAG:TURBOVEC] vector search company=%d col=%s → %d results (index has %d chunks)",
                company_id, collection, len(results), tv_count,
            )
            return results
        except Exception as exc:
            logger.warning(
                "[RAG:TURBOVEC] search error company=%d col=%s — falling back to ChromaDB: %s",
                company_id, collection, exc,
            )
    else:
        logger.info(
            "[RAG:TURBOVEC] index empty company=%d col=%s — falling back to ChromaDB",
            company_id, collection,
        )

    # --- Fallback: ChromaDB ---
    try:
        col = get_collection(company_id, collection)
        count = col.count()
        if count == 0:
            logger.info(
                "[RAG:CHROMADB] also empty company=%d col=%s — no results",
                company_id, collection,
            )
            return []
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=min(n, count),
            include=["documents", "metadatas", "distances"],
        )
        docs = [
            {
                "content": doc,
                "metadata": results["metadatas"][0][i],
                "score": 1 - results["distances"][0][i],
                "source": "vector",
            }
            for i, doc in enumerate(results["documents"][0])
        ]
        logger.info(
            "[RAG:CHROMADB] vector search company=%d col=%s → %d results (index has %d chunks)",
            company_id, collection, len(docs), count,
        )
        return docs
    except Exception as exc:
        logger.warning(
            "[RAG:CHROMADB] vector search also failed company=%d col=%s: %s",
            company_id, collection, exc,
        )
        return []


# BM25 keyword search

def _bm25_search(
    company_id: int,
    collection: str,
    query: str,
    n: int = 20,
) -> list[dict]:
    """BM25 over corpus — TurboVec chunks primary, ChromaDB fallback."""
    if not _BM25_AVAILABLE:
        return []
    try:
        # --- Primary: TurboVec chunk store ---
        all_chunks = get_store().get_all_chunks(company_id, collection)
        documents = [c["content"] for c in all_chunks]
        metadatas = [c["metadata"] for c in all_chunks]

        if documents:
            logger.info(
                "[RAG:TURBOVEC] BM25 corpus company=%d col=%s — %d docs",
                company_id, collection, len(documents),
            )
        else:
            # --- Fallback: ChromaDB ---
            logger.info(
                "[RAG:TURBOVEC] BM25 corpus empty company=%d col=%s — falling back to ChromaDB",
                company_id, collection,
            )
            col = get_collection(company_id, collection)
            raw = col.get(include=["documents", "metadatas"])
            documents = raw["documents"]
            metadatas = raw["metadatas"]
            logger.info(
                "[RAG:CHROMADB] BM25 corpus company=%d col=%s — %d docs",
                company_id, collection, len(documents),
            )

        if not documents:
            return []

        tokenized_corpus = [doc.lower().split() for doc in documents]
        bm25 = _BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(query.lower().split())

        ranked = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )[:n]

        return [
            {
                "content": documents[i],
                "metadata": metadatas[i],
                "score": float(score),
                "source": "bm25",
            }
            for i, score in ranked
            if score > 0
        ]
    except Exception as exc:
        logger.warning("[RAG] BM25 search failed: %s", exc)
        return []


# Reciprocal Rank Fusion

def _rrf(
    list1: list[dict],
    list2: list[dict],
    k: int = 60,
) -> list[dict]:
    """
    Merge two ranked lists using Reciprocal Rank Fusion.
    Content string is used as the unique key (dedup across sources).
    """
    scores: dict[str, float] = {}
    docs_by_key: dict[str, dict] = {}

    for rank, doc in enumerate(list1):
        key = doc["content"]
        scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
        docs_by_key[key] = doc

    for rank, doc in enumerate(list2):
        key = doc["content"]
        scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
        docs_by_key.setdefault(key, doc)

    merged = sorted(docs_by_key.values(), key=lambda d: scores[d["content"]], reverse=True)
    return merged


# Cross-encoder reranking

def _rerank(query: str, docs: list[dict], n: int) -> list[dict]:
    """Rerank top docs with a cross-encoder. Falls back gracefully."""
    reranker = _get_reranker()
    if not reranker or not docs:
        return docs[:n]
    try:
        pairs = [(query, doc["content"]) for doc in docs]
        scores = reranker.predict(pairs)
        ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in ranked[:n]]
    except Exception as exc:
        logger.warning("[RAG] Reranking failed: %s", exc)
        return docs[:n]


# Public: search one collection

def search_collection(
    query: str,
    company_id: int,
    collection: str,
    n_results: int = 5,
) -> list[dict]:
    """Full hybrid search over a single company collection."""
    tv_count = get_store().count(company_id, collection)
    chroma_count = 0
    try:
        chroma_count = get_collection(company_id, collection).count()
    except Exception:
        pass
    if tv_count == 0 and chroma_count == 0:
        return []

    query_embedding = embed(query)

    # 1. Dense + sparse retrieval
    vector_results = _vector_search(company_id, collection, query_embedding, n=20)
    bm25_results = _bm25_search(company_id, collection, query, n=20)

    # 2. Merge with RRF
    merged = _rrf(vector_results, bm25_results)

    # 3. Rerank top-10, return top-N
    return _rerank(query, merged[:10], n=n_results)


# Public: search across all collections

def search_all_collections(
    query: str,
    company_id: int,
    n_results: int = 5,
) -> list[dict]:
    """Search all 7 collections and return a merged, reranked result."""
    all_results: list[dict] = []
    for col_name in COLLECTIONS:
        try:
            results = search_collection(query, company_id, col_name, n_results=3)
            for r in results:
                r["collection"] = col_name
            all_results.extend(results)
        except Exception as exc:
            logger.warning("[RAG] search failed for %s: %s", col_name, exc)

    # Final rerank across all collections
    return _rerank(query, all_results, n=n_results)
