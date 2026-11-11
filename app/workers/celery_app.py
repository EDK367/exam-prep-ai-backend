import os
import re
from celery import Celery
from app.core.config import settings

def _clean_redis_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    match = re.search(r'(rediss?://\S+)', url)
    return match.group(1).strip("'\"") if match else url

broker_url = _clean_redis_url(os.getenv("CELERY_BROKER_URL")) or settings.CELERY_BROKER_URL or settings.REDIS_URL
result_backend = _clean_redis_url(os.getenv("CELERY_RESULT_BACKEND")) or settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

celery_app = Celery(
    "exam_prep_ai",
    broker=broker_url,
    backend=result_backend,
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

    # ── Optimizaciones para Redis Free Tier (30 MB) ──────────────────────
    # Expira resultados en 15 minutos (900 seg) para no saturar los 30 MB
    result_expires=900,
    # Comprime tareas y resultados para reducir el consumo de memoria en ~70%
    task_compression='gzip',
    result_compression='gzip',
    # Limita el almacenamiento previo de tareas por worker a 1
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Permite compartir la base de datos 0 en Redis Cloud separando por prefijos
    broker_transport_options={
        'global_keyprefix': 'exam_prep_broker:',
        'visibility_timeout': 3600,
    },
    result_backend_transport_options={
        'global_keyprefix': 'exam_prep_result:',
    },
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