"""
app/routers/knowledge.py — API endpoints for operational runbook ingestion and vector retrieval.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.

Tenancy & Authorization Note
----------------------------
TraceMind AI currently operates in a single-tenant deployment model protected by a shared API key
(``TRACEMIND_API_KEY``). Multi-tenant organization or workspace isolation is not implemented.
Runbooks may optionally specify a ``service_name`` to restrict retrieval to relevant components,
but all authenticated callers access the same service instance knowledge base.
"""

import logging
import os
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeIngestRequest,
    KnowledgeSearchRequest,
    RetrievedChunkResponse,
)
from app.services.knowledge import MAX_DOCUMENT_BYTES, ingest_document
from app.services.retrieval import search_relevant_chunks

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Knowledge & Runbooks"])

SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".markdown"}


@router.post(
    "/runbooks",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest operational runbook (JSON payload)",
)
def ingest_runbook_json(
    payload: KnowledgeIngestRequest,
    db: Session = Depends(get_db),
) -> KnowledgeDocumentResponse:
    """
    Ingest, chunk, embed, and index an operational runbook or SOP from text.
    Idempotent: Identical content is deduplicated by content hash.
    """
    try:
        doc, is_duplicate = ingest_document(
            session=db,
            title=payload.title,
            content=payload.content,
            source=payload.source,
            service_name=payload.service_name,
            environment=payload.environment,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    resp = KnowledgeDocumentResponse.model_validate(doc)
    resp.is_duplicate = is_duplicate
    return resp


@router.post(
    "/runbooks/upload",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload operational runbook file (.md, .txt, .json)",
)
async def upload_runbook_file(
    file: UploadFile = File(..., description="Markdown or text runbook file (max 1 MB)."),
    title: Optional[str] = Form(None, description="Optional document title; defaults to filename."),
    service_name: Optional[str] = Form(None, description="Optional service scope."),
    environment: Optional[str] = Form(None, description="Optional environment scope."),
    db: Session = Depends(get_db),
) -> KnowledgeDocumentResponse:
    """
    Upload and index a runbook document file (.md, .txt, .json).
    """
    filename = file.filename or "uploaded_runbook.md"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{ext}'. Supported extensions: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file exceeds maximum limit of {MAX_DOCUMENT_BYTES} bytes (1 MB).",
        )

    try:
        content = file_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content could not be decoded as UTF-8 text.",
        ) from exc

    doc_title = title.strip() if title and title.strip() else filename

    try:
        doc, is_duplicate = ingest_document(
            session=db,
            title=doc_title,
            content=content,
            source=f"file:{filename}",
            service_name=service_name.strip() if service_name else None,
            environment=environment.strip() if environment else None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    resp = KnowledgeDocumentResponse.model_validate(doc)
    resp.is_duplicate = is_duplicate
    return resp


@router.get(
    "/runbooks",
    response_model=List[KnowledgeDocumentResponse],
    summary="List ingested runbook documents",
)
def list_runbooks(
    limit: int = Query(default=50, ge=1, le=100, description="Max documents to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    service_name: Optional[str] = Query(default=None, description="Filter by service"),
    db: Session = Depends(get_db),
) -> List[KnowledgeDocumentResponse]:
    """
    Retrieve metadata for ingested operational runbooks.
    """
    stmt = select(KnowledgeDocument)
    if service_name:
        stmt = stmt.where(KnowledgeDocument.service_name == service_name)
    stmt = stmt.order_by(desc(KnowledgeDocument.created_at)).limit(limit).offset(offset)

    docs = db.execute(stmt).scalars().all()
    return [KnowledgeDocumentResponse.model_validate(d) for d in docs]


@router.get(
    "/runbooks/{document_id}",
    response_model=KnowledgeDocumentResponse,
    summary="Get runbook metadata by UUID",
)
def get_runbook(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> KnowledgeDocumentResponse:
    """
    Retrieve document metadata for a specific runbook UUID.
    """
    doc = db.get(KnowledgeDocument, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Runbook document with id={document_id} not found.",
        )
    return KnowledgeDocumentResponse.model_validate(doc)


@router.post(
    "/knowledge/search",
    response_model=List[RetrievedChunkResponse],
    summary="Search runbook passages via vector similarity",
)
def search_knowledge(
    payload: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
) -> List[RetrievedChunkResponse]:
    """
    Retrieve the top-k relevant runbook passages matching a technical error query.
    """
    chunks = search_relevant_chunks(
        session=db,
        query=payload.query,
        top_k=payload.top_k,
        min_similarity=payload.min_similarity,
        service_name=payload.service_name,
    )

    return [
        RetrievedChunkResponse(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            document_title=c.document_title,
            source=c.source,
            service_name=c.service_name,
            similarity_score=c.similarity_score,
            content=c.content,
        )
        for c in chunks
    ]
