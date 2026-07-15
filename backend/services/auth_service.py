"""User auth — bcrypt hashing + PyJWT (HS256) tokens. No new deps."""
import os
import logging
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("auth_service")

SECRET = os.environ.get("AI_TEAM_HUB_JWT_SECRET") or os.environ.get("AI_TEAM_HUB_API_KEY") or "dev-insecure-jwt-secret"
# ponytail: 7-day token, no refresh. Add refresh when session length matters.
TOKEN_TTL = timedelta(days=7)
ALGO = "HS256"


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def create_token(user_id: str, workspace_id: str) -> str:
    payload = {
        "sub": user_id,
        "ws": workspace_id,
        "exp": datetime.now(timezone.utc) + TOKEN_TTL,
    }
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGO])
    except Exception:
        return None
