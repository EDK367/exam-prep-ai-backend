from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base
from app.db.mixins import UUIDMixin, TimestampMixin

class UserType(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'user_types'
    name = Column(String(100), nullable=False, unique=True)
    
    users = relationship("User", back_populates="user_type")

class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'users'
    
    name = Column(String(255))
    last_names = Column(String(255))
    email = Column(String(255), unique=True, index=True, nullable=False)
    avatar_url = Column(String(1000))
    is_active = Column(Boolean, default=True)
    supabase_id = Column(String(255), unique=True, index=True)
    type_user_id = Column(UUID(as_uuid=True), ForeignKey('user_types.id'))
    
    # Relationships
    user_type = relationship("UserType", back_populates="users")
    subscription = relationship("UserSubscription", back_populates="user", uselist=False)
    documents = relationship("Document", back_populates="user")
    tests = relationship("Test", back_populates="user")
    bitacora_entries = relationship("Bitacora", back_populates="user")
