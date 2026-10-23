# services/spy/avatar.py — download avatar WarEra ke file lokal (diekstrak 28 Sep 2026)

from __future__ import annotations

import logging

log = logging.getLogger("WarEraBot.avatar")


# --- download ---

async def download_avatar(session, avatar_url: str, save_path: str) -> str | None:
    """Download avatar_url ke save_path. Return path, atau None kalau gagal."""
    if not avatar_url:
        return None
    try:
        async with session.get(avatar_url, timeout=10) as r:
            if r.status != 200:
                return None
            content = await r.read()
        with open(save_path, "wb") as f:
            f.write(content)
        return save_path
    except Exception as exc:
        log.error(f"download_avatar: {exc}")
        return None
