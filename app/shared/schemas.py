# app/shared/schemas.py
from pydantic import BaseModel
from typing import Generic, TypeVar, Literal

T = TypeVar('T')

class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    meta: dict | None = None

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool

class JobResponse(BaseModel):
    job_id: str
    status: Literal['queued', 'processing', 'completed', 'failed']
    progress: int
    result_url: str | None = None
    error: str | None = None
