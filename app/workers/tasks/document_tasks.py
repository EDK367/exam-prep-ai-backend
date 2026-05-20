"""
Celery tasks for document processing and AI generation.
These run in background workers, separate from the API process.
"""
import asyncio
from uuid import UUID

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from app.workers.celery_app import celery_app
from app.core.enums import DocumentStatus, TestStatus

import structlog

logger = structlog.get_logger(__name__)


def _run_async(coro):
    """Helper to run async code from synchronous Celery tasks."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _process_document_async(document_id: str) -> dict:
    """Async implementation of document processing."""
    from app.db.session import AsyncSessionLocal
    from app.modules.documents.service import document_service

    async with AsyncSessionLocal() as db:
        doc = await document_service.process_document(db, UUID(document_id))
        return {
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "page_count": doc.page_count,
        }


async def _update_document_status_async(
    document_id: str, status: str, error_message: str = None
):
    """Update document status from sync context."""
    from app.db.session import AsyncSessionLocal
    from app.modules.documents.repository import document_repo

    async with AsyncSessionLocal() as db:
        await document_repo.update_status(
            db,
            UUID(document_id),
            DocumentStatus(status),
            error_message=error_message,
        )


@celery_app.task(
    bind=True,
    name="document_tasks.process_document",
    queue="documents",
    max_retries=3,
    default_retry_delay=120,
    soft_time_limit=300,
    time_limit=360,
)
def process_document(self, document_id: str) -> dict:
    """
    Full document processing pipeline:
    1. Download PDF from storage
    2. Extract text (with OCR fallback)
    3. Clean and chunk text
    4. Save chunks to DB
    5. Update document status
    """
    logger.info("task_started", task="process_document", document_id=document_id)

    try:
        result = _run_async(_process_document_async(document_id))
        logger.info(
            "task_completed",
            task="process_document",
            document_id=document_id,
            result=result,
        )
        return result

    except SoftTimeLimitExceeded:
        logger.error("task_timeout", task="process_document", document_id=document_id)
        _run_async(
            _update_document_status_async(
                document_id, DocumentStatus.FAILED.value, "Processing timed out"
            )
        )
        raise

    except Exception as exc:
        logger.error(
            "task_failed",
            task="process_document",
            document_id=document_id,
            error=str(exc),
            attempt=self.request.retries + 1,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        _run_async(
            _update_document_status_async(
                document_id,
                DocumentStatus.FAILED.value,
                f"Failed after {self.max_retries + 1} attempts: {exc}",
            )
        )
        raise


async def _generate_test_async(
    user_id: str,
    document_id: str,
    question_count: int,
    difficulty: str,
    model: str,
    test_id: str = None,
) -> dict:
    """Async implementation of test generation."""
    from app.db.session import AsyncSessionLocal
    from app.modules.tests.service import test_service

    async with AsyncSessionLocal() as db:
        test = await test_service.create_test_from_document(
            db,
            UUID(user_id),
            UUID(document_id),
            question_count=question_count,
            difficulty=difficulty,
            model=model,
        )
        return {
            "test_id": str(test.id),
            "status": test.status,
            "title": test.title,
        }


@celery_app.task(
    bind=True,
    name="ai_tasks.generate_test",
    queue="ai",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=180,
    time_limit=240,
)
def generate_test(
    self,
    user_id: str,
    document_id: str,
    question_count: int = 10,
    difficulty: str = "medium",
    model: str = "deepseek/deepseek-v4-flash:free",
) -> dict:
    """Background task for AI-powered test generation."""
    logger.info(
        "task_started",
        task="generate_test",
        user_id=user_id,
        document_id=document_id,
    )

    try:
        result = _run_async(
            _generate_test_async(
                user_id, document_id, question_count, difficulty, model
            )
        )
        logger.info("task_completed", task="generate_test", result=result)
        return result

    except SoftTimeLimitExceeded:
        logger.error("task_timeout", task="generate_test")
        raise

    except Exception as exc:
        logger.error(
            "task_failed",
            task="generate_test",
            error=str(exc),
            attempt=self.request.retries + 1,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        raise
