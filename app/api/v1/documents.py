"""
Document API endpoints.
Handles upload, listing, processing, status, and deletion.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.enums import DocumentStatus
from app.modules.billing.subscription_service import subscription_service
from app.modules.documents.schemas import (
    DocumentResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentProcessingStatus,
)
from app.modules.documents.service import document_service
from app.modules.users.models import User
from app.shared.rate_limiter import limiter
from app.workers.tasks.document_tasks import process_document

router = APIRouter()


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF document. Validates file type, size, and plan limits."""
    # Get plan limits
    limits = await subscription_service.get_user_limits(db, current_user.id)

    # Read file
    file_bytes = await file.read()

    # Upload and validate
    document = await document_service.upload_document(
        db,
        user_id=current_user.id,
        file_bytes=file_bytes,
        filename=file.filename,
        content_type=file.content_type or "application/pdf",
        max_uploads=limits["max_uploads"],
    )

    # Dispatch background processing
    task = process_document.delay(str(document.id))

    # Save task ID
    from app.modules.documents.repository import document_repo
    await document_repo.update(db, document, {"celery_task_id": task.id})

    return document


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List uploaded documents for the current user."""
    doc_status = DocumentStatus(status) if status else None
    result = await document_service.list_documents(
        db, current_user.id, status=doc_status, page=page, page_size=page_size
    )
    return result


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single document's details."""
    return await document_service.get_document(db, document_id, current_user.id)


@router.get("/{document_id}/detail", response_model=DocumentDetailResponse)
async def get_document_detail(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a document with all its chunks."""
    return await document_service.get_document_with_chunks(
        db, document_id, current_user.id
    )


@router.get("/{document_id}/status", response_model=DocumentProcessingStatus)
async def get_processing_status(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll the processing status of a document."""
    return await document_service.get_processing_status(
        db, document_id, current_user.id
    )


@router.post("/{document_id}/reprocess", response_model=DocumentResponse)
async def reprocess_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reprocess a failed or completed document."""
    doc = await document_service.reprocess_document(
        db, document_id, current_user.id
    )

    # Dispatch background processing again
    task = process_document.delay(str(document_id))
    from app.modules.documents.repository import document_repo
    await document_repo.update(db, doc, {"celery_task_id": task.id})

    return doc


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and its storage file."""
    await document_service.delete_document(db, document_id, current_user.id)
