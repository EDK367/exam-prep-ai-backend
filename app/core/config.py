from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from functools import lru_cache
from typing import Literal, Optional

class Settings(BaseSettings):
    # Configuración de Pydantic V2
    model_config = ConfigDict(
        extra='ignore'  # Esto ignora variables extra en lugar de rechazarlas
    )
    
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
    
    OPENROUTER_API_KEY: str = 'mock_key'
    
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_FILE_TYPES: list[str] = ['application/pdf']
    
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_AI_PER_HOUR: int = 20
    
    SUPABASE_ANON_KEY: Optional[str] = None
    SUPABASE_STORAGE_BUCKET: Optional[str] = None
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    SENTRY_DSN: Optional[str] = None
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()