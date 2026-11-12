from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional
from app.modules.users.models import User
from app.modules.billing.models import UserSubscription
from app.modules.users.schemas import UserCreate, UserUpdate

class UserRepository:
    async def get_by_id(self, db: AsyncSession, user_id: str) -> Optional[User]:
        result = await db.execute(
            select(User)
            .options(selectinload(User.subscription).selectinload(UserSubscription.plan))
            .where(User.id == user_id)
        )
        return result.scalars().first()

    async def get_by_supabase_id(self, db: AsyncSession, supabase_id: str) -> Optional[User]:
        result = await db.execute(
            select(User)
            .options(selectinload(User.subscription).selectinload(UserSubscription.plan))
            .where(User.supabase_id == supabase_id)
        )
        return result.scalars().first()

    async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        result = await db.execute(
            select(User)
            .options(selectinload(User.subscription).selectinload(UserSubscription.plan))
            .where(User.email == email)
        )
        return result.scalars().first()

    async def create(self, db: AsyncSession, obj_in: UserCreate) -> User:
        db_obj = User(
            email=obj_in.email,
            name=obj_in.name,
            last_names=obj_in.last_names,
            avatar_url=obj_in.avatar_url,
            supabase_id=obj_in.supabase_id,
            is_active=obj_in.is_active
        )
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update(self, db: AsyncSession, db_obj: User, obj_in: UserUpdate) -> User:
        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

user_repo = UserRepository()
