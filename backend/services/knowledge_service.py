"""
Knowledge Base service — CRUD for KnowledgeDocument + ChromaDB synchronisation.

Every write operation (create / update / delete) is immediately reflected in
ChromaDB so agents always search fresh data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from models.models import KnowledgeDocument, utc_now
from services.rag.ingestion import delete_document as chroma_delete, index_document as chroma_index

logger = logging.getLogger(__name__)


def _sync_to_chroma(doc: KnowledgeDocument) -> list[str]:
    """Index (or re-index) a KnowledgeDocument into ChromaDB. Returns doc IDs."""
    try:
        ids = chroma_index(
            company_id=doc.company_id,
            collection=doc.collection,
            title=doc.title,
            content=doc.content,
            tags=doc.tags or [],
            extra_metadata=doc.metadata_json or {},
        )
        return ids
    except Exception as exc:
        logger.error("[KB] ChromaDB sync failed for doc %s: %s", doc.id, exc)
        return []


def _remove_from_chroma(doc: KnowledgeDocument) -> None:
    """Remove all ChromaDB chunks for a document."""
    try:
        chroma_delete(
            company_id=doc.company_id,
            collection=doc.collection,
            title=doc.title,
        )
    except Exception as exc:
        logger.warning("[KB] ChromaDB delete failed for doc %s: %s", doc.id, exc)



def create_document(
    session: Session,
    company_id: int,
    collection: str,
    title: str,
    content: str,
    actor_user_id: int,
    tags: Optional[list] = None,
    metadata_json: Optional[dict] = None,
) -> KnowledgeDocument:
    """Create a KnowledgeDocument in the DB and index it into ChromaDB."""
    doc = KnowledgeDocument(
        company_id=company_id,
        collection=collection,
        title=title,
        content=content,
        tags=tags,
        metadata_json=metadata_json,
        is_active=True,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(doc)
    session.flush()  # get doc.id without full commit

    ids = _sync_to_chroma(doc)
    doc.chroma_doc_id = ids[0] if ids else None
    doc.last_indexed_at = utc_now()
    session.add(doc)
    session.commit()
    session.refresh(doc)

    logger.info("[KB] Created doc %d '%s' in %s (company %d)", doc.id, title, collection, company_id)
    return doc


def update_document(
    session: Session,
    doc_id: int,
    actor_user_id: int,
    content: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[list] = None,
    metadata_json: Optional[dict] = None,
    is_active: Optional[bool] = None,
) -> KnowledgeDocument:
    """Update a KnowledgeDocument and re-index in ChromaDB."""
    doc = session.get(KnowledgeDocument, doc_id)
    if not doc:
        raise ValueError(f"KnowledgeDocument {doc_id} not found")

    # Remove old chunks before re-indexing (title may have changed)
    _remove_from_chroma(doc)

    if title is not None:
        doc.title = title
    if content is not None:
        doc.content = content
    if tags is not None:
        doc.tags = tags
    if metadata_json is not None:
        doc.metadata_json = metadata_json
    if is_active is not None:
        doc.is_active = is_active

    doc.updated_at = utc_now()
    doc.updated_by = actor_user_id
    session.add(doc)
    session.flush()

    if doc.is_active:
        ids = _sync_to_chroma(doc)
        doc.chroma_doc_id = ids[0] if ids else None
        doc.last_indexed_at = utc_now()
        session.add(doc)

    session.commit()
    session.refresh(doc)
    logger.info("[KB] Updated doc %d '%s'", doc.id, doc.title)
    return doc


def delete_document(
    session: Session,
    doc_id: int,
    actor_user_id: int,
) -> None:
    """Soft-delete a KnowledgeDocument and remove it from ChromaDB."""
    doc = session.get(KnowledgeDocument, doc_id)
    if not doc:
        raise ValueError(f"KnowledgeDocument {doc_id} not found")

    _remove_from_chroma(doc)

    doc.is_active = False
    doc.updated_at = utc_now()
    doc.updated_by = actor_user_id
    session.add(doc)
    session.commit()
    logger.info("[KB] Soft-deleted doc %d '%s'", doc.id, doc.title)


def get_document(session: Session, doc_id: int) -> Optional[KnowledgeDocument]:
    return session.get(KnowledgeDocument, doc_id)


def list_documents(
    session: Session,
    company_id: int,
    collection: Optional[str] = None,
    active_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[KnowledgeDocument]:
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.company_id == company_id)
    if collection:
        stmt = stmt.where(KnowledgeDocument.collection == collection)
    if active_only:
        stmt = stmt.where(KnowledgeDocument.is_active == True)
    stmt = stmt.order_by(KnowledgeDocument.updated_at.desc()).offset(offset).limit(limit)
    return list(session.exec(stmt).all())


def reindex_all(session: Session, company_id: int) -> int:
    """Re-index every active document for a company. Returns count re-indexed."""
    docs = list_documents(session, company_id, active_only=True, limit=10_000)
    count = 0
    for doc in docs:
        ids = _sync_to_chroma(doc)
        if ids:
            doc.chroma_doc_id = ids[0]
            doc.last_indexed_at = utc_now()
            session.add(doc)
            count += 1
    session.commit()
    logger.info("[KB] Re-indexed %d documents for company %d", count, company_id)
    return count
