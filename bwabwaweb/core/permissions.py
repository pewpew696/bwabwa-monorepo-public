# core/permissions.py
"""
Hierarki akses terpusat:
  4 OWNER        - OWNER_ID
  3 BOT_ADMIN    - tabel bot_admins + OWNER
  2 SERVER_ADMIN - Discord guild_permissions.administrator
  1 VERIFIED     - role dari tabel verified_roles (per guild)
  0 NONE
"""

from __future__ import annotations

import asyncio
import logging
import os

from services.db import pool as db_pool

log = logging.getLogger("WarEraBot.permissions")

LEVEL_NONE         = 0
LEVEL_VERIFIED     = 1
LEVEL_SERVER_ADMIN = 2
LEVEL_BOT_ADMIN    = 3
LEVEL_OWNER        = 4

OWNER_ID: int = int(os.environ.get("OWNER_ID", "0"))


async def is_bot_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    try:
        res = await asyncio.to_thread(
            lambda: (
                db_pool.table("bot_admins")
                .select("user_id")
                .eq("user_id", str(user_id))
                .execute()
            )
        )
        return bool(res)
    except Exception as exc:
        log.error(f"is_bot_admin: {exc}")
        return False


def is_server_admin(member) -> bool:
    try:
        return bool(member.guild_permissions.administrator)
    except Exception:
        return False


async def has_verified_role(member) -> bool:
    """Cek role member di tabel verified_roles (per guild)."""
    try:
        if member is None or member.guild is None:
            return False
        res = await asyncio.to_thread(
            lambda: (
                db_pool.table("verified_roles")
                .select("role_id")
                .eq("guild_id", str(member.guild.id))
                .execute()
            )
        )
        if not res:
            return False
        verified_ids = {str(r["role_id"]) for r in res}
        member_role_ids = {str(r.id) for r in member.roles}
        return bool(verified_ids & member_role_ids)
    except Exception as exc:
        log.error(f"has_verified_role: {exc}")
        return False


async def get_level(member) -> int:
    """Return level akses (0-4) untuk Discord member."""
    if member is None:
        return LEVEL_NONE
    uid = getattr(member, "id", 0)
    if uid == OWNER_ID:
        return LEVEL_OWNER
    if await is_bot_admin(uid):
        return LEVEL_BOT_ADMIN
    if is_server_admin(member):
        return LEVEL_SERVER_ADMIN
    if await has_verified_role(member):
        return LEVEL_VERIFIED
    return LEVEL_NONE
