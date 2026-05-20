import os

dirs = [
    "app/api/v1",
    "app/core",
    "app/db",
    "app/modules/users",
    "app/modules/documents",
    "app/modules/ai/pipelines",
    "app/modules/sessions",
    "app/modules/billing",
    "app/workers/tasks",
    "app/shared",
    "tests/unit",
    "tests/integration",
    "tests/e2e",
    "migrations/versions",
    "infra/docker",
    "infra/nginx",
    "infra/k8s",
    "scripts"
]

for d in dirs:
    os.makedirs(d, exist_ok=True)

files = {}

files["app/api/deps.py"] = """# app/api/deps.py — Dependency Injection
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
# from app.db.session import get_db
# from app.modules.users.models import User
# from app.modules.users.repository import user_repo
# from app.modules.users.service import user_service
from app.core.security import jwt_validator

bearer_scheme = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    # db: AsyncSession = Depends(get_db),
):
    payload = await jwt_validator.validate(credentials.credentials)
    supabase_id = payload['sub']
    # user = await user_repo.get_by_supabase_id(db, supabase_id)
    # if not user:
    #     user = await user_service.sync_from_supabase(db, payload)
    # return user
    return payload # Mocked return

def require_role(*roles: str):
    async def check(user = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(403, 'Insufficient permissions')
        return user
    return check
"""

files["app/core/security.py"] = """# app/core/security.py
import httpx
from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import HTTPException
from datetime import datetime
from app.core.config import settings

class SupabaseJWTValidator:
    def __init__(self):
        self._jwks = None
        self._jwks_fetched_at = None

    async def _get_jwks(self) -> dict:
        now = datetime.utcnow()
        if self._jwks is None or (now - self._jwks_fetched_at).seconds > 3600:
            async with httpx.AsyncClient() as client:
                resp = await client.get(settings.SUPABASE_JWKS_URL)
                self._jwks = resp.json()
                self._jwks_fetched_at = now
        return self._jwks

    async def validate(self, token: str) -> dict:
        try:
            jwks = await self._get_jwks()
            payload = jwt.decode(
                token,
                jwks,
                algorithms=['RS256'],
                audience='authenticated',
                options={'verify_exp': True}
            )
            return payload
        except ExpiredSignatureError:
            raise HTTPException(401, 'Token expired')
        except JWTError as e:
            raise HTTPException(401, f'Invalid token: {e}')

jwt_validator = SupabaseJWTValidator()
"""

files["app/db/mixins.py"] = """# app/db/mixins.py
import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID

class UUIDMixin:
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SoftDeleteMixin:
    deleted_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False)
"""

files["app/modules/documents/models.py"] = """# app/modules/documents/models.py
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Integer, ForeignKey, Text, JSON, Enum, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
# from app.db.base import Base
from sqlalchemy.orm import declarative_base
Base = declarative_base()
from app.db.mixins import UUIDMixin, TimestampMixin

class Document(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'documents'
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    file_path = Column(String(1000))  # Supabase Storage path
    file_size_bytes = Column(Integer)
    page_count = Column(Integer)
    status = Column(Enum('pending','processing','ready','error', name='document_status_enum'), default='pending')
    processing_metadata = Column(JSON)  # {chunks: N, tokens: N, model: '...'}
    chunks = relationship('DocumentChunk', back_populates='document')

class DocumentChunk(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'document_chunks'
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), nullable=False)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    token_count = Column(Integer)
    page_number = Column(Integer)
    chunk_metadata = Column(JSON)
    embedding = relationship('Embedding', back_populates='chunk', uselist=False)

class Embedding(Base, UUIDMixin):
    __tablename__ = 'embeddings'
    chunk_id = Column(UUID(as_uuid=True), ForeignKey('document_chunks.id'), nullable=False)
    vector = Column(Vector(1536))  # text-embedding-3-small dimension
    model = Column(String(100), default='text-embedding-3-small')
    created_at = Column(DateTime, default=datetime.utcnow)
"""

