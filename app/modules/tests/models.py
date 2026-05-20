from sqlalchemy import Column, String, Integer, ForeignKey, Boolean, JSON, Float, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base
from app.db.mixins import UUIDMixin, TimestampMixin
from app.core.enums import TestStatus


class TestTemplate(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'test_templates'

    name = Column(String(255), nullable=False)
    duration_minutes = Column(Integer)
    passing_score = Column(Float)
    difficulty = Column(String(50))
    question_count = Column(Integer)
    is_active = Column(Boolean, default=True)

    tests = relationship("Test", back_populates="template")


class Test(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'tests'

    title = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    status = Column(String(50), default=TestStatus.DRAFT.value, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), nullable=True, index=True)
    test_template_id = Column(UUID(as_uuid=True), ForeignKey('test_templates.id'), nullable=True)
    score = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)

    user = relationship("User", back_populates="tests")
    document = relationship("Document", backref="tests")
    template = relationship("TestTemplate", back_populates="tests")
    questions = relationship("Question", back_populates="test", cascade="all, delete-orphan")


class Question(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'questions'

    test_id = Column(UUID(as_uuid=True), ForeignKey('tests.id'), nullable=False, index=True)
    questions_type = Column(String(50))  # multiple_choice, true_false, open_question, flashcard
    points = Column(Float, default=1.0)
    content = Column(JSON, nullable=False)  # { "question", "options", "correct_answer", "explanation" }

    test = relationship("Test", back_populates="questions")
    user_responses = relationship("UserResponse", back_populates="question", cascade="all, delete-orphan")


class UserResponse(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'user_responses'

    question_id = Column(UUID(as_uuid=True), ForeignKey('questions.id'), nullable=False, index=True)
    response_text = Column(JSON)  # User's answer
    is_correct = Column(Boolean)

    question = relationship("Question", back_populates="user_responses")
