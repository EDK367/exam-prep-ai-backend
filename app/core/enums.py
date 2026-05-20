"""
Domain enums for document and test state machines.
These enforce valid state transitions throughout the application.
"""
from enum import Enum


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    CHUNKED = "chunked"
    AI_PROCESSING = "ai_processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    @classmethod
    def valid_transitions(cls) -> dict["DocumentStatus", list["DocumentStatus"]]:
        return {
            cls.UPLOADED: [cls.PROCESSING, cls.CANCELED],
            cls.PROCESSING: [cls.CHUNKED, cls.FAILED, cls.CANCELED],
            cls.CHUNKED: [cls.AI_PROCESSING, cls.FAILED, cls.CANCELED, cls.COMPLETED],
            cls.AI_PROCESSING: [cls.COMPLETED, cls.FAILED, cls.CANCELED],
            cls.COMPLETED: [cls.PROCESSING],  # allow reprocessing
            cls.FAILED: [cls.PROCESSING],     # allow retry
            cls.CANCELED: [cls.PROCESSING],   # allow restart
        }

    def can_transition_to(self, new_status: "DocumentStatus") -> bool:
        allowed = self.valid_transitions().get(self, [])
        return new_status in allowed


class TestStatus(str, Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

    @classmethod
    def valid_transitions(cls) -> dict["TestStatus", list["TestStatus"]]:
        return {
            cls.DRAFT: [cls.GENERATING],
            cls.GENERATING: [cls.READY, cls.FAILED],
            cls.READY: [cls.IN_PROGRESS],
            cls.IN_PROGRESS: [cls.COMPLETED],
            cls.COMPLETED: [],  # terminal
            cls.FAILED: [cls.GENERATING],  # allow retry
        }

    def can_transition_to(self, new_status: "TestStatus") -> bool:
        allowed = self.valid_transitions().get(self, [])
        return new_status in allowed


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    OPEN_QUESTION = "open_question"
    FLASHCARD = "flashcard"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELED = "canceled"
    TRIAL = "trial"


class BitacoraStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
