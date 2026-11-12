"""
Billing & subscription API endpoints.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.modules.billing.subscription_service import subscription_service, plan_repo, subscription_repo
from app.modules.billing.models import UserSubscription, Plan
from app.core.enums import SubscriptionStatus
from app.modules.shared.bitacora_service import bitacora_service
from app.modules.users.models import User

router = APIRouter()


@router.get("/plan")
async def get_current_plan(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's plan and limits."""
    limits = await subscription_service.get_user_limits(db, current_user.id)
    return {"success": True, "data": limits}


@router.get("/usage")
async def get_usage_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed usage statistics for the current billing period."""
    limits = await subscription_service.get_user_limits(db, current_user.id)
    usage = await bitacora_service.get_monthly_usage(db, current_user.id)
    daily_usage = await bitacora_service.get_daily_usage(db, current_user.id)

    from app.modules.documents.repository import document_repo
    from app.modules.tests.repository import test_repo

    upload_count = await document_repo.count_by_user(db, current_user.id)
    test_count = await test_repo.count_by_user(db, current_user.id)

    return {
        "success": True,
        "data": {
            "plan": limits["plan_name"],
            "tokens": {
                "used": usage["total_tokens"],
                "max": limits["max_tokens"],
                "remaining": max(0, limits["max_tokens"] - usage["total_tokens"]),
                "today": daily_usage["total_tokens"],
            },
            "uploads": {
                "used": upload_count,
                "max": limits["max_uploads"],
                "remaining": max(0, limits["max_uploads"] - upload_count),
            },
            "tests": {
                "used": test_count,
                "max": limits["max_tests"],
                "remaining": max(0, limits["max_tests"] - test_count),
            },
            "cost": {
                "total": usage["total_cost"],
                "request_count": usage["request_count"],
            },
        },
    }

@router.get("/plans")
async def get_all_plans(db: AsyncSession = Depends(get_db)):
    """Get all available plans."""
    from sqlalchemy import select
    from app.modules.billing.models import Plan
    result = await db.execute(select(Plan).order_by(Plan.max_tokens))
    plans = result.scalars().all()
    if not plans:
        # Create default plans if they don't exist
        default_plans = [
            Plan(name="FREE", max_tokens=50000, max_uploads=5, max_test=10, max_text=100000, model="liquid/lfm-2.5-2.6b:free"),
            Plan(name="PLUS", max_tokens=250000, max_uploads=50, max_test=50, max_text=500000, model="liquid/lfm-2.5-2.6b:free"),
            Plan(name="PRO", max_tokens=500000, max_uploads=100, max_test=100, max_text=1000000, model="liquid/lfm-2.5-2.6b:free")
        ]
        db.add_all(default_plans)
        await db.commit()
        for p in default_plans:
            await db.refresh(p)
        plans = default_plans

    return {"success": True, "data": plans}

@router.post("/plan/{plan_name}")
async def change_plan(
    plan_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change user's plan and persist directly to the database."""
    from sqlalchemy import select, func
    
    clean_name = plan_name.strip()
    result = await db.execute(select(Plan).where(func.lower(Plan.name) == clean_name.lower()))
    plan = result.scalars().first()
    
    is_free = clean_name.lower() == "free"
    if not plan:
        plan = Plan(
            name=clean_name.upper(),
            max_tokens=50000 if is_free else 500000,
            max_uploads=5 if is_free else 100,
            max_test=10 if is_free else 100,
            max_text=100000 if is_free else 1000000,
            model="liquid/lfm-2.5-2.6b:free",
        )
        db.add(plan)
        await db.commit()
        await db.refresh(plan)

    sub = await subscription_repo.get_by_user(db, current_user.id)
    if sub:
        await subscription_repo.update(db, sub, {
            "plan_id": plan.id,
            "status": SubscriptionStatus.ACTIVE.value,
            "starter_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=30),
        })
    else:
        new_sub = UserSubscription(
            user_id=current_user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE.value,
            starter_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db.add(new_sub)
        await db.commit()

    limits = await subscription_service.get_user_limits(db, current_user.id)
    return {
        "success": True,
        "message": f"Plan actualizado exitosamente a {plan.name}",
        "data": limits,
    }
