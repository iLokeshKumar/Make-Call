"""
Knowledge Base API — CRUD for documents + semantic search endpoint.

All operations are company-scoped (RLS + explicit company_id check).

Endpoints:
  GET    /crm/knowledge/documents                  list documents
  POST   /crm/knowledge/documents                  create + index
  GET    /crm/knowledge/documents/{id}             get single document
  PUT    /crm/knowledge/documents/{id}             update + re-index
  DELETE /crm/knowledge/documents/{id}             soft-delete + remove from chroma
  GET    /crm/knowledge/search?q=...&collection=.. semantic search
  POST   /crm/knowledge/reindex                    re-index all documents for company
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, SQLModel

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import KnowledgeDocument, User
from services.knowledge_service import (
    create_document,
    delete_document,
    get_document,
    list_documents,
    reindex_all,
    update_document,
)
from services.rag.collections import COLLECTIONS
from services.rag.query_engine import format_for_prompt, search

router = APIRouter(prefix="/crm", tags=["Knowledge"])


# Pydantic request/response schemas

class DocumentCreate(SQLModel):
    collection: str
    title: str
    content: str
    tags: Optional[list] = None
    metadata_json: Optional[dict] = None


class DocumentUpdate(SQLModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list] = None
    metadata_json: Optional[dict] = None
    is_active: Optional[bool] = None


class DocumentOut(SQLModel):
    id: int
    company_id: int
    collection: str
    title: str
    content: str
    tags: Optional[list] = None
    metadata_json: Optional[dict] = None
    chroma_doc_id: Optional[str] = None
    is_active: bool
    last_indexed_at: Optional[str] = None

    @classmethod
    def from_orm(cls, doc: KnowledgeDocument) -> "DocumentOut":
        return cls(
            id=doc.id,
            company_id=doc.company_id,
            collection=doc.collection,
            title=doc.title,
            content=doc.content,
            tags=doc.tags,
            metadata_json=doc.metadata_json,
            chroma_doc_id=doc.chroma_doc_id,
            is_active=doc.is_active,
            last_indexed_at=doc.last_indexed_at.isoformat() if doc.last_indexed_at else None,
        )



@router.get("/knowledge/documents")
async def list_knowledge_documents(
    collection: Optional[str] = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    docs = list_documents(
        session,
        company_id=current_user.company_id,
        collection=collection,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return [DocumentOut.from_orm(d) for d in docs]



@router.get("/knowledge/documents/{doc_id}")
async def get_knowledge_document(
    doc_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    doc = get_document(session, doc_id)
    if not doc or doc.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentOut.from_orm(doc)



@router.post("/knowledge/documents", status_code=201)
async def create_knowledge_document(
    payload: DocumentCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    if payload.collection not in COLLECTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid collection '{payload.collection}'. Valid: {COLLECTIONS}",
        )
    doc = create_document(
        session=session,
        company_id=current_user.company_id,
        collection=payload.collection,
        title=payload.title,
        content=payload.content,
        actor_user_id=current_user.id,
        tags=payload.tags,
        metadata_json=payload.metadata_json,
    )
    return DocumentOut.from_orm(doc)


@router.put("/knowledge/documents/{doc_id}")
async def update_knowledge_document(
    doc_id: int,
    payload: DocumentUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    existing = get_document(session, doc_id)
    if not existing or existing.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = update_document(
        session=session,
        doc_id=doc_id,
        actor_user_id=current_user.id,
        content=payload.content,
        title=payload.title,
        tags=payload.tags,
        metadata_json=payload.metadata_json,
        is_active=payload.is_active,
    )
    return DocumentOut.from_orm(doc)




@router.delete("/knowledge/documents/{doc_id}", status_code=204)
async def delete_knowledge_document(
    doc_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    existing = get_document(session, doc_id)
    if not existing or existing.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Document not found")

    delete_document(session=session, doc_id=doc_id, actor_user_id=current_user.id)


# Semantic search

@router.get("/knowledge/search")
async def search_knowledge(
    q: str = Query(..., min_length=1),
    collection: str = Query("all"),
    n: int = Query(5, ge=1, le=20),
    as_text: bool = Query(False, description="Return results formatted as a single prompt-ready string"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    results = search(
        query=q,
        company_id=current_user.company_id,
        collection=collection,
        n_results=n,
    )
    if as_text:
        return {"query": q, "text": format_for_prompt(results)}
    return {
        "query": q,
        "collection": collection,
        "count": len(results),
        "results": results,
    }


# Re-index

@router.post("/knowledge/reindex")
async def reindex_knowledge(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    count = reindex_all(session, company_id=current_user.company_id)
    return {"reindexed": count}


# Collections catalogue (read-only metadata)

@router.get("/knowledge/collections")
async def list_collections(
    current_user: User = Depends(get_current_user),
):
    return {"collections": COLLECTIONS}
