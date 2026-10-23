"""Penerbitan dan verifikasi JWT HS256 untuk cookie identitas, pending, dan upgrade."""
import time

import jwt

ALGORITHM = "HS256"
SECONDS_PER_DAY = 24 * 60 * 60


class TokenService:
    def __init__(self, secret: str) -> None:
        self._secret = secret

    def _encode(self, payload: dict, ttl_seconds: int) -> str:
        now = int(time.time())
        claims = {**payload, "iat": now, "exp": now + ttl_seconds}
        return jwt.encode(claims, self._secret, algorithm=ALGORITHM)

    def _decode(self, token: str | None) -> dict | None:
        if not token:
            return None
        try:
            return jwt.decode(token, self._secret, algorithms=[ALGORITHM])
        except jwt.InvalidTokenError:
            return None

    def issue_identity(self, identity_id: str, name: str, ttl_days: int) -> str:
        payload = {"identity_id": identity_id, "identity": name}
        return self._encode(payload, ttl_days * SECONDS_PER_DAY)

    def issue_pending(self, ttl_seconds: int) -> str:
        return self._encode({"pending": True}, ttl_seconds)

    def issue_upgrade(self, identity_id: str, tier: str, ttl_seconds: int) -> str:
        payload = {"identity_id": identity_id, "upgraded": True, "tier": tier}
        return self._encode(payload, ttl_seconds)

    def read_identity(self, token: str | None) -> dict | None:
        payload = self._decode(token)
        if payload is None or payload.get("pending") or payload.get("upgraded"):
            return None
        return payload if payload.get("identity_id") else None

    def is_pending_valid(self, token: str | None) -> bool:
        payload = self._decode(token)
        return bool(payload and payload.get("pending") is True)

    def read_upgrade(self, token: str | None) -> dict | None:
        payload = self._decode(token)
        if payload is None or payload.get("upgraded") is not True:
            return None
        if not payload.get("identity_id") or not payload.get("tier"):
            return None
        return payload
