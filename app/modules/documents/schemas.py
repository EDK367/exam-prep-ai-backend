"""
Pydantic schemas for the documents module.
Used for request validation and response serialization.
"""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DocumentStatus


# ── Request Schemas ──────────────────────────────────────────────────────────

class DocumentUploadMeta(BaseModel):
    """Optional metadata the client can send with an upload."""
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


# ── Response Schemas ─────────────────────────────────────────────────────────

class DocumentChunkResponse(BaseModel):
    id: UUID
    chunk_index: int
    content: str
    metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    storage_path: Optional[str] = None
    size_types: Optional[int] = None
    status: DocumentStatus
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentDetailResponse(DocumentResponse):
    chunks: list[DocumentChunkResponse] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


class DocumentProcessingStatus(BaseModel):
    """Real-time processing status for polling."""
    document_id: UUID
    status: DocumentStatus
    progress_percent: int = 0
    current_step: str = ""
    error_message: Optional[str] = None
    chunk_count: Optional[int] = None
    celery_task_id: Optional[str] = None
