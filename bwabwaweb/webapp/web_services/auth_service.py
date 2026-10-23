"""Logika autentikasi: password, identitas perangkat, upgrade tier. Tanpa fastapi."""
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from webapp.core.errors import (
    ConflictError,
    InvalidPasswordError,
    UnauthorizedError,
    ValidationAppError,
)
from webapp.core.settings import PENDING_TTL_SECONDS, UPGRADE_TTL_SECONDS, Settings
from webapp.web_services.token_service import TokenService

NAME_MAX_LENGTH = 24
LAST_SEEN_INTERVAL_SECONDS = 300
TIER_BASIC = "basic"
TIER_PRO = "pro"


@dataclass(frozen=True)
class LoginResult:
    needs_name: bool
    pending_token: str | None


@dataclass(frozen=True)
class SessionInfo:
    identity_id: str
    identity: str
    tier: str | None

    @property
    def is_upgraded(self) -> bool:
        return self.tier is not None


def _normalize_password(raw_password: str) -> str:
    return raw_password.strip().upper()


def _is_match(candidate: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(candidate.encode(), expected.encode())


def _is_last_seen_stale(last_seen_at: datetime | None) -> bool:
    if last_seen_at is None:
        return True
    age = datetime.now(timezone.utc) - last_seen_at
    return age.total_seconds() > LAST_SEEN_INTERVAL_SECONDS


class AuthService:
    def __init__(self, settings: Settings, tokens: TokenService, identity_store) -> None:
        self._settings = settings
        self._tokens = tokens
        self._identities = identity_store

    def _require_password(self, raw_password: str) -> str:
        normalized = _normalize_password(raw_password or "")
        if not normalized:
            raise ValidationAppError("password kosong")
        return normalized

    def _find_identity_row(self, identity_token: str | None) -> dict | None:
        payload = self._tokens.read_identity(identity_token)
        if payload is None:
            return None
        return self._identities.get_identity(payload["identity_id"])

    def login(self, raw_password: str, identity_token: str | None) -> LoginResult:
        password = self._require_password(raw_password)
        matches = [
            _is_match(password, self._settings.auth_password_1),
            _is_match(password, self._settings.auth_password_2),
        ]
        if not any(matches):
            raise InvalidPasswordError("password login salah")
        if self._find_identity_row(identity_token) is not None:
            return LoginResult(needs_name=False, pending_token=None)
        pending_token = self._tokens.issue_pending(PENDING_TTL_SECONDS)
        return LoginResult(needs_name=True, pending_token=pending_token)

    def register_name(
        self, raw_name: str, identity_token: str | None, pending_token: str | None
    ) -> str:
        if self._find_identity_row(identity_token) is not None:
            raise ConflictError("perangkat sudah punya identitas")
        if not self._tokens.is_pending_valid(pending_token):
            raise UnauthorizedError("pending tidak valid")
        name = (raw_name or "").strip()[:NAME_MAX_LENGTH]
        if not name:
            raise ValidationAppError("nama kosong")
        identity_id = str(uuid.uuid4())
        self._identities.insert_identity(identity_id, name)
        return self._tokens.issue_identity(
            identity_id, name, self._settings.identity_ttl_days
        )

    def upgrade(self, raw_password: str, identity_token: str | None) -> tuple[str, str]:
        row = self._find_identity_row(identity_token)
        if row is None:
            raise UnauthorizedError("sesi tidak ada")
        password = self._require_password(raw_password)
        if _is_match(password, self._settings.auth_password_1):
            tier = TIER_PRO
        else:
            raise InvalidPasswordError("password upgrade salah")
        token = self._tokens.issue_upgrade(row["id"], tier, UPGRADE_TTL_SECONDS)
        return token, tier

    def find_session(
        self,
        identity_token: str | None,
        upgrade_token: str | None,
        device_info: str,
        last_ip: str,
    ) -> SessionInfo | None:
        row = self._find_identity_row(identity_token)
        if row is None:
            return None
        if _is_last_seen_stale(row["last_seen_at"]):
            self._identities.touch_identity(
                row["id"], device_info, last_ip, LAST_SEEN_INTERVAL_SECONDS
            )
        upgrade = self._tokens.read_upgrade(upgrade_token)
        tier = upgrade["tier"] if upgrade and upgrade["identity_id"] == row["id"] else None
        return SessionInfo(identity_id=row["id"], identity=row["name"], tier=tier)

    def require_session(
        self,
        identity_token: str | None,
        upgrade_token: str | None,
        device_info: str,
        last_ip: str,
    ) -> SessionInfo:
        session = self.find_session(identity_token, upgrade_token, device_info, last_ip)
        if session is None:
            raise UnauthorizedError("sesi tidak valid")
        return session
