"""Konfigurasi webapp dari environment. Tanpa efek samping saat import."""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

COOKIE_IDENTITY = "bwabwabwa_id"
COOKIE_PENDING = "bwabwabwa_pending"
COOKIE_UPGRADE = "bwabwabwa_upgrade"

PENDING_TTL_SECONDS = 10 * 60
UPGRADE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_IDENTITY_TTL_DAYS = 30


class SettingsError(RuntimeError):
    """Konfigurasi wajib tidak lengkap."""


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    auth_password_1: str
    auth_password_2: str
    identity_ttl_days: int
    cookie_secure: bool


def _read_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_password(name: str) -> str:
    """Sama seperti Flask lama: nilai env dinormalisasi strip + upper (input juga)."""
    return os.environ.get(name, "").strip().upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env-webapp")
    return Settings(
        jwt_secret=os.environ.get("JWT_SECRET", ""),
        auth_password_1=_read_password("AUTH_PASSWORD_1"),
        auth_password_2=_read_password("AUTH_PASSWORD_2"),
        identity_ttl_days=int(
            os.environ.get("IDENTITY_TTL_DAYS", DEFAULT_IDENTITY_TTL_DAYS)
        ),
        cookie_secure=_read_bool("COOKIE_SECURE", True),
    )


def require_auth_settings() -> Settings:
    """Validasi variabel wajib; dipanggil saat startup, bukan saat import."""
    settings = get_settings()
    required = {
        "JWT_SECRET": settings.jwt_secret,
        "AUTH_PASSWORD_1": settings.auth_password_1,
        "AUTH_PASSWORD_2": settings.auth_password_2,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SettingsError(f"Env wajib kosong: {', '.join(missing)}")
    return settings
