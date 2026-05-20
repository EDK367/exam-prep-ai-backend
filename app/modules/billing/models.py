from sqlalchemy import Column, String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base
from app.db.mixins import UUIDMixin, TimestampMixin

class Plan(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'plans'
    
    name = Column(String(100), nullable=False)
    max_tokens = Column(Integer)
    min_tokens = Column(Integer)
    max_text = Column(Integer)
    time_refresh = Column(Integer) # In days or hours?
    max_test = Column(Integer)
    max_uploads = Column(Integer)
    model = Column(String(100)) # e.g., 'gpt-4o'
    
    subscriptions = relationship("UserSubscription", back_populates="plan")

class UserSubscription(Base, UUIDMixin):
    __tablename__ = 'user_subscriptions'
    
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, unique=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey('plans.id'), nullable=False)
    starter_at = Column(DateTime)
    expires_at = Column(DateTime)
    status = Column(String(50)) # e.g., 'active', 'expired'
    
    user = relationship("User", back_populates="subscription")
    plan = relationship("Plan", back_populates="subscriptions")
