"""Wspólna instancja Limitera slowapi dla całej aplikacji."""
from __future__ import annotations

from fastapi import Request
from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.security import decode_access_token


def rate_limit_key(request: Request) -> str:
    """
    Klucz rate-limitu = user_id (jeśli zalogowany), inaczej IP.
    Dzięki temu limit per-user trzyma się nawet przy zmiennym NAT.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = decode_access_token(auth_header[7:])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except JWTError:
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=rate_limit_key)
