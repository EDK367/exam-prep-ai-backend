from sqlalchemy import Column, String, Integer, ForeignKey, Float, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
from app.db.mixins import UUIDMixin, TimestampMixin


class Bitacora(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'bitacora'

    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)
    status = Column(String(50))  # success, failed, timeout, rate_limited
    model = Column(String(100), nullable=True)
    request_type = Column(String(100), nullable=True)  # exam_generation, summary, flashcards
    error_message = Column(Text, nullable=True)

    user = relationship("User", back_populates="bitacora_entries")
