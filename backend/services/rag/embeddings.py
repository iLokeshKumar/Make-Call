"""
Pluggable embedding providers.

Default: local SentenceTransformer (no API cost, model already bundled with
sentence-transformers). Override via EMBED_MODEL and EMBED_PROVIDER env vars.

EMBED_PROVIDER options: local (default), openai, google
EMBED_MODEL     options: any model name valid for the chosen provider
                default: all-MiniLM-L6-v2 (fast, already cached from existing usage)
                upgrade:  BAAI/bge-large-en-v1.5 (1024-dim, better accuracy)
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer as _ST

logger = logging.getLogger(__name__)

_EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "local").lower()
_EMBED_MODEL = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")

_local_model: "_ST | None" = None


def _get_local_model() -> "_ST":
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("[RAG] Loading local embedding model: %s", _EMBED_MODEL)
        _local_model = SentenceTransformer(_EMBED_MODEL)
    return _local_model


def embed(text: str) -> list[float]:
    """Embed a single string. Returns a list[float] vector."""
    return embed_batch([text])[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings. Returns a parallel list of vectors."""
    if not texts:
        return []

    provider = _EMBED_PROVIDER

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        model = os.getenv("EMBED_MODEL", "text-embedding-3-small")
        embedder = OpenAIEmbeddings(model=model)
        return embedder.embed_documents(texts)

    if provider == "google":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        model = os.getenv("EMBED_MODEL", "models/embedding-001")
        embedder = GoogleGenerativeAIEmbeddings(model=model)
        return embedder.embed_documents(texts)

    # Default: local SentenceTransformer
    model = _get_local_model()
    return model.encode(texts, show_progress_bar=False).tolist()