files["app/modules/documents/processor.py"] = """# app/modules/documents/processor.py
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pdfplumber import open as pdf_open
import tiktoken
from pydantic import BaseModel

class ChunkData(BaseModel):
    content: str
    chunk_index: int
    token_count: int

class PDFProcessor:
    CHUNK_SIZE = 800      # tokens — sweet spot para GPT-4o
    CHUNK_OVERLAP = 150   # 20% overlap para mantener contexto

    def __init__(self):
        self.tokenizer = tiktoken.encoding_for_model('gpt-4o')
        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            model_name='gpt-4o',
            chunk_size=self.CHUNK_SIZE,
            chunk_overlap=self.CHUNK_OVERLAP,
            separators=['\\n\\n', '\\n', '. ', '! ', '? ', ' ', '']
        )

    def extract_text(self, file_path: str) -> list[dict]:
        pages = []
        with pdf_open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ''
                pages.append({'page_number': i+1, 'text': text})
        return pages

    def chunk_document(self, pages: list[dict]) -> list[ChunkData]:
        full_text = '\\n\\n'.join(p['text'] for p in pages)
        raw_chunks = self.splitter.split_text(full_text)
        chunks = []
        for idx, chunk_text in enumerate(raw_chunks):
            token_count = len(self.tokenizer.encode(chunk_text))
            chunks.append(ChunkData(
                content=chunk_text,
                chunk_index=idx,
                token_count=token_count,
            ))
        return chunks
"""

files["app/modules/ai/embeddings.py"] = """# app/modules/ai/embeddings.py
from openai import AsyncOpenAI
# from app.shared.cache import redis_cache
import hashlib

# Mock redis_cache
class MockRedis:
    async def get(self, key): return None
    async def set(self, key, val, ttl): pass
redis_cache = MockRedis()

class EmbeddingService:
    MODEL = 'text-embedding-3-small'
    BATCH_SIZE = 100

    def __init__(self, client: AsyncOpenAI):
        self.client = client

    async def embed_chunks(self, chunks: list[str]) -> list[list[float]]:
        all_embeddings = []
        for i in range(0, len(chunks), self.BATCH_SIZE):
            batch = chunks[i:i + self.BATCH_SIZE]
            cached, uncached_idxs, uncached_texts = [], [], []
            for j, text in enumerate(batch):
                cache_key = f'emb:{{hashlib.md5(text.encode()).hexdigest()}}'
                cached_val = await redis_cache.get(cache_key)
                if cached_val:
                    cached.insert(j, cached_val)
                else:
                    uncached_idxs.append(j)
                    uncached_texts.append(text)
            if uncached_texts:
                response = await self.client.embeddings.create(
                    model=self.MODEL,
                    input=uncached_texts,
                )
                for k, emb in enumerate(response.data):
                    text = uncached_texts[k]
                    cache_key = f'emb:{{hashlib.md5(text.encode()).hexdigest()}}'
                    await redis_cache.set(cache_key, emb.embedding, ttl=2592000)
                    cached.insert(uncached_idxs[k], emb.embedding)
            all_embeddings.extend(cached)
        return all_embeddings
"""

files["app/modules/ai/retrieval.py"] = """# app/modules/ai/retrieval.py
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
"""

files["app/modules/ai/pipelines/rag.py"] = """# app/modules/ai/pipelines/rag.py
from uuid import UUID
from pydantic import BaseModel

class RAGResponse(BaseModel):
    answer: str
    sources: list[dict]
    tokens_used: int

class Message(BaseModel):
    role: str
    content: str

class RAGPipeline:
    def __init__(self, embedding_svc, retrieval_svc, db, llm, usage_svc):
        self.embedding_svc = embedding_svc
        self.retrieval_svc = retrieval_svc
        self.db = db
        self.llm = llm
        self.usage_svc = usage_svc

    async def run(
        self,
        question: str,
        document_ids: list[UUID],
        conversation_history: list[Message],
        user,
    ) -> RAGResponse:
        query_embedding = await self.embedding_svc.embed_single(question)
        relevant_chunks = await self.retrieval_svc.similarity_search(
            self.db, query_embedding, document_ids, top_k=6
        )
        context = self._build_context(relevant_chunks, max_tokens=3000)
        messages = self._build_messages(question, context, conversation_history)
        response = await self.llm.chat(
            messages=messages,
            model='gpt-4o',
            temperature=0.1,
            max_tokens=2000,
        )
        await self.usage_svc.log(user.id, 'rag_chat', response.usage)
        return RAGResponse(
            answer=response.content,
            sources=[{'id': str(c.id)} for c in relevant_chunks], # Mocking c.to_source_ref()
            tokens_used=response.usage.total_tokens,
        )
    
    def _build_context(self, relevant_chunks, max_tokens):
        return "" # placeholder
    
    def _build_messages(self, question, context, conversation_history):
        return [] # placeholder
"""

