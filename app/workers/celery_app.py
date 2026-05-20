from celery import Celery
import os

celery_app = Celery(
    "exam_prep_ai",
    broker=os.getenv("CELERY_BROKER_URL"),
    backend=os.getenv("CELERY_RESULT_BACKEND"),
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
)

# IMPORTAR TASKS
import app.workers.tasks.document_tasks

# Import all models to ensure they are registered with SQLAlchemy's Base.metadata.
# This prevents SQLAlchemy from raising InvalidRequestError when querying models
# that have relationships with other unimported models (like User).
from app.modules.users.models import UserType, User
from app.modules.billing.models import Plan, UserSubscription
from app.modules.shared.models import Bitacora
from app.modules.documents.models import Document, DocumentChunk
from app.modules.tests.models import TestTemplate, Test, Question, UserResponse