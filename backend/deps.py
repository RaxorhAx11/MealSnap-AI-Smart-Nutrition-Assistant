"""
Reusable FastAPI dependencies.

- get_current_user: JWT auth dependency. Extracts Bearer token from Authorization
  header, verifies signature and expiry, loads user from DB, returns User.
  Raises 401 if token is missing, invalid, or expired.
"""

from __future__ import annotations

import os
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User

# Must match main.py JWT config so tokens issued at login verify here.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"

MSG_UNAUTHORIZED = "Invalid or expired token"


def get_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    """
    Extract JWT from Authorization header, verify it, and return the current user.
    Use as a FastAPI dependency on protected routes.

    - Expects "Authorization: Bearer <token>".
    - Verifies signature (HS256) and expiry.
    - Loads user by sub (user id); raises 401 if user not found.

    Raises:
        HTTPException 401: Missing header, invalid/expired token, or user not found.
    """
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail=MSG_UNAUTHORIZED)

    token = authorization.strip()[7:].strip()  # "Bearer " -> token
    if not token:
        raise HTTPException(status_code=401, detail=MSG_UNAUTHORIZED)

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail=MSG_UNAUTHORIZED)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail=MSG_UNAUTHORIZED)

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail=MSG_UNAUTHORIZED)

    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail=MSG_UNAUTHORIZED)

    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=401, detail=MSG_UNAUTHORIZED)

    return user


# Use in route signatures: current_user: CurrentUser
CurrentUser = Annotated[User, Depends(get_current_user)]
