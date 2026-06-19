"""
TurboVec-based vector store replacing ChromaDB.

One IdMapIndex per (company_id, collection) pair.
Persisted as:
  <TURBOVEC_PATH>/company_{id}_{collection}.tv   — TurboVec binary index
  <TURBOVEC_PATH>/company_{id}_{collection}.json — chunk text + metadata sidecar
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
from turbovec import IdMapIndex

logger = logging.getLogger(__name__)

_STORE_PATH = os.getenv("TURBOVEC_PATH", "./knowledge_base_tv")
_BIT_WIDTH = int(os.getenv("TURBOVEC_BIT_WIDTH", "4"))


class _CollectionIndex:
    """Vector index + chunk store for one (company_id, collection) pair."""

    def __init__(self, dim: int, index: IdMapIndex):
        self.dim = dim
        self._index = index
        self._chunks: dict[int, dict] = {}  # uint64_id → {content, metadata, doc_id}
        self._next_id: int = 0

    # ------------------------------------------------------------------ add

    def add(
        self,
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        doc_ids: list[str],
    ) -> list[int]:
        if not contents:
            return []
        vecs = np.array(embeddings, dtype=np.float32)
        uids = np.array(
            [self._next_id + i for i in range(len(contents))], dtype=np.uint64
        )
        self._next_id += len(contents)
        self._index.add_with_ids(vecs, uids)
        for uid, content, meta, doc_id in zip(
            uids.tolist(), contents, metadatas, doc_ids
        ):
            self._chunks[uid] = {"content": content, "metadata": meta, "doc_id": doc_id}
        return uids.tolist()

    # --------------------------------------------------------------- search

    def search(self, query_embedding: list[float], k: int) -> list[dict]:
        if not self._chunks:
            return []
        q = np.array([query_embedding], dtype=np.float32)
        actual_k = min(k, len(self._chunks))
        scores, ids = self._index.search(q, k=actual_k)
        results = []
        for score, uid in zip(scores[0].tolist(), ids[0].tolist()):
            chunk = self._chunks.get(int(uid))
            if chunk:
                results.append(
                    {
                        "content": chunk["content"],
                        "metadata": chunk["metadata"],
                        "score": float(score),
                        "source": "vector",
                    }
                )
        return results

    # --------------------------------------------------------------- remove

    def remove_by_doc_ids(self, doc_ids: set[str]) -> None:
        to_remove = [
            uid
            for uid, c in self._chunks.items()
            if c.get("doc_id") in doc_ids
        ]
        for uid in to_remove:
            try:
                self._index.remove(uid)
            except Exception as exc:
                logger.warning("[TurboVec] remove uid=%d failed: %s", uid, exc)
            del self._chunks[uid]

    # ----------------------------------------------------------- BM25 corpus

    def get_all(self) -> list[dict]:
        return [
            {"content": c["content"], "metadata": c["metadata"]}
            for c in self._chunks.values()
        ]

    def count(self) -> int:
        return len(self._chunks)

    # ----------------------------------------------------------- persistence

    def save(self, path_prefix: str) -> None:
        Path(path_prefix).parent.mkdir(parents=True, exist_ok=True)
        self._index.write(f"{path_prefix}.tv")
        sidecar = {
            "dim": self.dim,
            "next_id": self._next_id,
            "chunks": {str(k): v for k, v in self._chunks.items()},
        }
        with open(f"{path_prefix}.json", "w", encoding="utf-8") as fh:
            json.dump(sidecar, fh, ensure_ascii=False)

    @classmethod
    def load(cls, path_prefix: str) -> Optional["_CollectionIndex"]:
        tv_path = f"{path_prefix}.tv"
        json_path = f"{path_prefix}.json"
        if not (os.path.exists(tv_path) and os.path.exists(json_path)):
            return None
        try:
            with open(json_path, encoding="utf-8") as fh:
                sidecar = json.load(fh)
            dim = sidecar["dim"]
            index = IdMapIndex.load(tv_path)
            obj = cls(dim=dim, index=index)
            obj._next_id = sidecar["next_id"]
            obj._chunks = {int(k): v for k, v in sidecar["chunks"].items()}
            return obj
        except Exception as exc:
            logger.warning("[TurboVec] load failed for %s: %s", path_prefix, exc)
            return None


# ---------------------------------------------------------------------------
# Singleton store
# ---------------------------------------------------------------------------

class TurboVecStore:
    """Per-(company_id, collection) index registry."""

    def __init__(self, store_path: str = _STORE_PATH):
        self._store_path = store_path
        self._indexes: dict[tuple[int, str], _CollectionIndex] = {}

    def _path_prefix(self, company_id: int, collection: str) -> str:
        return os.path.join(self._store_path, f"company_{company_id}_{collection}")

    def get(self, company_id: int, collection: str, dim: int) -> _CollectionIndex:
        key = (company_id, collection)
        if key not in self._indexes:
            prefix = self._path_prefix(company_id, collection)
            loaded = _CollectionIndex.load(prefix)
            if loaded is not None:
                self._indexes[key] = loaded
                logger.info(
                    "[TurboVec] Loaded index company_%d_%s (%d chunks)",
                    company_id, collection, loaded.count(),
                )
            else:
                self._indexes[key] = _CollectionIndex(
                    dim=dim, index=IdMapIndex(dim=dim, bit_width=_BIT_WIDTH)
                )
                logger.info(
                    "[TurboVec] Created index company_%d_%s dim=%d",
                    company_id, collection, dim,
                )
        return self._indexes[key]

    def add_chunks(
        self,
        company_id: int,
        collection: str,
        contents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        doc_ids: list[str],
    ) -> list[int]:
        dim = len(embeddings[0])
        col = self.get(company_id, collection, dim=dim)
        uids = col.add(contents, embeddings, metadatas, doc_ids)
        col.save(self._path_prefix(company_id, collection))
        return uids

    def search(
        self,
        company_id: int,
        collection: str,
        query_embedding: list[float],
        k: int = 20,
    ) -> list[dict]:
        dim = len(query_embedding)
        col = self.get(company_id, collection, dim=dim)
        return col.search(query_embedding, k=k)

    def remove_by_doc_ids(
        self,
        company_id: int,
        collection: str,
        doc_ids: list[str],
    ) -> None:
        key = (company_id, collection)
        if key not in self._indexes:
            # Try loading so we can remove from a persisted index
            prefix = self._path_prefix(company_id, collection)
            loaded = _CollectionIndex.load(prefix)
            if loaded is None:
                return
            self._indexes[key] = loaded
        col = self._indexes[key]
        col.remove_by_doc_ids(set(doc_ids))
        col.save(self._path_prefix(company_id, collection))

    def get_all_chunks(
        self, company_id: int, collection: str
    ) -> list[dict]:
        """Return all chunks for BM25 corpus. Returns [] if index not loaded yet."""
        key = (company_id, collection)
        col = self._indexes.get(key)
        if col is None:
            prefix = self._path_prefix(company_id, collection)
            loaded = _CollectionIndex.load(prefix)
            if loaded is None:
                return []
            self._indexes[key] = loaded
            col = loaded
        return col.get_all()

    def count(self, company_id: int, collection: str) -> int:
        key = (company_id, collection)
        col = self._indexes.get(key)
        if col is None:
            prefix = self._path_prefix(company_id, collection)
            loaded = _CollectionIndex.load(prefix)
            if loaded is None:
                return 0
            self._indexes[key] = loaded
            col = loaded
        return col.count()


# Module-level singleton
_store: TurboVecStore | None = None


def get_store() -> TurboVecStore:
    global _store
    if _store is None:
        _store = TurboVecStore()
    return _store
