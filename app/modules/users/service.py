from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate
from app.modules.users.repository import user_repo

class UserService:
    async def sync_from_supabase(self, db: AsyncSession, payload: dict) -> User:
        """
        Synchronize a user from Supabase JWT payload.
        If the user does not exist, it will be created.
        If it exists, you could potentially update it if data changed.
        """
        supabase_id = payload.get('sub')
        email = payload.get('email')
        
        # Depending on auth provider (e.g., Google), metadata might be here
        user_metadata = payload.get('user_metadata', {})
        name = user_metadata.get('full_name') or user_metadata.get('name') or ''
        avatar_url = user_metadata.get('avatar_url')
        
        # Check if user exists by supabase_id
        user = await user_repo.get_by_supabase_id(db, supabase_id)
        
        if not user:
            # Check by email in case of manual link
            user = await user_repo.get_by_email(db, email)
            if user:
                # Update existing user with supabase_id
                user = await user_repo.update(db, user, UserUpdate(supabase_id=supabase_id))
            else:
                # Create new user
                user_in = UserCreate(
                    email=email,
                    supabase_id=supabase_id,
                    name=name,
                    avatar_url=avatar_url
                )
                user = await user_repo.create(db, user_in)
                
                # Optional: Here you could trigger creation of a free plan subscription
                
        return user

user_service = UserService()
