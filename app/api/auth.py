import json
import uuid
import logging
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db.session import get_db
from app.models.db_models import User as DBUser
from app.models.schemas import UserRegister, UserLogin, TokenResponse, GarminCredentials, UserResponse
from app.redis.client import get_redis_client
from app.api.deps import get_current_user, AuthenticatedUser, rate_limit
from app.garmin.tasks import poll_user_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"], dependencies=[rate_limit])


def hash_password(password: str) -> str:
    """Hashes a plain text password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against its hash using bcrypt."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    """Registers a new user, hashes their password, and saves to database."""
    # Check if user already exists
    stmt = select(DBUser).where(DBUser.email == payload.email)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered"
        )

    # Hash and save
    hashed = hash_password(payload.password)
    new_user = DBUser(email=payload.email, hashed_password=hashed)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(f"Successfully registered user: {new_user.email}")
    return new_user


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    """Validates user credentials and issues a session token cached in Redis for 24h."""
    # Lookup user
    stmt = select(DBUser).where(DBUser.email == payload.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Generate session token
    token = uuid.uuid4().hex
    session_key = f"session:{token}"
    
    # Store session data in Redis (UUID and email) to bypass DB lookups in deps
    redis = await get_redis_client()
    session_data = json.dumps({
        "id": str(user.id),
        "email": user.email
    })
    
    # Cache for 24 hours (86400 seconds)
    await redis.set(session_key, session_data, ex=86400)
    logger.info(f"User {user.email} logged in. Session cached in Redis.")

    return TokenResponse(access_token=token)


@router.post("/garmin", status_code=status.HTTP_200_OK)
async def store_garmin_credentials(
    credentials: GarminCredentials,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """Encrypts and stores Garmin credentials, then triggers an immediate poll."""
    # 1. AES Encrypt password
    try:
        encrypted_password = settings.encrypt_value(credentials.password)
    except Exception as e:
        logger.error(f"Failed to encrypt Garmin credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cryptographic encryption failure"
        )

    # 2. Update user record in Database
    stmt = select(DBUser).where(DBUser.id == uuid.UUID(current_user.id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    user.garmin_username = credentials.username
    user.garmin_password_encrypted = encrypted_password
    await db.commit()

    # 3. Trigger an immediate poll via Celery so the user sees data right away,
    # rather than waiting for the next scheduled beat tick.
    poll_user_task.delay(str(user.id), credentials.username, encrypted_password)

    logger.info(f"Stored Garmin credentials & queued initial poll for user ID: {current_user.id}")
    return {"status": "success", "message": "Garmin credentials updated and initial poll queued."}


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    authorization: str = Header(..., description="Bearer token"),
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """Logs the user out by deleting their Redis session. Garmin polling continues in the background."""
    token = authorization.split(" ")[1]
    redis = await get_redis_client()

    # Delete session from Redis
    await redis.delete(f"session:{token}")

    logger.info(f"Logged out user ID: {current_user.id}")
    return {"status": "success", "message": "Logged out."}