files["app/workers/celery_app.py"] = """# app/workers/celery_app.py
from celery import Celery
from app.core.config import settings

celery_app = Celery('exam_prep_ai')

celery_app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_routes={
        'workers.tasks.document_tasks.*': {'queue': 'documents'},
        'workers.tasks.ai_tasks.*':       {'queue': 'ai'},
        'workers.tasks.notification_tasks.*': {'queue': 'notifications'},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_max_retries=3,
    task_default_retry_delay=60,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
)
"""

files["app/workers/tasks/document_tasks.py"] = """# app/workers/tasks/document_tasks.py
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from app.workers.celery_app import celery_app

@celery_app.task(
    bind=True,
    name='document_tasks.process_document',
    queue='documents',
    max_retries=3,
    default_retry_delay=120,
    soft_time_limit=300,
    time_limit=360,
)
def process_document(self, document_id: str) -> dict:
    try:
        # db = get_sync_session()
        # doc_repo.update_status(db, document_id, 'processing')
        # file_path = storage.download(doc.file_path)
        # pages = processor.extract_text(file_path)
        # chunks = processor.chunk_document(pages)
        # saved_chunks = chunk_repo.bulk_create(db, document_id, chunks)
        # texts = [c.content for c in saved_chunks]
        # embeddings = embedding_svc.embed_chunks_sync(texts)
        # embedding_repo.bulk_create(db, saved_chunks, embeddings)
        # doc_repo.update_status(db, document_id, 'ready', metadata={'chunks': len(chunks)})
        return {'status': 'ok', 'chunks': 0}
    except SoftTimeLimitExceeded:
        # doc_repo.update_status(db, document_id, 'error', error='Timeout')
        raise
    except Exception as exc:
        # doc_repo.update_status(db, document_id, 'error', error=str(exc))
        raise self.retry(exc=exc)
"""

files["app/core/config.py"] = """# app/core/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Literal

class Settings(BaseSettings):
    APP_ENV: Literal['development', 'staging', 'production'] = 'development'
    APP_VERSION: str = '1.0.0'
    DEBUG: bool = False
    SECRET_KEY: str = 'supersecretkey12345678901234567890'
    ALLOWED_ORIGINS: list[str] = ['http://localhost:3000']
    
    DATABASE_URL: str = 'postgresql+asyncpg://postgres:postgres@localhost:5432/exam_prep_ai'
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    REDIS_URL: str = 'redis://localhost:6379/0'
    CACHE_TTL_DEFAULT: int = 3600
    
    SUPABASE_URL: str = 'https://mock.supabase.co'
    SUPABASE_SERVICE_KEY: str = 'mock_key'
    SUPABASE_JWT_SECRET: str = 'mock_secret'
    SUPABASE_JWKS_URL: str = 'https://mock.supabase.co/auth/v1/.well-known/jwks.json'
    
    OPENAI_API_KEY: str = 'sk-mock'
    OPENAI_DEFAULT_MODEL: str = 'gpt-4o'
    OPENAI_EMBEDDING_MODEL: str = 'text-embedding-3-small'
    OPENAI_MAX_TOKENS_PER_REQUEST: int = 4000
    OPENAI_MONTHLY_BUDGET_USD: float = 500.0
    
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_FILE_TYPES: list[str] = ['application/pdf']
    
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_AI_PER_HOUR: int = 20

    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        case_sensitive = True

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
"""

