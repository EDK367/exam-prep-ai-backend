"""
File upload validation service.
Validates mime type, file size, page count, and plan limits before processing.
"""
try:
    import magic
except Exception:
    magic = None
import struct
from typing import Optional

import structlog

from app.core.config import settings
from app.core.exceptions import FileValidationError, PlanLimitExceededError

logger = structlog.get_logger(__name__)

ALLOWED_MIME_TYPES = {"application/pdf"}
PDF_MAGIC_BYTES = b"%PDF"
MAX_PAGES_FREE = 100
MAX_PAGES_PRO = 500


class FileValidator:
    """Validates uploaded files for security and plan compliance."""

    @staticmethod
    def validate_mime_type(file_bytes: bytes, filename: str) -> str:
        """
        Validate MIME type using magic bytes, not Content-Type header.
        Returns the detected MIME type.
        """
        # Check magic bytes first (most reliable)
        if not file_bytes[:4] == PDF_MAGIC_BYTES:
            raise FileValidationError(
                f"Invalid file format. Expected PDF, got unknown file type."
            )

        # Double-check with python-magic if available
        detected = "application/pdf"
        if magic is not None:
            try:
                detected = magic.from_buffer(file_bytes[:2048], mime=True)
            except Exception:
                # python-magic not available; trust the magic bytes check
                pass

        if detected not in ALLOWED_MIME_TYPES:
            raise FileValidationError(
                f"Invalid file type: {detected}. Only PDF files are allowed."
            )

        return detected

    @staticmethod
    def validate_file_size(file_bytes: bytes) -> int:
        """Validate file size against configured limit. Returns size in bytes."""
        size = len(file_bytes)
        max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024

        if size == 0:
            raise FileValidationError("File is empty")

        if size > max_size:
            raise FileValidationError(
                f"File size ({size / 1024 / 1024:.1f}MB) exceeds "
                f"the limit of {settings.MAX_FILE_SIZE_MB}MB"
            )

        return size

    @staticmethod
    def validate_page_count(page_count: int, max_pages: int = MAX_PAGES_FREE) -> None:
        """Validate page count against plan limits."""
        if page_count > max_pages:
            raise PlanLimitExceededError("pages", page_count, max_pages)

    @staticmethod
    def validate_upload_count(current_count: int, max_uploads: int) -> None:
        """Validate upload count against plan limits."""
        if current_count >= max_uploads:
            raise PlanLimitExceededError("uploads", current_count, max_uploads)

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Remove path separators and dangerous characters from filename."""
        import os
        import re

        # Remove path components
        filename = os.path.basename(filename)
        # Remove non-alphanumeric except dots, hyphens, underscores
        filename = re.sub(r"[^\w.\-]", "_", filename)
        # Limit length
        if len(filename) > 255:
            name, ext = os.path.splitext(filename)
            filename = name[:255 - len(ext)] + ext
        return filename

    @classmethod
    def validate_upload(
        cls,
        file_bytes: bytes,
        filename: str,
        current_upload_count: int,
        max_uploads: int,
    ) -> dict:
        """
        Run all validations. Returns validated metadata dict.
        Raises FileValidationError or PlanLimitExceededError on failure.
        """
        cls.validate_upload_count(current_upload_count, max_uploads)
        mime_type = cls.validate_mime_type(file_bytes, filename)
        file_size = cls.validate_file_size(file_bytes)
        safe_filename = cls.sanitize_filename(filename)

        logger.info(
            "file_validated",
            filename=safe_filename,
            size=file_size,
            mime_type=mime_type,
        )

        return {
            "filename": safe_filename,
            "mime_type": mime_type,
            "file_size": file_size,
        }


file_validator = FileValidator()
