"""Minimal token helper for the payments service."""
from __future__ import annotations


class AuthError(Exception):
    """Raised for invalid or missing auth tokens."""


def decode_token(token: str | None) -> str:
    """Return the payload segment of a `header.payload.signature` token."""
    if token is None:
        raise AuthError("Token is None")
    return token.split(".")[1]