files[".env.example"] = """# Application
APP_ENV=development
DEBUG=true
SECRET_KEY=your-secret-key-min-32-chars
ALLOWED_ORIGINS=["http://localhost:3000","http://localhost:5173"]

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/exam_prep_ai
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://localhost:6379/0

# Supabase
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIs...
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIs...
SUPABASE_JWT_SECRET=your-supabase-jwt-secret
SUPABASE_JWKS_URL=https://xxxxxxxxxxxx.supabase.co/auth/v1/.well-known/jwks.json

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_DEFAULT_MODEL=gpt-4o
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_MONTHLY_BUDGET_USD=500

# File Storage
SUPABASE_STORAGE_BUCKET=documents
MAX_FILE_SIZE_MB=50

# Rate Limiting
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_AI_PER_HOUR=20

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Monitoring
SENTRY_DSN=https://...@sentry.io/...
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
"""

files["infra/docker/Dockerfile.api"] = """# infra/docker/Dockerfile.api
FROM python:3.12-slim as base

ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PIP_NO_CACHE_DIR=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \\
    libpq-dev gcc build-essential \\
    poppler-utils tesseract-ocr \\
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY pyproject.toml ./
RUN pip install uv && uv pip install --system .

COPY . .

# Non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

files["docker-compose.yml"] = """version: '3.9'
services:
  api:
    build:
      context: .
      dockerfile: infra/docker/Dockerfile.api
    ports: ['8000:8000']
    env_file: .env.development
    volumes: ['.:/app']
    command: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    depends_on: [postgres, redis]
    networks: [exam_prep_net]

  worker:
    build:
      context: .
      dockerfile: infra/docker/Dockerfile.worker
    env_file: .env.development
    command: celery -A app.workers.celery_app worker -Q documents,ai,notifications -c 4 -l INFO
    depends_on: [postgres, redis]
    networks: [exam_prep_net]
    deploy:
      replicas: 2

  flower:
    image: mher/flower:2.0
    ports: ['5555:5555']
    env_file: .env.development
    command: celery --broker=redis://redis:6379/1 flower
    depends_on: [redis]
    networks: [exam_prep_net]

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: exam_prep_ai
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports: ['5432:5432']
    volumes: [postgres_data:/var/lib/postgresql/data]
    networks: [exam_prep_net]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      retries: 5

  redis:
    image: redis:7-alpine
    ports: ['6379:6379']
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes: [redis_data:/data]
    networks: [exam_prep_net]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s

volumes:
  postgres_data:
  redis_data:

networks:
  exam_prep_net:
    driver: bridge
"""

files["infra/docker/Dockerfile.worker"] = """# infra/docker/Dockerfile.worker
FROM python:3.12-slim as base

ENV PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PIP_NO_CACHE_DIR=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \\
    libpq-dev gcc build-essential \\
    poppler-utils tesseract-ocr \\
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY pyproject.toml ./
RUN pip install uv && uv pip install --system .

COPY . .

# Non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

CMD ["celery", "-A", "app.workers.celery_app", "worker", "-Q", "documents,ai,notifications", "-c", "4", "-l", "INFO"]
"""

files["pyproject.toml"] = """[build-system]
requires = ['setuptools>=68']
build-backend = 'setuptools.backends.legacy:build'

[project]
name = 'exam-prep-ai'
version = '1.0.0'
requires-python = '>=3.12'
dependencies = [
    'fastapi[standard]>=0.115',
    'uvicorn[standard]>=0.30',
    'python-multipart>=0.0.9',
    'sqlalchemy[asyncio]>=2.0',
    'asyncpg>=0.29',
    'alembic>=1.13',
    'pgvector>=0.3',
    'pydantic>=2.8',
    'pydantic-settings>=2.4',
    'email-validator>=2.2',
    'python-jose[cryptography]>=3.3',
    'httpx>=0.27',
    'redis>=5.0',
    'celery>=5.4',
    'flower>=2.0',
    'openai>=1.40',
    'tiktoken>=0.7',
    'langchain-text-splitters>=0.2',
    'pdfplumber>=0.11',
    'pypdf>=4.3',
    'pillow>=10.4',
    'supabase>=2.6',
    'boto3>=1.35',
    'structlog>=24.4',
    'sentry-sdk[fastapi]>=2.13',
    'opentelemetry-sdk>=1.26',
    'opentelemetry-exporter-otlp>=1.26',
    'prometheus-client>=0.20',
    'slowapi>=0.1.9'
]

