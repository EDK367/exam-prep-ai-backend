# app/core/security.py
from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import HTTPException
from app.core.config import settings
import structlog
import time

logger = structlog.get_logger(__name__)

class SupabaseJWTValidator:
    """
    Validates Supabase-issued JWTs.
    Supabase uses HS256 (HMAC-SHA256) signed with the project JWT secret.
    """

    async def validate(self, token: str) -> dict:
        try:
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=['HS256'],
                audience='authenticated',
                options={'verify_exp': True}
            )
            return payload
        except ExpiredSignatureError:
            raise HTTPException(401, 'Token expired')
        except JWTError as e:
            # Fallback for development if secret is wrong
            if settings.APP_ENV == 'development':
                logger.warning(
                    "JWT signature verification failed. Bypassing because APP_ENV=development. "
                    "Please check your SUPABASE_JWT_SECRET in .env.development!"
                )
                try:
                    payload = jwt.get_unverified_claims(token)
                    # manually check expiration just in case
                    if 'exp' in payload and payload['exp'] < time.time():
                        raise HTTPException(401, 'Token expired')
                    return payload
                except Exception as inner_e:
                    raise HTTPException(401, f'Invalid token: {inner_e}')
            
            # If not in development, raise normally
            raise HTTPException(401, f'Invalid token: {e}')
        except Exception as e:
            raise HTTPException(401, f'Unexpected error: {e}')

jwt_validator = SupabaseJWTValidator()
