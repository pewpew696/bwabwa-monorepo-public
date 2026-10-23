"""
cogs/alerts/cmd_storage.py — xalert watch/unwatch <nama_atau_user_id> (Type 4, DM personal)

2026-09-17: WAJIB lolos verifikasi sebelum disimpan.
- Input 24-hex  -> dianggap User ID -> probe user.getUserById langsung.
- Input lainnya -> dianggap nama -> resolve via spy cog (_search_user_ids +
  _get_user_lite, mekanisme yang sama dengan xspy player) -> dapat Mongo ID.
Yang tersimpan SELALU Mongo ID (anti-rename; getUserById cast _id ke ObjectId
di server — username mentah pasti 500 "Cast to ObjectId failed", terbukti via curl).
"""
from __future__ import annotations

import re

from aiohttp import ClientResponseError
from discord.ext import commands

from .base import AlertsBase
from services.spy.search import find_player_exact
from .cmd_root import cmd_alert

_ID_RE = re.compile(r"\A[0-9a-f]{24}\Z", re.IGNORECASE)

_MSG_NOT_ID = (
    "❌ `{input}` tidak dikenal.\n"
    "Coba **username in-game** (contoh `Example_Player`) atau **User ID WarEra** "
    "(24 karakter, contoh `6a05f65f65ae5994efe28a6f`)."
)
_MSG_NOT_FOUND = (
    "⚠️ Player `{input}` tidak ketemu. Cek ejaan, atau pakai User ID dari URL profil."
)
_MSG_API_DOWN = "⚠️ API WarEra lagi bermasalah/timeout, verifikasi gagal. Coba 1-2 menit lagi."
_MSG_UNKNOWN_ID = "❌ ID `{input}` tidak dikenal oleh API WarEra — cek ulang ID-nya."


def _normalize(raw: str) -> str:
    # strip bracket literal (user menirukan <warera_user_id> dari help), quote, @
    return raw.strip().strip("<>").strip().strip('"').lstrip("@").strip()


class StorageWatchCommands(AlertsBase):
    async def _probe_user(self, wid: str) -> tuple[bool, str, dict]:
        """Probe getUserById. Return (ok, reason, data) — data dipakai buat display username."""
        import market as mkt
        url = f"{mkt.BASE_URL}/user.getUserById?input={mkt._encode({'userId': wid})}"
        try:
            resp = await mkt._get_json_with_retry(
                self._session, url, headers=mkt.HEADERS, timeout=15
            )
        except ClientResponseError as e:
            if getattr(e, "status", None) == 404:
                return False, "unknown_id", {}
            return False, "api_down", {}
        except Exception:
            return False, "api_down", {}
        data = (resp or {}).get("result", {}).get("data") or {}
        if not data:
            return False, "unknown_id", {}   # ID well-formed tapi tidak exist
        return True, "", data

    async def _resolve_name_to_id(self, nama: str) -> tuple[str, str, str, list]:
        """Nama -> Mongo ID via spy cog (duck-typing, tanpa hardcode nama cog).
        Return (status, wid, uname, candidates)."""
        spy = next(
            (c for c in self.bot.cogs.values()
             if hasattr(c, "_search_user_ids") and hasattr(c, "_get_user_lite")),
            None,
        )
        if spy is None:
            return "no_spy", "", "", []
        try:
            data, suggestions = await find_player_exact(spy._session, nama)
        except Exception:
            return "api_down", "", "", []
        if data:
            uname = data.get("username", "?")
            return "ok", data["_id"], uname, [(data["_id"], uname)]
        if suggestions:
            return "ambiguous", "", "", [("", n) for n in suggestions]
        return "not_found", "", "", []

    async def _finalize_add(self, ctx: commands.Context, wid: str, uname: str) -> None:
        ok, reason, data = await self._probe_user(wid)
        if not ok:
            await ctx.send(_MSG_UNKNOWN_ID.format(input=wid) if reason == "unknown_id" else _MSG_API_DOWN)
            return
        display = uname or data.get("username") or wid
        await self._add_storage_watch(wid, ctx.author.id)
        await ctx.send(
            f"✅ Terverifikasi: **{display}** (`{wid}`) — DM alert saat storage company >= 80%."
        )

    @cmd_alert.command(name="watch")
    async def alert_watch(self, ctx: commands.Context, warera_user_id: str) -> None:
        """xalert watch <username_atau_user_id> — DM alert saat storage company >=80%"""
        wid = _normalize(warera_user_id)
        if not wid:
            await ctx.send(_MSG_NOT_ID.format(input=warera_user_id))
            return
        if _ID_RE.fullmatch(wid):
            await self._finalize_add(ctx, wid, "")
            return
        status, rid, uname, cands = await self._resolve_name_to_id(wid)
        if status in ("no_spy", "api_down"):
            await ctx.send(_MSG_API_DOWN)
            return
        if status == "not_found":
            await ctx.send(_MSG_NOT_FOUND.format(input=wid))
            return
        if status == "ambiguous":
            lines = [f"• **{n}**" for _, n in cands]
            await ctx.send(
                "🔍 Tidak ada nama yang persis sama — tulis ulang nama lengkap salah satu:\n"
                + "\n".join(lines)
            )
            return
        await self._finalize_add(ctx, rid, uname)

    @cmd_alert.command(name="unwatch")
    async def alert_unwatch(self, ctx: commands.Context, warera_user_id: str) -> None:
        """xalert unwatch <username_atau_user_id> — berhenti dapat alert"""
        wid = _normalize(warera_user_id)
        if _ID_RE.fullmatch(wid):
            target, uname = wid, ""
        else:
            status, rid, uname, _ = await self._resolve_name_to_id(wid)
            if status != "ok":
                await ctx.send(_MSG_NOT_FOUND.format(input=wid))
                return
            target = rid
        removed = await self._remove_storage_watch(target)
        if removed:
            await ctx.send(f"🗑️ Storage alert for **{uname or target}** (`{target}`) stopped.")
        else:
            await ctx.send("That account isn't on your watchlist.")
