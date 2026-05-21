"""
Document service — orchestrates upload, processing, and status management.
"""
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DocumentStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.documents.models import Document
from app.modules.documents.processor import pdf_processor
from app.modules.documents.repository import document_repo, chunk_repo
from app.modules.documents.storage import storage_backend
from app.modules.documents.validators import file_validator

logger = structlog.get_logger(__name__)


class DocumentService:
    """
    High-level document operations.
    Coordinates validation → storage → DB → task dispatch.
    """

    # ── Upload ───────────────────────────────────────────────────────────

    async def upload_document(
        self,
        db: AsyncSession,
        user_id: UUID,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        max_uploads: int = 50,
    ) -> Document:
        """
        Validate, store, and register a new document.
        Returns the created Document record.
        """
        # Count existing uploads
        current_count = await document_repo.count_by_user(db, user_id)

        # Run validations
        validated = file_validator.validate_upload(
            file_bytes=file_bytes,
            filename=filename,
            current_upload_count=current_count,
            max_uploads=max_uploads,
        )

        # Get page count for metadata
        page_count = pdf_processor.get_page_count(file_bytes)

        # Upload to storage
        storage_path = await storage_backend.upload(
            file_bytes=file_bytes,
            filename=validated["filename"],
            content_type=validated["mime_type"],
        )

        # Create DB record
        document = Document(
            user_id=user_id,
            filename=validated["filename"],
            storage_path=storage_path,
            size_types=validated["file_size"],
            status=DocumentStatus.UPLOADED.value,
            page_count=page_count,
            mime_type=validated["mime_type"],
        )
        document = await document_repo.create(db, document)

        logger.info(
            "document_uploaded",
            document_id=str(document.id),
            filename=document.filename,
            pages=page_count,
        )

        return document

    # ── Processing ───────────────────────────────────────────────────────

    async def process_document(
        self, db: AsyncSession, document_id: UUID
    ) -> Document:
        """
        Full processing pipeline:
        1. Download file from storage
        2. Extract text (with OCR fallback)
        3. Clean text
        4. Chunk document
        5. Save chunks to DB
        6. Update document status
        """
        doc = await document_repo.get_by_id_or_raise(db, document_id)

        # Transition to processing
        doc = await document_repo.update_status(
            db, document_id, DocumentStatus.PROCESSING
        )

        try:
            # Download file
            file_bytes = await storage_backend.download(doc.storage_path)

            # Extract text
            pages = pdf_processor.extract_text(file_bytes)
            total_chars = sum(p.char_count for p in pages)

            if total_chars < 50:
                raise ValidationError(
                    "Document contains insufficient text content for processing"
                )

            logger.info(
                "text_extracted",
                document_id=str(document_id),
                pages=len(pages),
                total_chars=total_chars,
            )

            # Chunk document
            chunks = pdf_processor.chunk_document(pages)

            # Delete existing chunks (for reprocessing)
            await chunk_repo.delete_by_document(db, document_id)

            # Save chunks
            chunks_data = [
                {
                    "chunk_index": c.chunk_index,
                    "content": c.content,
                    "metadata": c.metadata,
                }
                for c in chunks
            ]
            saved_chunks = await chunk_repo.bulk_create(db, document_id, chunks_data)

            # Update status to chunked
            doc = await document_repo.update_status(
                db,
                document_id,
                DocumentStatus.CHUNKED,
                extra_data={
                    "chunk_count": len(saved_chunks),
                    "page_count": len(pages),
                },
            )

            # Update status to completed so the frontend knows processing is fully done and ready
            doc = await document_repo.update_status(
                db,
                document_id,
                DocumentStatus.COMPLETED,
            )

            logger.info(
                "document_chunked",
                document_id=str(document_id),
                chunks=len(saved_chunks),
            )

            return doc

        except (ValidationError,):
            raise
        except Exception as exc:
            logger.error(
                "document_processing_failed",
                document_id=str(document_id),
                error=str(exc),
            )
            await document_repo.update_status(
                db,
                document_id,
                DocumentStatus.FAILED,
                error_message=str(exc),
            )
            raise

    # ── Query ────────────────────────────────────────────────────────────

    async def get_document(
        self, db: AsyncSession, document_id: UUID, user_id: UUID
    ) -> Document:
        return await document_repo.verify_ownership(db, document_id, user_id)

    async def get_document_file(
        self, db: AsyncSession, document_id: UUID, user_id: UUID
    ) -> tuple[bytes, str, str]:
        """Download raw PDF bytes for viewing (ownership verified)."""
        doc = await document_repo.verify_ownership(db, document_id, user_id)
        if not doc.storage_path:
            raise NotFoundError("Document file not found")
        file_bytes = await storage_backend.download(doc.storage_path)
        return file_bytes, doc.filename, doc.mime_type or "application/pdf"

    async def get_document_with_chunks(
        self, db: AsyncSession, document_id: UUID, user_id: UUID
    ) -> Document:
        doc = await document_repo.verify_ownership(db, document_id, user_id)
        return await document_repo.get_with_chunks(db, document_id)

    async def list_documents(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        status: Optional[DocumentStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        return await document_repo.get_by_user(
            db, user_id, status=status, page=page, page_size=page_size
        )

    async def get_processing_status(
        self, db: AsyncSession, document_id: UUID, user_id: UUID
    ) -> dict:
        doc = await document_repo.verify_ownership(db, document_id, user_id)
        progress_map = {
            DocumentStatus.UPLOADED: 0,
            DocumentStatus.PROCESSING: 25,
            DocumentStatus.CHUNKED: 50,
            DocumentStatus.AI_PROCESSING: 75,
            DocumentStatus.COMPLETED: 100,
            DocumentStatus.FAILED: 0,
            DocumentStatus.CANCELED: 0,
        }
        status = DocumentStatus(doc.status)
        return {
            "document_id": doc.id,
            "status": status,
            "progress_percent": progress_map.get(status, 0),
            "current_step": self._get_step_label(status),
            "error_message": doc.error_message,
            "chunk_count": doc.chunk_count,
            "celery_task_id": doc.celery_task_id,
        }

    # ── Delete ───────────────────────────────────────────────────────────

    async def delete_document(
        self, db: AsyncSession, document_id: UUID, user_id: UUID
    ) -> None:
        doc = await document_repo.verify_ownership(db, document_id, user_id)

        # Delete from storage
        if doc.storage_path:
            try:
                await storage_backend.delete(doc.storage_path)
            except Exception as exc:
                logger.warning(
                    "storage_delete_failed",
                    document_id=str(document_id),
                    error=str(exc),
                )

        # Delete from DB (cascades to chunks)
        await document_repo.delete(db, doc)
        logger.info("document_deleted", document_id=str(document_id))

    # ── Reprocess ────────────────────────────────────────────────────────

    async def reprocess_document(
        self, db: AsyncSession, document_id: UUID, user_id: UUID
    ) -> Document:
        """Reset a failed/completed document for reprocessing."""
        doc = await document_repo.verify_ownership(db, document_id, user_id)
        current = DocumentStatus(doc.status)

        if current not in (
            DocumentStatus.FAILED,
            DocumentStatus.COMPLETED,
            DocumentStatus.CANCELED,
        ):
            raise ValidationError(
                f"Cannot reprocess document in '{current.value}' status"
            )

        doc = await document_repo.update_status(
            db,
            document_id,
            DocumentStatus.PROCESSING,
            error_message=None,
        )
        return doc

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _get_step_label(status: DocumentStatus) -> str:
        labels = {
            DocumentStatus.UPLOADED: "Waiting for processing",
            DocumentStatus.PROCESSING: "Extracting text from PDF",
            DocumentStatus.CHUNKED: "Text extracted, ready for AI",
            DocumentStatus.AI_PROCESSING: "Generating content with AI",
            DocumentStatus.COMPLETED: "Processing complete",
            DocumentStatus.FAILED: "Processing failed",
            DocumentStatus.CANCELED: "Processing canceled",
        }
        return labels.get(status, "Unknown")


document_service = DocumentService()
