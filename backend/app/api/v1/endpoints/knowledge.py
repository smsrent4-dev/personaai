import uuid

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_current_active_user
from app.core.ssrf_guard import UnsafeURLError, fetch_url_safely
from app.database import get_db
from app.models.knowledge import KnowledgeSourceType
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResult,
    KnowledgeTextCreate,
    KnowledgeUrlCreate,
)
from app.services.knowledge import KnowledgeService
from app.services.knowledge.extractors import infer_source_type_from_filename

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])

_ALLOWED_UPLOAD_EXTENSIONS = (".pdf", ".docx", ".txt", ".md", ".markdown")


@router.get("/documents", response_model=list[KnowledgeDocumentResponse])
async def list_documents(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await KnowledgeService(db).list_documents(current_user.id)


@router.get("/documents/{document_id}", response_model=KnowledgeDocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await KnowledgeService(db).get_document(current_user.id, document_id)


@router.post("/documents/upload", response_model=KnowledgeDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    agent_id: uuid.UUID | None = Form(default=None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    raw = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit",
        )

    filename = file.filename or ""
    if not filename.lower().endswith(_ALLOWED_UPLOAD_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(_ALLOWED_UPLOAD_EXTENSIONS)}",
        )

    source_type = infer_source_type_from_filename(filename or "upload.txt")
    service = KnowledgeService(db)
    document = await service.create_from_upload(
        owner=current_user,
        title=title or (file.filename or "Untitled document"),
        filename=file.filename or "upload",
        source_type=source_type,
        raw_content=raw,
        agent_id=agent_id,
    )
    # Ingest inline for now (see service docstring re: Celery). Small/medium
    # documents finish well within a normal request timeout.
    return await service.ingest_document(document)


@router.post("/documents/text", response_model=KnowledgeDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_text_document(
    data: KnowledgeTextCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeService(db)
    document = await service.create_from_text(
        owner=current_user,
        title=data.title,
        content=data.content,
        source_type=data.source_type,
        agent_id=data.agent_id,
    )
    return await service.ingest_document(document)


@router.post("/documents/url", response_model=KnowledgeDocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_url_document(
    data: KnowledgeUrlCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        resp = await fetch_url_safely(str(data.url))
    except UnsafeURLError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not fetch URL: {exc}"
        ) from exc

    service = KnowledgeService(db)
    document = await service.create_from_url(
        owner=current_user,
        url=str(data.url),
        title=data.title,
        html=resp.text,
        agent_id=data.agent_id,
    )
    return await service.ingest_document(document)


@router.post("/documents/{document_id}/reprocess", response_model=KnowledgeDocumentResponse)
async def reprocess_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-runs ingestion — useful after a FAILED status, or after changing
    the embedding model/provider."""
    service = KnowledgeService(db)
    document = await service.get_document(current_user.id, document_id)
    return await service.ingest_document(document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await KnowledgeService(db).delete_document(current_user.id, document_id)


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    data: KnowledgeSearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = KnowledgeService(db)
    results = await service.search(current_user.id, data.query, agent_id=data.agent_id, top_k=data.top_k)
    return KnowledgeSearchResponse(
        results=[
            KnowledgeSearchResult(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=chunk.document.title,
                content=chunk.content,
                score=score,
            )
            for chunk, score in results
        ]
    )
