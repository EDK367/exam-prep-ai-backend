"""
Subscription repository and service.
Manages plan enforcement, expiration, and limit checking.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import SubscriptionStatus
from app.core.exceptions import (
    SubscriptionError,
    SubscriptionExpiredError,
    PlanLimitExceededError,
    NotFoundError,
)
from app.db.repository import BaseRepository
from app.modules.billing.models import Plan, UserSubscription

logger = structlog.get_logger(__name__)

# Default limits for users without a subscription (free tier)
FREE_TIER_LIMITS = {
    "max_tokens": 50000,
    "max_uploads": 5,
    "max_tests": 10,
    "max_text": 100000,
    "model": "liquid/lfm-2.5-2.6b:free",
}


class PlanRepository(BaseRepository[Plan]):
    def __init__(self):
        super().__init__(Plan)

    async def get_by_name(self, db: AsyncSession, name: str) -> Optional[Plan]:
        result = await db.execute(select(Plan).where(Plan.name == name))
        return result.scalars().first()


class SubscriptionRepository(BaseRepository[UserSubscription]):
    def __init__(self):
        super().__init__(UserSubscription)

    async def get_by_user(
        self, db: AsyncSession, user_id: UUID
    ) -> Optional[UserSubscription]:
        result = await db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
            .where(UserSubscription.user_id == user_id)
        )
        return result.scalars().first()

    async def get_active_by_user(
        self, db: AsyncSession, user_id: UUID
    ) -> Optional[UserSubscription]:
        result = await db.execute(
            select(UserSubscription)
            .options(selectinload(UserSubscription.plan))
            .where(UserSubscription.user_id == user_id)
            .where(UserSubscription.status == SubscriptionStatus.ACTIVE.value)
        )
        return result.scalars().first()


class SubscriptionService:
    """
    Service for checking and enforcing subscription limits.
    Every guarded action calls this service before proceeding.
    """

    def __init__(self):
        self.plan_repo = PlanRepository()
        self.sub_repo = SubscriptionRepository()

    async def get_user_limits(
        self, db: AsyncSession, user_id: UUID
    ) -> dict:
        """
        Get the effective limits for a user.
        Falls back to FREE_TIER_LIMITS if no active subscription.
        """
        sub = await self.sub_repo.get_active_by_user(db, user_id)

        if not sub or not sub.plan:
            return {**FREE_TIER_LIMITS, "plan_name": "FREE", "is_active": True}

        # Check expiration
        if sub.expires_at and sub.expires_at < datetime.utcnow():
            await self.sub_repo.update(
                db, sub, {"status": SubscriptionStatus.EXPIRED.value}
            )
            return {**FREE_TIER_LIMITS, "plan_name": "FREE (Expired)", "is_active": False}

        plan = sub.plan
        return {
            "max_tokens": plan.max_tokens or FREE_TIER_LIMITS["max_tokens"],
            "max_uploads": plan.max_uploads or FREE_TIER_LIMITS["max_uploads"],
            "max_tests": plan.max_test or FREE_TIER_LIMITS["max_tests"],
            "max_text": plan.max_text or FREE_TIER_LIMITS["max_text"],
            "model": plan.model or FREE_TIER_LIMITS["model"],
            "plan_name": plan.name,
            "is_active": True,
            "expires_at": sub.expires_at,
        }

    async def check_upload_limit(
        self, db: AsyncSession, user_id: UUID, current_uploads: int
    ) -> dict:
        """Check if user can upload another document."""
        limits = await self.get_user_limits(db, user_id)
        if current_uploads >= limits["max_uploads"]:
            raise PlanLimitExceededError(
                "uploads", current_uploads, limits["max_uploads"]
            )
        return limits

    async def check_test_limit(
        self, db: AsyncSession, user_id: UUID, current_tests: int
    ) -> dict:
        """Check if user can create another test."""
        limits = await self.get_user_limits(db, user_id)
        if current_tests >= limits["max_tests"]:
            raise PlanLimitExceededError(
                "tests", current_tests, limits["max_tests"]
            )
        return limits

    async def check_token_limit(
        self, db: AsyncSession, user_id: UUID, used_tokens: int
    ) -> dict:
        """Check if user is within token budget."""
        limits = await self.get_user_limits(db, user_id)
        if used_tokens >= limits["max_tokens"]:
            raise PlanLimitExceededError(
                "tokens", used_tokens, limits["max_tokens"]
            )
        return limits

    async def require_active_subscription(
        self, db: AsyncSession, user_id: UUID
    ) -> dict:
        """Require that the user has an active subscription (or free tier)."""
        limits = await self.get_user_limits(db, user_id)
        if not limits.get("is_active", True):
            raise SubscriptionExpiredError()
        return limits

    async def create_free_subscription(
        self, db: AsyncSession, user_id: UUID
    ) -> UserSubscription:
        """Create a free tier subscription for a new user."""
        free_plan = await self.plan_repo.get_by_name(db, "FREE")
        if not free_plan:
            free_plan = await self.plan_repo.get_by_name(db, "Free")
        if not free_plan:
            logger.warning("free_plan_not_found")
            return None

        sub = UserSubscription(
            user_id=user_id,
            plan_id=free_plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            starter_at=datetime.utcnow(),
        )
        return await self.sub_repo.create(db, sub)


plan_repo = PlanRepository()
subscription_repo = SubscriptionRepository()
subscription_service = SubscriptionService()
