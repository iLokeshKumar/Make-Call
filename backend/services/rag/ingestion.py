"""
Document ingestion — chunking, TurboVec upsert (primary), ChromaDB upsert (fallback).

Chunking strategies:
  - Heading-based  : markdown split on H2/H3 (products, objections, playbooks, …)
  - Sliding window : overlapping token windows (transcripts)
  - Whole-doc      : fallback when no headings found and doc is short
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from .collections import COLLECTIONS, get_collection
from .embeddings import embed_batch
from .turbovec_store import get_store

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


def _doc_id(company_id: int, collection: str, title: str, chunk_index: int) -> str:
    """Deterministic, stable document ID."""
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
    Chunk a document and write to TurboVec (primary) + ChromaDB (fallback).

    Returns the list of doc IDs written.
    """
    if collection not in COLLECTIONS:
        raise ValueError(f"Unknown collection '{collection}'")

    chunks = chunk_document(content, collection)
    if not chunks:
        logger.warning("[RAG] No chunks produced for '%s' in %s", title, collection)
        return []

    # Remove stale chunks before re-indexing
    delete_document(company_id, collection, title)

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

    tv_ok = False
    chroma_ok = False

    # --- Primary: TurboVec ---
    try:
        get_store().add_chunks(
            company_id=company_id,
            collection=collection,
            contents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            doc_ids=ids,
        )
        tv_ok = True
    except Exception as exc:
        logger.warning("[RAG:TURBOVEC] write failed for '%s': %s", title, exc)

    # --- Fallback: ChromaDB (always kept in sync) ---
    try:
        chroma_col = get_collection(company_id, collection)
        chroma_col.upsert(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        chroma_ok = True
    except Exception as exc:
        logger.warning("[RAG:CHROMADB] write failed for '%s': %s", title, exc)

    logger.info(
        "[RAG] Indexed %d chunk(s) for '%s' → %s (company %d) | turbovec=%s chromadb=%s",
        len(chunks), title, collection, company_id,
        "OK" if tv_ok else "FAIL",
        "OK" if chroma_ok else "FAIL",
    )
    return ids


def delete_document(
    company_id: int,
    collection: str,
    title: str,
    max_chunks: int = 200,
) -> None:
    """Remove chunks from TurboVec and ChromaDB."""
    ids = [_doc_id(company_id, collection, title, i) for i in range(max_chunks)]

    tv_del = chroma_del = False
    try:
        get_store().remove_by_doc_ids(company_id, collection, ids)
        tv_del = True
    except Exception as exc:
        logger.warning("[RAG:TURBOVEC] delete failed for '%s': %s", title, exc)

    try:
        chroma_col = get_collection(company_id, collection)
        chroma_col.delete(ids=ids)
        chroma_del = True
    except Exception as exc:
        logger.warning("[RAG:CHROMADB] delete failed for '%s': %s", title, exc)

    logger.info(
        "[RAG] Deleted '%s' from %s (company %d) | turbovec=%s chromadb=%s",
        title, collection, company_id,
        "OK" if tv_del else "FAIL",
        "OK" if chroma_del else "FAIL",
    )
