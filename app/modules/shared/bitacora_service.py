"""
Bitacora (AI usage log) repository and service.
Tracks token consumption, costs, and request status per user.
"""
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BitacoraStatus
from app.db.repository import BaseRepository
from app.modules.shared.models import Bitacora

logger = structlog.get_logger(__name__)


class BitacoraRepository(BaseRepository[Bitacora]):
    def __init__(self):
        super().__init__(Bitacora)

    async def get_by_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        return await self.get_paginated(
            db,
            page=page,
            page_size=page_size,
            filters=[Bitacora.user_id == user_id],
        )

    async def get_usage_since(
        self, db: AsyncSession, user_id: UUID, since: datetime
    ) -> dict:
        """Get aggregated usage since a given date."""
        result = await db.execute(
            select(
                func.coalesce(func.sum(Bitacora.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(Bitacora.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(Bitacora.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(Bitacora.estimated_cost), 0.0).label("total_cost"),
                func.count(Bitacora.id).label("request_count"),
            )
            .where(Bitacora.user_id == user_id)
            .where(Bitacora.created_at >= since)
            .where(Bitacora.status == BitacoraStatus.SUCCESS.value)
        )
        row = result.one()
        return {
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "total_tokens": row.total_tokens,
            "total_cost": float(row.total_cost),
            "request_count": row.request_count,
        }

    async def get_monthly_usage(
        self, db: AsyncSession, user_id: UUID
    ) -> dict:
        """Get usage for the current calendar month."""
        now = datetime.utcnow()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return await self.get_usage_since(db, user_id, start_of_month)

    async def get_daily_usage(
        self, db: AsyncSession, user_id: UUID
    ) -> dict:
        """Get usage for the current calendar day (UTC)."""
        now = datetime.utcnow()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.get_usage_since(db, user_id, start_of_day)


class BitacoraService:
    """Service for logging and querying AI usage."""

    def __init__(self):
        self.repo = BitacoraRepository()

    async def log_usage(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        estimated_cost: float,
        model: str,
        status: BitacoraStatus = BitacoraStatus.SUCCESS,
        request_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Bitacora:
        """Log an AI usage entry."""
        entry = Bitacora(
            user_id=user_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost,
            status=status.value,
            model=model,
            request_type=request_type,
            error_message=error_message,
        )
        entry = await self.repo.create(db, entry)

        logger.info(
            "ai_usage_logged",
            user_id=str(user_id),
            tokens=total_tokens,
            cost=estimated_cost,
            model=model,
            status=status.value,
        )
        return entry

    async def log_from_ai_response(
        self,
        db: AsyncSession,
        user_id: UUID,
        ai_response,
        *,
        request_type: Optional[str] = None,
    ) -> Bitacora:
        """Log usage from an AIResponse object."""
        return await self.log_usage(
            db,
            user_id,
            input_tokens=ai_response.input_tokens,
            output_tokens=ai_response.output_tokens,
            total_tokens=ai_response.total_tokens,
            estimated_cost=ai_response.estimated_cost,
            model=ai_response.model,
            request_type=request_type,
        )

    async def log_failure(
        self,
        db: AsyncSession,
        user_id: UUID,
        *,
        model: str,
        error_message: str,
        request_type: Optional[str] = None,
    ) -> Bitacora:
        """Log a failed AI request."""
        return await self.log_usage(
            db,
            user_id,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
            model=model,
            status=BitacoraStatus.FAILED,
            request_type=request_type,
            error_message=error_message,
        )

    async def get_monthly_usage(
        self, db: AsyncSession, user_id: UUID
    ) -> dict:
        return await self.repo.get_monthly_usage(db, user_id)

    async def get_daily_usage(
        self, db: AsyncSession, user_id: UUID
    ) -> dict:
        return await self.repo.get_daily_usage(db, user_id)

    async def check_token_budget(
        self, db: AsyncSession, user_id: UUID, max_tokens: int
    ) -> dict:
        """Check if user is within token budget. Returns usage info."""
        usage = await self.repo.get_monthly_usage(db, user_id)
        remaining = max(0, max_tokens - usage["total_tokens"])
        return {
            **usage,
            "max_tokens": max_tokens,
            "remaining_tokens": remaining,
            "is_within_budget": usage["total_tokens"] < max_tokens,
        }


bitacora_repo = BitacoraRepository()
bitacora_service = BitacoraService()
