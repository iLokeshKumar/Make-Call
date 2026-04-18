"""
ChromaDB collection registry.

Each company gets its own isolated namespace:
    company_{company_id}_{collection}

e.g. company_42_products, company_42_objections
"""
from __future__ import annotations

import logging
import os

import chromadb

logger = logging.getLogger(__name__)

# Collection catalogue

COLLECTIONS: list[str] = [
    "products",      # product specs, pricing, features
    "objections",    # objection → handling guide
    "competitors",   # competitor battle cards
    "playbooks",     # SOPs, scripts, discovery frameworks
    "coaching",      # coaching tips, best practices
    "sops",          # standard operating procedures
    "transcripts",   # past call transcripts (auto-indexed post-call)
]

# ChromaDB singleton

_chroma_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _chroma_client
    if _chroma_client is None:
        path = os.getenv("CHROMA_PATH", "./knowledge_base")
        logger.info("[RAG] Initialising ChromaDB at %s", path)
        _chroma_client = chromadb.PersistentClient(path=path)
    return _chroma_client


# Naming helpers

def collection_name(company_id: int, collection: str) -> str:
    """Returns the ChromaDB collection name for a company+collection pair."""
    if collection not in COLLECTIONS:
        raise ValueError(f"Unknown collection '{collection}'. Valid: {COLLECTIONS}")
    return f"company_{company_id}_{collection}"


def get_collection(company_id: int, collection: str) -> chromadb.Collection:
    """Get-or-create the ChromaDB collection for the given company+collection."""
    name = collection_name(company_id, collection)
    return get_chroma_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def get_all_collections(company_id: int) -> list[chromadb.Collection]:
    """Return all 7 ChromaDB collections for a company."""
    return [get_collection(company_id, c) for c in COLLECTIONS]
