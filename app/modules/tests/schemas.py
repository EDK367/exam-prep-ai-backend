"""
Pydantic schemas for tests, questions, and user responses.
"""
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import TestStatus, QuestionType


# ── Request Schemas ──────────────────────────────────────────────────────────

class CreateTestRequest(BaseModel):
    document_id: UUID
    title: Optional[str] = None
    question_count: int = Field(default=10, ge=1, le=50)
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    template_id: Optional[UUID] = None
    include_flashcards: bool = False
    include_summary: bool = False
    
    # Hard mode configs
    hard_mode: bool = False
    concept_mode: bool = False
    multiple_answers: bool = False
    no_go_back: bool = False


class SubmitAnswerRequest(BaseModel):
    question_id: UUID
    response_text: Any  # Can be a string, option index, or boolean


class SubmitTestRequest(BaseModel):
    answers: list[SubmitAnswerRequest]


# ── Response Schemas ─────────────────────────────────────────────────────────

class QuestionResponse(BaseModel):
    id: UUID
    questions_type: Optional[str] = None
    points: float = 1.0
    content: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuestionWithAnswerResponse(QuestionResponse):
    """Question with correct answer revealed (for review)."""
    user_answer: Optional[Any] = None
    is_correct: Optional[bool] = None
    explanation: Optional[str] = None


class UserResponseResponse(BaseModel):
    id: UUID
    question_id: UUID
    response_text: Any
    is_correct: Optional[bool] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestResponse(BaseModel):
    id: UUID
    title: str
    status: str
    is_active: bool
    user_id: UUID
    test_template_id: Optional[UUID] = None
    question_count: Optional[int] = None
    config: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestDetailResponse(TestResponse):
    questions: list[QuestionResponse] = Field(default_factory=list)


class TestResultResponse(BaseModel):
    test_id: UUID
    title: str
    total_questions: int
    correct_answers: int
    incorrect_answers: int
    unanswered: int
    score_percent: float
    passed: bool
    passing_score: float
    questions: list[QuestionWithAnswerResponse] = Field(default_factory=list)


class TestListResponse(BaseModel):
    items: list[TestResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
