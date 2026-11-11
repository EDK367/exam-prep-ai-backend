import re
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
from functools import lru_cache
from typing import Literal, Optional

class Settings(BaseSettings):
    # Configuración de Pydantic Settings
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'
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
    CACHE_TTL_DEFAULT: int = 900  # Optimizado a 15 min para Redis de 30 MB
    
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

    @field_validator('DATABASE_URL', mode='before')
    @classmethod
    def sanitize_database_url(cls, v: Optional[str]) -> Optional[str]:
        """Asegura que el esquema de la base de datos use el driver asyncpg para SQLAlchemy asíncrono."""
        if not v or not isinstance(v, str):
            return v
        v = v.strip()
        if v.startswith('postgres://'):
            return 'postgresql+asyncpg://' + v[len('postgres://'):]
        if v.startswith('postgresql://') and not v.startswith('postgresql+asyncpg://'):
            return 'postgresql+asyncpg://' + v[len('postgresql://'):]
        return v

    @field_validator('REDIS_URL', 'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND', mode='before')
    @classmethod
    def sanitize_redis_url(cls, v: Optional[str]) -> Optional[str]:
        """Limpia prefijos de CLI como 'redis-cli -u' si se copiaron de la consola."""
        if not v or not isinstance(v, str):
            return v
        v = v.strip()
        match = re.search(r'(rediss?://\S+)', v)
        if match:
            return match.group(1).strip("'\"")
        return v

    @model_validator(mode='after')
    def set_celery_defaults(self):
        """Asigna CELERY_BROKER_URL y CELERY_RESULT_BACKEND a REDIS_URL si no están definidos."""
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = self.REDIS_URL
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()