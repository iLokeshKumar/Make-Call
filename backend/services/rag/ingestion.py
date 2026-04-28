"""
Document ingestion — chunking, dedup, and ChromaDB upsert.

Chunking strategies:
  - Heading-based  : markdown split on H2/H3 (products, objections, playbooks, …)
  - Sliding window : overlapping token windows (transcripts)
  - Whole-doc      : fallback when no headings found and doc is short
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .collections import COLLECTIONS, get_collection
from .embeddings import embed_batch

logger = logging.getLogger(__name__)

# ~4 chars per token is a safe approximation for English text
_CHARS_PER_TOKEN = 4
_WINDOW_TOKENS = 300
_OVERLAP_TOKENS = 50
_MAX_WHOLE_DOC_TOKENS = 400  # docs shorter than this are kept as one chunk


# Chunking helpers

def _chunk_by_heading(text: str) -> list[str]:
    """Split markdown text on H2 (##) or H3 (###) headings."""
    parts = re.split(r"(?m)^#{2,3}\s+", text)
    chunks = [p.strip() for p in parts if p.strip()]
    return chunks


def _chunk_sliding_window(
    text: str,
    window_tokens: int = _WINDOW_TOKENS,
    overlap_tokens: int = _OVERLAP_TOKENS,
) -> list[str]:
    """Overlapping character windows (used for transcripts)."""
    window_chars = window_tokens * _CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * _CHARS_PER_TOKEN
    step = max(1, window_chars - overlap_chars)

    chunks = []
    for start in range(0, len(text), step):
        chunk = text[start : start + window_chars].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def chunk_document(content: str, collection: str) -> list[str]:
    """Return a list of text chunks appropriate for the given collection."""
    if collection == "transcripts":
        return _chunk_sliding_window(content)

    # Try heading-based split first
    chunks = _chunk_by_heading(content)
    if chunks:
        return chunks

    # Fallback: keep as one chunk if short enough, else sliding window
    if len(content) <= _MAX_WHOLE_DOC_TOKENS * _CHARS_PER_TOKEN:
        return [content.strip()]
    return _chunk_sliding_window(content)


# ChromaDB upsert / delete

def _doc_id(company_id: int, collection: str, title: str, chunk_index: int) -> str:
    """Deterministic, stable ChromaDB document ID."""
    key = f"{company_id}::{collection}::{title}::{chunk_index}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def index_document(
    company_id: int,
    collection: str,
    title: str,
    content: str,
    tags: Optional[list] = None,
    extra_metadata: Optional[dict] = None,
) -> list[str]:
    """
    Chunk a document and upsert all chunks into ChromaDB.

    Returns the list of ChromaDB doc IDs that were written.
    """
    if collection not in COLLECTIONS:
        raise ValueError(f"Unknown collection '{collection}'")

    chunks = chunk_document(content, collection)
    if not chunks:
        logger.warning("[RAG] No chunks produced for '%s' in %s", title, collection)
        return []

    chroma_col = get_collection(company_id, collection)

    ids = [_doc_id(company_id, collection, title, i) for i in range(len(chunks))]
    embeddings = embed_batch(chunks)
    metadatas = [
        {
            "company_id": company_id,
            "collection": collection,
            "title": title,
            "chunk_index": i,
            "tags": ",".join(tags or []),
            **(extra_metadata or {}),
        }
        for i in range(len(chunks))
    ]

    chroma_col.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    logger.info(
        "[RAG] Indexed %d chunk(s) for '%s' → %s (company %d)",
        len(chunks), title, collection, company_id,
    )
    return ids


def delete_document(
    company_id: int,
    collection: str,
    title: str,
    max_chunks: int = 200,
) -> None:
    """Remove all ChromaDB chunks for the given document title."""
    chroma_col = get_collection(company_id, collection)
    ids = [_doc_id(company_id, collection, title, i) for i in range(max_chunks)]
    # ChromaDB delete ignores IDs that don't exist — safe to call speculatively
    try:
        chroma_col.delete(ids=ids)
        logger.info("[RAG] Deleted chunks for '%s' from %s (company %d)", title, collection, company_id)
    except Exception as exc:
        logger.warning("[RAG] Delete failed for '%s': %s", title, exc)
