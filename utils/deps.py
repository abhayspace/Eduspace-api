"""FastAPI dependencies for authentication and authorization."""
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database import get_client
from utils.security import decode_access_token, decode_access_token_ignore_expiry

bearer_scheme = HTTPBearer(auto_error=False)

_USER_COLUMNS = "id,email,full_name,role,school_id,admission_no,user_code,is_active,gender"


async def get_user_by_token(token: str) -> dict:
    """Decode a JWT and load the corresponding active user from storage."""
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    client = get_client()
    res = (
        await client.table("users")
        .select(_USER_COLUMNS)
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    user = res.data[0]
    if not user.get("is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is inactive")
    return user


async def current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing authentication token")
    try:
        return await get_user_by_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


async def current_user_allow_expired(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Like current_user but accepts expired tokens (for refresh only)."""
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing authentication token")
    try:
        payload = decode_access_token_ignore_expiry(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    client = get_client()
    res = (
        await client.table("users")
        .select(_USER_COLUMNS)
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    user = res.data[0]
    if not user.get("is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is inactive")
    return user


def require_roles(*roles: str):
    """Dependency factory enforcing that the user has one of ``roles``.

    ``super_admin`` always passes.
    """

    async def _dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles and user["role"] != "super_admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return _dep
