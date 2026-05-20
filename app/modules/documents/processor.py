"""
PDF processing pipeline: extraction, cleaning, chunking.
Supports text-based PDFs with OCR fallback for scanned documents.
"""
import re
import unicodedata
from io import BytesIO
from typing import Optional

import structlog
import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel

from app.core.exceptions import PDFExtractionError, ChunkingError

logger = structlog.get_logger(__name__)


class PageData(BaseModel):
    page_number: int
    text: str
    char_count: int = 0
    is_ocr: bool = False


class ChunkData(BaseModel):
    content: str
    chunk_index: int
    token_count: int
    metadata: dict


class PDFProcessor:
    """
    Enterprise PDF processor:
    1. Extract text via pdfplumber (fast, accurate for text PDFs)
    2. Fall back to OCR via pytesseract for scanned/image pages
    3. Clean and normalize extracted text
    4. Chunk with token-aware splitting
    """

    CHUNK_SIZE = 800       # tokens — sweet spot for GPT-4o
    CHUNK_OVERLAP = 150    # ~20% overlap for context continuity
    MIN_PAGE_CHARS = 20    # threshold below which we try OCR

    def __init__(self):
        self.tokenizer = tiktoken.encoding_for_model("gpt-4o")
        self.splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
            model_name="gpt-4o",
            chunk_size=self.CHUNK_SIZE,
            chunk_overlap=self.CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""],
        )

    # ── Public API ───────────────────────────────────────────────────────

    def extract_text(self, file_path_or_bytes) -> list[PageData]:
        """
        Extract text from all pages. Accepts a file path (str) or raw bytes.
        Falls back to OCR for pages with insufficient text.
        """
        try:
            if isinstance(file_path_or_bytes, (str,)):
                return self._extract_from_path(file_path_or_bytes)
            else:
                return self._extract_from_bytes(file_path_or_bytes)
        except Exception as exc:
            logger.error("pdf_extraction_failed", error=str(exc))
            raise PDFExtractionError(f"Failed to extract text: {exc}")

    def get_page_count(self, file_path_or_bytes) -> int:
        """Return the number of pages without full extraction."""
        try:
            from pypdf import PdfReader

            if isinstance(file_path_or_bytes, bytes):
                reader = PdfReader(BytesIO(file_path_or_bytes))
            else:
                reader = PdfReader(file_path_or_bytes)
            return len(reader.pages)
        except Exception:
            return 0

    def chunk_document(self, pages: list[PageData]) -> list[ChunkData]:
        """Split extracted pages into token-aware chunks with metadata."""
        try:
            full_text = "\n\n".join(p.text for p in pages if p.text.strip())
            if not full_text.strip():
                raise ChunkingError("No text content to chunk")

            cleaned = self.clean_text(full_text)
            raw_chunks = self.splitter.split_text(cleaned)

            chunks = []
            for idx, chunk_text in enumerate(raw_chunks):
                token_count = len(self.tokenizer.encode(chunk_text))
                page_range = self._estimate_page_range(chunk_text, pages)
                chunks.append(
                    ChunkData(
                        content=chunk_text,
                        chunk_index=idx,
                        token_count=token_count,
                        metadata={
                            "token_count": token_count,
                            "char_count": len(chunk_text),
                            "page_range": page_range,
                        },
                    )
                )

            logger.info(
                "document_chunked",
                chunk_count=len(chunks),
                total_tokens=sum(c.token_count for c in chunks),
            )
            return chunks

        except ChunkingError:
            raise
        except Exception as exc:
            logger.error("chunking_failed", error=str(exc))
            raise ChunkingError(f"Failed to chunk document: {exc}")

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text))

    # ── Text Cleaning ────────────────────────────────────────────────────

    @staticmethod
    def clean_text(text: str) -> str:
        """
        Comprehensive text cleaning:
        - Normalize unicode
        - Remove control characters
        - Fix encoding artifacts
        - Collapse whitespace
        - Remove headers/footers patterns
        """
        # Unicode normalization
        text = unicodedata.normalize("NFKD", text)

        # Remove control characters (keep newlines and tabs)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

        # Fix common PDF extraction artifacts
        text = text.replace("\xad", "-")       # soft hyphen
        text = text.replace("\u2022", "- ")    # bullet
        text = text.replace("\u2013", "-")     # en dash
        text = text.replace("\u2014", " - ")   # em dash
        text = text.replace("\u201c", '"')     # smart quotes
        text = text.replace("\u201d", '"')
        text = text.replace("\u2018", "'")
        text = text.replace("\u2019", "'")

        # Remove repeated page numbers/headers (common pattern)
        text = re.sub(r"\n\s*\d+\s*\n", "\n", text)

        # Collapse multiple blank lines into two
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Collapse multiple spaces
        text = re.sub(r"[ \t]{2,}", " ", text)

        # Strip leading/trailing whitespace per line
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)

        return text.strip()

    # ── Private Helpers ──────────────────────────────────────────────────

    def _extract_from_path(self, file_path: str) -> list[PageData]:
        from pdfplumber import open as pdf_open

        pages = []
        with pdf_open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                is_ocr = False

                if len(text.strip()) < self.MIN_PAGE_CHARS:
                    ocr_text = self._ocr_page_from_path(file_path, i)
                    if ocr_text and len(ocr_text.strip()) > len(text.strip()):
                        text = ocr_text
                        is_ocr = True

                pages.append(
                    PageData(
                        page_number=i + 1,
                        text=text,
                        char_count=len(text),
                        is_ocr=is_ocr,
                    )
                )
        return pages

    def _extract_from_bytes(self, file_bytes: bytes) -> list[PageData]:
        from pdfplumber import open as pdf_open

        pages = []
        with pdf_open(BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                is_ocr = False

                if len(text.strip()) < self.MIN_PAGE_CHARS:
                    ocr_text = self._ocr_page_from_bytes(file_bytes, i)
                    if ocr_text and len(ocr_text.strip()) > len(text.strip()):
                        text = ocr_text
                        is_ocr = True

                pages.append(
                    PageData(
                        page_number=i + 1,
                        text=text,
                        char_count=len(text),
                        is_ocr=is_ocr,
                    )
                )
        return pages

    @staticmethod
    def _ocr_page_from_path(file_path: str, page_index: int) -> Optional[str]:
        """OCR fallback for a single page."""
        try:
            from pdf2image import convert_from_path
            import pytesseract

            images = convert_from_path(
                file_path, first_page=page_index + 1, last_page=page_index + 1
            )
            if images:
                return pytesseract.image_to_string(images[0], lang="spa+eng")
        except Exception as exc:
            logger.warning("ocr_fallback_failed", page=page_index, error=str(exc))
        return None

    @staticmethod
    def _ocr_page_from_bytes(file_bytes: bytes, page_index: int) -> Optional[str]:
        """OCR fallback for a single page from bytes."""
        try:
            from pdf2image import convert_from_bytes
            import pytesseract

            images = convert_from_bytes(
                file_bytes, first_page=page_index + 1, last_page=page_index + 1
            )
            if images:
                return pytesseract.image_to_string(images[0], lang="spa+eng")
        except Exception as exc:
            logger.warning("ocr_fallback_failed", page=page_index, error=str(exc))
        return None

    @staticmethod
    def _estimate_page_range(chunk_text: str, pages: list[PageData]) -> list[int]:
        """Estimate which pages a chunk came from."""
        matched_pages = []
        # Check first 100 chars of chunk against each page
        snippet = chunk_text[:100]
        for page in pages:
            if snippet in page.text or page.text[:50] in chunk_text:
                matched_pages.append(page.page_number)
        return matched_pages if matched_pages else [1]


pdf_processor = PDFProcessor()
