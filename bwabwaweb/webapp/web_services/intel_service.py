"""Logika Intel: daftar pengguna aktif webapp. Tanpa fastapi."""
from dataclasses import dataclass

ACTIVE_WINDOW_MINUTES = 15


@dataclass(frozen=True)
class ActiveUsers:
    window_minutes: int
    users: list[dict]


class IntelService:
    def __init__(self, intel_queries) -> None:
        self._intel = intel_queries

    def get_active_users(self) -> ActiveUsers:
        users = self._intel.get_active_users(ACTIVE_WINDOW_MINUTES)
        return ActiveUsers(window_minutes=ACTIVE_WINDOW_MINUTES, users=users)
