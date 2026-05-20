from sqlalchemy import Column, String, Integer, ForeignKey, Text, JSON, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
from app.db.mixins import UUIDMixin, TimestampMixin
from app.core.enums import DocumentStatus


class Document(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'documents'

    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    filename = Column(String(500), nullable=False)
    storage_path = Column(String(1000))
    size_types = Column(Integer)  # File size in bytes
    status = Column(String(50), default=DocumentStatus.UPLOADED.value, index=True)
    page_count = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    mime_type = Column(String(100), nullable=True)

    user = relationship("User", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'document_chunks'

    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON)  # { token_count, page_range, ... }

    document = relationship("Document", back_populates="chunks")
