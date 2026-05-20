"""
Test & Quiz API endpoints.
Handles test creation, listing, taking, submission, and results.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.enums import TestStatus
from app.modules.billing.subscription_service import subscription_service
from app.modules.tests.schemas import (
    CreateTestRequest,
    SubmitTestRequest,
    TestResponse,
    TestDetailResponse,
    TestListResponse,
    TestResultResponse,
)
from app.modules.tests.service import test_service
from app.modules.users.models import User

router = APIRouter()


@router.post("/", response_model=TestResponse, status_code=201)
async def create_test(
    request: CreateTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new test from a processed document.
    Generates questions via AI and saves them.
    """
    limits = await subscription_service.get_user_limits(db, current_user.id)

    test = await test_service.create_test_from_document(
        db,
        current_user.id,
        request.document_id,
        title=request.title,
        question_count=request.question_count,
        difficulty=request.difficulty,
        template_id=request.template_id,
        max_tests=limits["max_tests"],
        max_tokens=limits["max_tokens"],
        model=limits["model"],
    )
    return test


@router.get("/", response_model=TestListResponse)
async def list_tests(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tests for the current user."""
    test_status = TestStatus(status) if status else None
    return await test_service.list_tests(
        db, current_user.id, status=test_status, page=page, page_size=page_size
    )


@router.get("/{test_id}", response_model=TestDetailResponse)
async def get_test(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a test with its questions (without correct answers for active tests)."""
    return await test_service.get_test_detail(db, test_id, current_user.id)


@router.post("/{test_id}/start", response_model=TestResponse)
async def start_test(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a test as in_progress."""
    return await test_service.start_test(db, test_id, current_user.id)


@router.post("/{test_id}/submit", response_model=TestResultResponse)
async def submit_test(
    test_id: UUID,
    request: SubmitTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit all answers for a test and get results."""
    answers = [
        {"question_id": a.question_id, "response_text": a.response_text}
        for a in request.answers
    ]
    return await test_service.submit_test(db, test_id, current_user.id, answers)


@router.get("/{test_id}/results", response_model=TestResultResponse)
async def get_results(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed results for a completed test."""
    return await test_service.get_test_results(db, test_id, current_user.id)


@router.delete("/{test_id}", status_code=204)
async def delete_test(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a test and all its questions/responses."""
    await test_service.delete_test(db, test_id, current_user.id)

@router.post("/{test_id}/retake", response_model=TestResponse)
async def retake_test(
    test_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset a test to retake it."""
    return await test_service.retake_test(db, test_id, current_user.id)
