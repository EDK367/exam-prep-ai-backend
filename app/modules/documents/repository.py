"""
Document & DocumentChunk repositories.
All DB access for the documents module goes through here.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import DocumentStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.db.repository import BaseRepository
from app.modules.documents.models import Document, DocumentChunk


class DocumentRepository(BaseRepository[Document]):
    def __init__(self):
        super().__init__(Document)

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        status: Optional[DocumentStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        filters = [Document.user_id == user_id]
        if status:
            filters.append(Document.status == status.value)
        return await self.get_paginated(
            db, page=page, page_size=page_size, filters=filters
        )

    async def get_with_chunks(
        self, db: AsyncSession, document_id: UUID
    ) -> Optional[Document]:
        result = await db.execute(
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id)
        )
        return result.scalars().first()

    async def count_by_user(self, db: AsyncSession, user_id: UUID) -> int:
        return await self.count(db, filters=[Document.user_id == user_id])

    async def update_status(
        self,
        db: AsyncSession,
        document_id: UUID,
        new_status: DocumentStatus,
        *,
        error_message: Optional[str] = None,
        extra_data: Optional[dict] = None,
    ) -> Document:
        doc = await self.get_by_id_or_raise(db, document_id)
        current_status = DocumentStatus(doc.status)
        if not current_status.can_transition_to(new_status):
            raise ValidationError(
                f"Cannot transition document from '{current_status.value}' to '{new_status.value}'"
            )
        update_data = {"status": new_status.value}
        if error_message is not None:
            update_data["error_message"] = error_message
        if extra_data:
            update_data.update(extra_data)
        return await self.update(db, doc, update_data)

    async def verify_ownership(
        self, db: AsyncSession, document_id: UUID, user_id: UUID
    ) -> Document:
        doc = await self.get_by_id_or_raise(db, document_id)
        if doc.user_id != user_id:
            raise NotFoundError("Document", str(document_id))
        return doc


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    def __init__(self):
        super().__init__(DocumentChunk)

    async def bulk_create(
        self,
        db: AsyncSession,
        document_id: UUID,
        chunks_data: list[dict],
    ) -> list[DocumentChunk]:
        chunk_objects = [
            DocumentChunk(
                document_id=document_id,
                chunk_index=c["chunk_index"],
                content=c["content"],
                metadata_json=c.get("metadata"),
            )
            for c in chunks_data
        ]
        return await self.create_many(db, chunk_objects)

    async def get_by_document(
        self, db: AsyncSession, document_id: UUID
    ) -> list[DocumentChunk]:
        result = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return list(result.scalars().all())

    async def delete_by_document(
        self, db: AsyncSession, document_id: UUID
    ) -> int:
        chunks = await self.get_by_document(db, document_id)
        count = len(chunks)
        for chunk in chunks:
            await db.delete(chunk)
        await db.commit()
        return count

    async def get_total_tokens(
        self, db: AsyncSession, document_id: UUID
    ) -> int:
        """Sum of token counts stored in metadata_json for a document."""
        chunks = await self.get_by_document(db, document_id)
        total = 0
        for chunk in chunks:
            if chunk.metadata_json and "token_count" in chunk.metadata_json:
                total += chunk.metadata_json["token_count"]
        return total


document_repo = DocumentRepository()
chunk_repo = DocumentChunkRepository()
