from fastapi import APIRouter
from app.api.v1 import ai, documents, users, tests, billing

api_router = APIRouter(prefix='/api/v1')
api_router.include_router(ai.router, prefix='/ai', tags=['AI'])
api_router.include_router(documents.router, prefix='/documents', tags=['Documents'])
api_router.include_router(users.router, prefix='/users', tags=['Users'])
api_router.include_router(tests.router, prefix='/tests', tags=['Tests'])
api_router.include_router(billing.router, prefix='/billing', tags=['Billing'])
