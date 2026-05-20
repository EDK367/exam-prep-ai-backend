"""
Tests for SubscriptionService logic.
"""
import pytest
from datetime import datetime, timedelta

from app.core.exceptions import PlanLimitExceededError, SubscriptionExpiredError
from app.modules.billing.subscription_service import subscription_service, FREE_TIER_LIMITS
from tests.factories import UserFactory, UserSubscriptionFactory, PlanFactory

pytestmark = pytest.mark.asyncio


async def test_get_user_limits_no_subscription(db_session):
    UserFactory._meta.sqlalchemy_session = db_session
    user = UserFactory()

    limits = await subscription_service.get_user_limits(db_session, user.id)

    assert limits["plan_name"] == "Free"
    assert limits["max_tokens"] == FREE_TIER_LIMITS["max_tokens"]
    assert limits["max_uploads"] == FREE_TIER_LIMITS["max_uploads"]
    assert limits["is_active"] is True


async def test_get_user_limits_active_subscription(db_session):
    UserFactory._meta.sqlalchemy_session = db_session
    PlanFactory._meta.sqlalchemy_session = db_session
    UserSubscriptionFactory._meta.sqlalchemy_session = db_session

    user = UserFactory()
    plan = PlanFactory(name="Pro", max_uploads=100)
    sub = UserSubscriptionFactory(user=user, plan=plan)

    limits = await subscription_service.get_user_limits(db_session, user.id)

    assert limits["plan_name"] == "Pro"
    assert limits["max_uploads"] == 100
    assert limits["is_active"] is True


async def test_get_user_limits_expired_subscription(db_session):
    UserFactory._meta.sqlalchemy_session = db_session
    PlanFactory._meta.sqlalchemy_session = db_session
    UserSubscriptionFactory._meta.sqlalchemy_session = db_session

    user = UserFactory()
    plan = PlanFactory(name="Pro")
    sub = UserSubscriptionFactory(
        user=user,
        plan=plan,
        expires_at=datetime.utcnow() - timedelta(days=1)
    )

    limits = await subscription_service.get_user_limits(db_session, user.id)

    # Should fall back to free tier limits
    assert limits["plan_name"] == "Free (Expired)"
    assert limits["max_uploads"] == FREE_TIER_LIMITS["max_uploads"]
    assert limits["is_active"] is False


async def test_check_upload_limit_exceeded(db_session):
    UserFactory._meta.sqlalchemy_session = db_session
    user = UserFactory()

    # User is on free tier, limit is max_uploads
    max_uploads = FREE_TIER_LIMITS["max_uploads"]

    # Should succeed at limit - 1
    await subscription_service.check_upload_limit(db_session, user.id, max_uploads - 1)

    # Should raise at limit
    with pytest.raises(PlanLimitExceededError) as exc:
        await subscription_service.check_upload_limit(db_session, user.id, max_uploads)
    
    assert "uploads" in str(exc.value)


async def test_require_active_subscription(db_session):
    UserFactory._meta.sqlalchemy_session = db_session
    PlanFactory._meta.sqlalchemy_session = db_session
    UserSubscriptionFactory._meta.sqlalchemy_session = db_session

    user = UserFactory()
    plan = PlanFactory()
    # Expired sub
    UserSubscriptionFactory(
        user=user,
        plan=plan,
        expires_at=datetime.utcnow() - timedelta(days=1)
    )

    with pytest.raises(SubscriptionExpiredError):
        await subscription_service.require_active_subscription(db_session, user.id)
