"""
Repositories for tests, questions, and user responses.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import TestStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.db.repository import BaseRepository
from app.modules.tests.models import Test, Question, UserResponse, TestTemplate


class TestRepository(BaseRepository[Test]):
    def __init__(self):
        super().__init__(Test)

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        status: Optional[TestStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        filters = [Test.user_id == user_id]
        if status:
            filters.append(Test.status == status.value)
        return await self.get_paginated(
            db, page=page, page_size=page_size, filters=filters
        )

    async def get_with_questions(
        self, db: AsyncSession, test_id: UUID
    ) -> Optional[Test]:
        result = await db.execute(
            select(Test)
            .options(selectinload(Test.questions))
            .where(Test.id == test_id)
        )
        return result.scalars().first()

    async def get_with_questions_and_responses(
        self, db: AsyncSession, test_id: UUID
    ) -> Optional[Test]:
        result = await db.execute(
            select(Test)
            .options(
                selectinload(Test.questions).selectinload(Question.user_responses)
            )
            .where(Test.id == test_id)
        )
        return result.scalars().first()

    async def count_by_user(self, db: AsyncSession, user_id: UUID) -> int:
        return await self.count(db, filters=[Test.user_id == user_id])

    async def update_status(
        self,
        db: AsyncSession,
        test_id: UUID,
        new_status: TestStatus,
        *,
        error_message: Optional[str] = None,
    ) -> Test:
        test = await self.get_by_id_or_raise(db, test_id)
        current_status = TestStatus(test.status) if test.status else TestStatus.DRAFT
        if not current_status.can_transition_to(new_status):
            raise ValidationError(
                f"Cannot transition test from '{current_status.value}' to '{new_status.value}'"
            )
        update_data = {"status": new_status.value}
        if error_message:
            update_data["error_message"] = error_message
        return await self.update(db, test, update_data)

    async def verify_ownership(
        self, db: AsyncSession, test_id: UUID, user_id: UUID
    ) -> Test:
        test = await self.get_by_id_or_raise(db, test_id)
        if test.user_id != user_id:
            raise NotFoundError("Test", str(test_id))
        return test


class QuestionRepository(BaseRepository[Question]):
    def __init__(self):
        super().__init__(Question)

    async def bulk_create(
        self,
        db: AsyncSession,
        test_id: UUID,
        questions_data: list[dict],
    ) -> list[Question]:
        questions = [
            Question(
                test_id=test_id,
                questions_type=q.get("type", "multiple_choice"),
                points=q.get("points", 1.0),
                content=q,
            )
            for q in questions_data
        ]
        return await self.create_many(db, questions)

    async def get_by_test(
        self, db: AsyncSession, test_id: UUID
    ) -> list[Question]:
        result = await db.execute(
            select(Question)
            .where(Question.test_id == test_id)
            .order_by(Question.created_at)
        )
        return list(result.scalars().all())


class UserResponseRepository(BaseRepository[UserResponse]):
    def __init__(self):
        super().__init__(UserResponse)

    async def bulk_create(
        self,
        db: AsyncSession,
        responses_data: list[dict],
    ) -> list[UserResponse]:
        responses = [
            UserResponse(
                question_id=r["question_id"],
                response_text=r["response_text"],
                is_correct=r.get("is_correct"),
            )
            for r in responses_data
        ]
        return await self.create_many(db, responses)

    async def get_by_question(
        self, db: AsyncSession, question_id: UUID
    ) -> list[UserResponse]:
        result = await db.execute(
            select(UserResponse).where(UserResponse.question_id == question_id)
        )
        return list(result.scalars().all())

    async def get_by_test(
        self, db: AsyncSession, test_id: UUID
    ) -> list[UserResponse]:
        result = await db.execute(
            select(UserResponse)
            .join(Question, UserResponse.question_id == Question.id)
            .where(Question.test_id == test_id)
        )
        return list(result.scalars().all())


class TestTemplateRepository(BaseRepository[TestTemplate]):
    def __init__(self):
        super().__init__(TestTemplate)

    async def get_active(self, db: AsyncSession) -> list[TestTemplate]:
        return await self.get_all(
            db, filters=[TestTemplate.is_active == True], limit=50
        )


test_repo = TestRepository()
question_repo = QuestionRepository()
user_response_repo = UserResponseRepository()
test_template_repo = TestTemplateRepository()
