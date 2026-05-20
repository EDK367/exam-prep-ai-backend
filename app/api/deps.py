# app/api/deps.py — Dependency Injection
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.modules.users.models import User
from app.modules.users.repository import user_repo
from app.modules.users.service import user_service
from app.core.security import jwt_validator

bearer_scheme = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = await jwt_validator.validate(credentials.credentials)
    supabase_id = payload['sub']
    user = await user_repo.get_by_supabase_id(db, supabase_id)
    if not user:
        user = await user_service.sync_from_supabase(db, payload)
    return user

def require_role(*roles: str):
    async def check(user = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(403, 'Insufficient permissions')
        return user
    return check
