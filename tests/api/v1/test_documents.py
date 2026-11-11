"""
Integration tests for document endpoints.
"""
import pytest
from unittest.mock import patch

from app.core.enums import DocumentStatus
from tests.factories import UserFactory, DocumentFactory

pytestmark = pytest.mark.asyncio


async def test_list_documents(client, db_session):
    UserFactory._meta.sqlalchemy_session = db_session
    DocumentFactory._meta.sqlalchemy_session = db_session

    user = UserFactory()
    doc1 = DocumentFactory(user=user, filename="doc1.pdf")
    doc2 = DocumentFactory(user=user, filename="doc2.pdf")
    
    # Mock the current user dependency
    from app.api.deps import get_current_user
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: user

    response = await client.get("/api/v1/documents/")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    filenames = [item["filename"] for item in data["items"]]
    assert "doc1.pdf" in filenames
    assert "doc2.pdf" in filenames
    
    app.dependency_overrides.clear()


@patch("app.api.v1.documents.process_document.delay")
async def test_upload_document(mock_celery_delay, client, db_session):
    mock_celery_delay.return_value.id = "mock-task-id-123"
    UserFactory._meta.sqlalchemy_session = db_session
    user = UserFactory()
    
    from app.api.deps import get_current_user
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: user

    # Create dummy PDF bytes (valid magic bytes)
    pdf_content = b"%PDF-1.4 dummy content"
    files = {"file": ("test.pdf", pdf_content, "application/pdf")}

    response = await client.post("/api/v1/documents/upload", files=files)
    
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "test.pdf"
    assert data["status"] == DocumentStatus.UPLOADED.value
    assert data["size_types"] == len(pdf_content)
    
    # Verify celery task was dispatched
    mock_celery_delay.assert_called_once()
    
    app.dependency_overrides.clear()


async def test_get_document_not_found(client, db_session):
    UserFactory._meta.sqlalchemy_session = db_session
    user = UserFactory()
    
    from app.api.deps import get_current_user
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: user

    import uuid
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/documents/{fake_id}")
    
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "NOT_FOUND"
    
    app.dependency_overrides.clear()
