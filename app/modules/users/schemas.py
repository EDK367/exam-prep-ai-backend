from pydantic import BaseModel, EmailStr, UUID4, ConfigDict
from typing import Optional
from datetime import datetime

class UserTypeResponse(BaseModel):
    id: UUID4
    name: str

    model_config = ConfigDict(from_attributes=True)

class PlanSummaryResponse(BaseModel):
    id: UUID4
    name: str
    max_tokens: Optional[int] = None
    max_test: Optional[int] = None
    max_uploads: Optional[int] = None
    model: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class SubscriptionSummaryResponse(BaseModel):
    id: UUID4
    status: Optional[str] = None
    expires_at: Optional[datetime] = None
    plan: Optional[PlanSummaryResponse] = None

    model_config = ConfigDict(from_attributes=True)

class UserBase(BaseModel):
    name: Optional[str] = None
    last_names: Optional[str] = None
    email: EmailStr
    avatar_url: Optional[str] = None
    is_active: bool = True

class UserCreate(UserBase):
    supabase_id: str

class UserUpdate(BaseModel):
    name: Optional[str] = None
    last_names: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: Optional[bool] = None
    type_user_id: Optional[UUID4] = None

class UserResponse(UserBase):
    id: UUID4
    supabase_id: str
    type_user_id: Optional[UUID4] = None
    subscription: Optional[SubscriptionSummaryResponse] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
