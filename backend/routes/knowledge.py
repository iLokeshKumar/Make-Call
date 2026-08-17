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
  POST   /crm/knowledge/upload                     upload file → convert → index
  POST   /crm/knowledge/upload-url                 convert URL/YouTube → index
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crm", tags=["Knowledge"])

# ---------------------------------------------------------------------------
# Supported file extensions for the upload endpoint
# ---------------------------------------------------------------------------
_SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".csv",
    ".html", ".htm", ".xml", ".json",
    ".txt", ".md", ".rst",
    ".epub",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff",
    ".mp3", ".wav", ".ogg", ".m4a",
    ".zip",
    ".msg",        # Outlook messages
    ".ipynb",      # Jupyter notebooks
}


def _build_markitdown():
    """Build a MarkItDown instance, optionally with Azure Document Intelligence."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="markitdown not installed. Run: pip install 'markitdown[all]'",
        )

    docintel_client = None
    docintel_endpoint = os.getenv("AZURE_DOCINTEL_ENDPOINT") or os.getenv("AZURE_SPEECH_ENDPOINT")
    docintel_key = os.getenv("AZURE_DOCINTEL_API_KEY") or os.getenv("AZURE_SPEECH_API_KEY")

    if docintel_endpoint and docintel_key:
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.core.credentials import AzureKeyCredential
            docintel_client = DocumentIntelligenceClient(
                endpoint=docintel_endpoint,
                credential=AzureKeyCredential(docintel_key),
            )
            logger.info("[MarkItDown] Azure Document Intelligence enabled")
        except Exception as exc:
            logger.warning("[MarkItDown] Azure Doc Intelligence unavailable: %s", exc)

    return MarkItDown(docintel_client=docintel_client)


async def _convert_file(md, path: str) -> str:
    """Run MarkItDown conversion in a thread (it's sync + potentially slow)."""
    result = await asyncio.to_thread(md.convert, path)
    return (result.text_content or "").strip()


async def _convert_url(md, url: str) -> str:
    result = await asyncio.to_thread(md.convert, url)
    return (result.text_content or "").strip()


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



@router.post("/knowledge/upload", status_code=201)
async def upload_knowledge_file(
    file: UploadFile = File(...),
    collection: str = Form("products"),
    title: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),          # comma-separated
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Upload a file (PDF/Word/Excel/PPTX/image/audio/etc.) → convert to Markdown → index in KB.

    Supports: PDF, DOCX, PPTX, XLSX, CSV, HTML, XML, JSON, TXT, MD,
              EPUB, JPG/PNG/GIF, MP3/WAV, ZIP, MSG, IPYNB and more.
    """
    if collection not in COLLECTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid collection '{collection}'. Valid: {COLLECTIONS}",
        )

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext and ext not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Supported: {sorted(_SUPPORTED_EXTENSIONS)}",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    md = _build_markitdown()

    suffix = ext or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        content = await _convert_file(md, tmp_path)
    except Exception as exc:
        logger.error("[MarkItDown] Conversion failed for %s: %s", file.filename, exc)
        raise HTTPException(status_code=422, detail=f"Conversion failed: {exc}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not content:
        raise HTTPException(status_code=422, detail="Conversion produced empty content. Check the file.")

    doc_title = title or file.filename or "Untitled"
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    doc = create_document(
        session=session,
        company_id=current_user.company_id,
        collection=collection,
        title=doc_title,
        content=content,
        actor_user_id=current_user.id,
        tags=tag_list or None,
        metadata_json={
            "source": "file_upload",
            "original_filename": file.filename,
            "file_extension": ext,
            "content_type": file.content_type or "unknown",
            "size_bytes": len(raw),
        },
    )
    return {
        "id": doc.id,
        "title": doc_title,
        "collection": collection,
        "chars": len(content),
        "original_filename": file.filename,
    }


@router.post("/knowledge/upload-url", status_code=201)
async def upload_knowledge_url(
    url: str = Form(...),
    collection: str = Form("products"),
    title: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Convert a URL (web page, YouTube video, RSS feed) to Markdown and index in KB.

    YouTube URLs are transcribed. Web pages are scraped and converted.
    """
    if collection not in COLLECTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid collection '{collection}'. Valid: {COLLECTIONS}",
        )
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    md = _build_markitdown()

    try:
        content = await _convert_url(md, url)
    except Exception as exc:
        logger.error("[MarkItDown] URL conversion failed for %s: %s", url, exc)
        raise HTTPException(status_code=422, detail=f"URL conversion failed: {exc}")

    if not content:
        raise HTTPException(status_code=422, detail="URL produced empty content.")

    doc_title = title or url[:120]
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    doc = create_document(
        session=session,
        company_id=current_user.company_id,
        collection=collection,
        title=doc_title,
        content=content,
        actor_user_id=current_user.id,
        tags=tag_list or None,
        metadata_json={
            "source": "url",
            "url": url,
        },
    )
    return {
        "id": doc.id,
        "title": doc_title,
        "collection": collection,
        "chars": len(content),
        "url": url,
    }


@router.post("/knowledge/upload-batch", status_code=201)
async def upload_knowledge_batch(
    files: List[UploadFile] = File(...),
    collection: str = Form("products"),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Upload multiple files at once. Each is converted and indexed independently."""
    if collection not in COLLECTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid collection '{collection}'.")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Max 20 files per batch.")

    md = _build_markitdown()
    results = []

    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower()
        raw = await file.read()
        if not raw:
            results.append({"filename": file.filename, "status": "skipped", "reason": "empty"})
            continue

        suffix = ext or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        try:
            content = await _convert_file(md, tmp_path)
        except Exception as exc:
            results.append({"filename": file.filename, "status": "error", "reason": str(exc)})
            continue
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if not content:
            results.append({"filename": file.filename, "status": "skipped", "reason": "empty output"})
            continue

        try:
            doc = create_document(
                session=session,
                company_id=current_user.company_id,
                collection=collection,
                title=file.filename or "Untitled",
                content=content,
                actor_user_id=current_user.id,
                metadata_json={
                    "source": "file_upload",
                    "original_filename": file.filename,
                    "file_extension": ext,
                    "size_bytes": len(raw),
                },
            )
            results.append({
                "filename": file.filename,
                "status": "ok",
                "doc_id": doc.id,
                "chars": len(content),
            })
        except Exception as exc:
            results.append({"filename": file.filename, "status": "error", "reason": str(exc)})

    ok = sum(1 for r in results if r["status"] == "ok")
    return {"total": len(files), "indexed": ok, "results": results}


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
