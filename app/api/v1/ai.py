"""
AI content generation API endpoints.
Generates exams, flashcards, summaries, and explanations.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.modules.ai.content_service import content_generation_service
from app.modules.billing.subscription_service import subscription_service
from app.modules.documents.repository import chunk_repo
from app.modules.documents.service import document_service
from app.modules.shared.bitacora_service import bitacora_service
from app.modules.users.models import User

router = APIRouter()


class GenerateFromTextRequest(BaseModel):
    text: str = Field(..., min_length=50, max_length=100000)
    question_count: int = Field(default=10, ge=1, le=50)
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")


class GenerateFromDocumentRequest(BaseModel):
    document_id: UUID
    question_count: int = Field(default=10, ge=1, le=50)
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")


class FlashcardRequest(BaseModel):
    document_id: UUID
    count: int = Field(default=15, ge=1, le=50)


class SummaryRequest(BaseModel):
    document_id: UUID


class ExplanationRequest(BaseModel):
    question: str = Field(..., min_length=10)
    context: str = Field(..., min_length=20)


@router.post("/generate-exam")
async def generate_exam_from_text(
    request: GenerateFromTextRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an exam from raw text input."""
    limits = await subscription_service.get_user_limits(db, current_user.id)

    result = await content_generation_service.generate_exam(
        db,
        current_user.id,
        request.text,
        question_count=request.question_count,
        difficulty=request.difficulty,
        model=limits["model"],
        max_tokens_budget=limits["max_tokens"],
    )
    return {"success": True, "data": result}


@router.post("/generate-exam-from-document")
async def generate_exam_from_document(
    request: GenerateFromDocumentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an exam from a processed document's chunks."""
    limits = await subscription_service.get_user_limits(db, current_user.id)

    # Get document chunks
    await document_service.get_document(db, request.document_id, current_user.id)
    chunks = await chunk_repo.get_by_document(db, request.document_id)
    chunk_texts = [c.content for c in chunks]

    if not chunk_texts:
        return {"success": False, "error": "Document has no processed chunks"}

    result = await content_generation_service.generate_exam_from_chunks(
        db,
        current_user.id,
        chunk_texts,
        question_count=request.question_count,
        difficulty=request.difficulty,
        model=limits["model"],
        max_tokens_budget=limits["max_tokens"],
    )
    return {"success": True, "data": result}


@router.post("/generate-flashcards")
async def generate_flashcards(
    request: FlashcardRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate flashcards from a processed document."""
    limits = await subscription_service.get_user_limits(db, current_user.id)

    await document_service.get_document(db, request.document_id, current_user.id)
    chunks = await chunk_repo.get_by_document(db, request.document_id)
    full_text = "\n\n".join(c.content for c in chunks)

    if not full_text.strip():
        return {"success": False, "error": "Document has no processed content"}

    result = await content_generation_service.generate_flashcards(
        db, current_user.id, full_text, count=request.count, model=limits["model"]
    )
    return {"success": True, "data": result}


@router.post("/generate-summary")
async def generate_summary(
    request: SummaryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a structured summary from a processed document."""
    limits = await subscription_service.get_user_limits(db, current_user.id)

    await document_service.get_document(db, request.document_id, current_user.id)
    chunks = await chunk_repo.get_by_document(db, request.document_id)
    full_text = "\n\n".join(c.content for c in chunks)

    if not full_text.strip():
        return {"success": False, "error": "Document has no processed content"}

    result = await content_generation_service.generate_summary(
        db, current_user.id, full_text, model=limits["model"]
    )
    return {"success": True, "data": result}


@router.post("/explain")
async def generate_explanation(
    request: ExplanationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a detailed explanation for a question."""
    limits = await subscription_service.get_user_limits(db, current_user.id)

    result = await content_generation_service.generate_explanation(
        db,
        current_user.id,
        request.question,
        request.context,
        model=limits["model"],
    )
    return {"success": True, "data": result}


@router.get("/usage")
async def get_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's AI usage statistics."""
    limits = await subscription_service.get_user_limits(db, current_user.id)
    usage = await bitacora_service.get_monthly_usage(db, current_user.id)
    return {
        "success": True,
        "data": {
            **usage,
            "max_tokens": limits["max_tokens"],
            "remaining_tokens": max(0, limits["max_tokens"] - usage["total_tokens"]),
            "plan": limits["plan_name"],
            "model": limits["model"],
        },
    }
