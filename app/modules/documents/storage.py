"""
Storage abstraction layer.
Supports local filesystem (dev) and Supabase Storage (production).
"""
import os
import uuid
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/documents")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class StorageBackend(ABC):
    """Abstract storage interface."""

    @abstractmethod
    async def upload(
        self, file_bytes: bytes, filename: str, content_type: str
    ) -> str:
        """Upload file and return the storage path."""

    @abstractmethod
    async def download(self, storage_path: str) -> bytes:
        """Download file bytes by storage path."""

    @abstractmethod
    async def delete(self, storage_path: str) -> bool:
        """Delete file. Returns True if deleted."""

    @abstractmethod
    async def get_url(self, storage_path: str) -> Optional[str]:
        """Get a temporary/public URL for the file."""


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage for development."""

    def __init__(self, base_dir: Path = UPLOAD_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def upload(
        self, file_bytes: bytes, filename: str, content_type: str
    ) -> str:
        ext = Path(filename).suffix
        unique_name = f"{uuid.uuid4()}{ext}"
        file_path = self.base_dir / unique_name

        file_path.write_bytes(file_bytes)
        logger.info("file_uploaded_local", path=str(file_path), size=len(file_bytes))
        return str(file_path)

    async def download(self, storage_path: str) -> bytes:
        path = Path(storage_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {storage_path}")
        return path.read_bytes()

    async def delete(self, storage_path: str) -> bool:
        path = Path(storage_path)
        if path.exists():
            path.unlink()
            logger.info("file_deleted_local", path=storage_path)
            return True
        return False

    async def get_url(self, storage_path: str) -> Optional[str]:
        return f"/uploads/{Path(storage_path).name}"


class SupabaseStorageBackend(StorageBackend):
    """Supabase Storage backend for production."""

    def __init__(self):
        from supabase import create_client

        self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        self.bucket = settings.SUPABASE_STORAGE_BUCKET or "documents"

    async def upload(
        self, file_bytes: bytes, filename: str, content_type: str
    ) -> str:
        ext = Path(filename).suffix
        storage_path = f"documents/{uuid.uuid4()}{ext}"

        self.client.storage.from_(self.bucket).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type},
        )
        logger.info(
            "file_uploaded_supabase", path=storage_path, size=len(file_bytes)
        )
        return storage_path

    async def download(self, storage_path: str) -> bytes:
        response = self.client.storage.from_(self.bucket).download(storage_path)
        return response

    async def delete(self, storage_path: str) -> bool:
        self.client.storage.from_(self.bucket).remove([storage_path])
        logger.info("file_deleted_supabase", path=storage_path)
        return True

    async def get_url(self, storage_path: str) -> Optional[str]:
        result = self.client.storage.from_(self.bucket).create_signed_url(
            storage_path, expires_in=3600
        )
        return result.get("signedURL")


def get_storage_backend() -> StorageBackend:
    """Factory: returns the appropriate backend based on environment."""
    if settings.APP_ENV == "production" and settings.SUPABASE_STORAGE_BUCKET:
        return SupabaseStorageBackend()
    return LocalStorageBackend()


storage_backend = get_storage_backend()
