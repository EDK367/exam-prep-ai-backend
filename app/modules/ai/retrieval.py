# app/modules/ai/retrieval.py
from sqlalchemy import select, func
from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.modules.documents.models import DocumentChunk, Embedding

class RetrievalService:
    async def similarity_search(
        self,
        db: AsyncSession,
        query_embedding: list[float],
        document_ids: list[UUID],
        top_k: int = 6,
        similarity_threshold: float = 0.75,
    ) -> list[DocumentChunk]:
        result = await db.execute(
            select(
                DocumentChunk,
                (1 - Embedding.vector.cosine_distance(query_embedding)).label('similarity')
            )
            .join(Embedding, DocumentChunk.id == Embedding.chunk_id)
            .where(DocumentChunk.document_id.in_(document_ids))
            .where((1 - Embedding.vector.cosine_distance(query_embedding)) >= similarity_threshold)
            .order_by(Embedding.vector.cosine_distance(query_embedding))
            .limit(top_k)
        )
        return result.all()
