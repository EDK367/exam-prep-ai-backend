"""
Generic async repository with common CRUD operations.
All module repositories inherit from this base.
"""
from typing import Any, Generic, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Async repository providing standard CRUD + pagination.
    Subclass and set `model` to get typed operations for free.
    """

    def __init__(self, model: Type[ModelType]):
        self.model = model

    # ── Read ─────────────────────────────────────────────────────────────

    async def get_by_id(self, db: AsyncSession, id: UUID) -> Optional[ModelType]:
        result = await db.execute(select(self.model).where(self.model.id == id))
        return result.scalars().first()

    async def get_by_id_or_raise(self, db: AsyncSession, id: UUID) -> ModelType:
        from app.core.exceptions import NotFoundError

        obj = await self.get_by_id(db, id)
        if not obj:
            raise NotFoundError(self.model.__tablename__, str(id))
        return obj

    async def get_all(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: list | None = None,
        order_by: Any = None,
    ) -> list[ModelType]:
        stmt = select(self.model)
        if filters:
            for f in filters:
                stmt = stmt.where(f)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        else:
            if hasattr(self.model, "created_at"):
                stmt = stmt.order_by(self.model.created_at.desc())
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self, db: AsyncSession, *, filters: list | None = None
    ) -> int:
        stmt = select(func.count()).select_from(self.model)
        if filters:
            for f in filters:
                stmt = stmt.where(f)
        result = await db.execute(stmt)
        return result.scalar_one()

    async def get_paginated(
        self,
        db: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: list | None = None,
        order_by: Any = None,
    ) -> dict:
        total = await self.count(db, filters=filters)
        skip = (page - 1) * page_size
        items = await self.get_all(
            db, skip=skip, limit=page_size, filters=filters, order_by=order_by
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": (skip + page_size) < total,
        }

    # ── Write ────────────────────────────────────────────────────────────

    async def create(self, db: AsyncSession, obj: ModelType) -> ModelType:
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    async def create_many(
        self, db: AsyncSession, objects: list[ModelType]
    ) -> list[ModelType]:
        db.add_all(objects)
        await db.commit()
        for obj in objects:
            await db.refresh(obj)
        return objects

    async def update(
        self, db: AsyncSession, obj: ModelType, update_data: dict
    ) -> ModelType:
        for field, value in update_data.items():
            setattr(obj, field, value)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    async def delete(self, db: AsyncSession, obj: ModelType) -> None:
        await db.delete(obj)
        await db.commit()

    async def soft_delete(self, db: AsyncSession, obj: ModelType) -> ModelType:
        """Soft delete — requires SoftDeleteMixin on the model."""
        from datetime import datetime

        return await self.update(
            db, obj, {"is_deleted": True, "deleted_at": datetime.utcnow()}
        )