[dependency-groups]
dev = [
    'pytest>=8.3',
    'pytest-asyncio>=0.24',
    'pytest-cov>=5.0',
    'httpx>=0.27',
    'factory-boy>=3.3',
    'faker>=28.0',
    'ruff>=0.6',
    'mypy>=1.11',
    'pre-commit>=3.8',
]
"""

files["app/shared/rate_limiter.py"] = """# app/shared/rate_limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)
"""

files["app/modules/billing/service.py"] = """# app/modules/billing/service.py
class BudgetExceededError(Exception):
    pass

COST_PER_1K_TOKENS = {
    'gpt-4o': {'input': 0.005, 'output': 0.015},
    'gpt-4o-mini': {'input': 0.00015, 'output': 0.0006},
    'text-embedding-3-small': {'input': 0.00002, 'output': 0},
    'text-embedding-3-large': {'input': 0.00013, 'output': 0},
}

class BillingService:
    async def get_monthly_cost(self, user_id):
        return 0.0

    async def log_usage(self, user_id, model, tokens_in, tokens_out, cost):
        pass

    async def check_and_log_usage(
        self, user, model: str, tokens_in: int, tokens_out: int
    ) -> None:
        cost = (
            tokens_in / 1000 * COST_PER_1K_TOKENS[model]['input'] +
            tokens_out / 1000 * COST_PER_1K_TOKENS[model]['output']
        )
        monthly_cost = await self.get_monthly_cost(user.id)
        if monthly_cost + cost > user.monthly_budget_usd:
            raise BudgetExceededError('Monthly AI budget exceeded')
        await self.log_usage(user.id, model, tokens_in, tokens_out, cost)
"""

files["tests/conftest.py"] = """# tests/conftest.py
import pytest_asyncio
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
# from app.main import app
# from app.api.deps import get_db
# from app.db.base import Base

TEST_DATABASE_URL = 'postgresql+asyncpg://postgres:postgres@localhost:5432/exam_prep_test'

@pytest.fixture(scope='session')
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

# @pytest_asyncio.fixture(scope='function')
# async def db_session():
#     engine = create_async_engine(TEST_DATABASE_URL)
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)
#     async with AsyncSession(engine) as session:
#         yield session
#         await session.rollback()
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.drop_all)

# @pytest_asyncio.fixture
# async def api_client(db_session):
#     app.dependency_overrides[get_db] = lambda: db_session
#     async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
#         yield c
"""

files["app/core/logging.py"] = """# app/core/logging.py
import structlog

def configure_logging():
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt='iso'),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

logger = structlog.get_logger(__name__)
"""

files["app/api/v1/router.py"] = """# app/api/v1/router.py
from fastapi import APIRouter
# from app.api.v1 import auth, users, documents, ai, sessions, health

api_router = APIRouter(prefix='/api/v1')
# api_router.include_router(health.router,     prefix='/health',    tags=['Health'])
# api_router.include_router(auth.router,       prefix='/auth',      tags=['Auth'])
# api_router.include_router(users.router,      prefix='/users',     tags=['Users'])
# api_router.include_router(documents.router,  prefix='/documents', tags=['Documents'])
# api_router.include_router(ai.router,         prefix='/ai',        tags=['AI'])
# api_router.include_router(sessions.router,   prefix='/sessions',  tags=['Sessions'])
"""

files["app/shared/schemas.py"] = """# app/shared/schemas.py
from pydantic import BaseModel
from typing import Generic, TypeVar, Literal

T = TypeVar('T')

class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    meta: dict | None = None

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool

class JobResponse(BaseModel):
    job_id: str
    status: Literal['queued', 'processing', 'completed', 'failed']
    progress: int
    result_url: str | None = None
    error: str | None = None
"""

files["Makefile"] = """# Makefile
dev:
	docker-compose up -d

migrate:
	alembic upgrade head

worker:
	celery -A app.workers.celery_app worker -Q documents,ai -c 4 -l INFO

test:
	pytest tests/ -v --cov=app --cov-report=term-missing

lint:
	ruff check app/ tests/ && mypy app/

format:
	ruff format app/ tests/
"""

files[".env.development"] = files[".env.example"]

for filepath, content in files.items():
    with open(filepath, 'w') as f:
        f.write(content)

print("Scaffolding completed.")
