# cogs/spy/orders.py — posisi player di antrian order book (admin-only).
from __future__ import annotations

import asyncio
import logging
import unicodedata

import discord
from discord.ext import commands

import market as mkt
from core.formatters import fmt_compact
from core.utils import make_embed
from services.spy.api_client import get_user_lite
from services.spy.search import find_player_exact
from services.spy.utils import not_found_msg

log = logging.getLogger("WarEraBot.spy")

ORDERS_FETCH_LIMIT = 100
ORDERS_FETCH_TIMEOUT = 15
CONCURRENCY = 8
MAX_ROWS_DISPLAY = 30
MAX_DESC_CHARS = 3500


def _w(s: str) -> int:
    """Lebar tampilan monospace. Emoji = 2, VS/combining = 0."""
    total = 0
    for ch in s:
        cp = ord(ch)
        if ch in ("\ufe0e", "\ufe0f"):
            continue
        if unicodedata.combining(ch):
            continue
        if 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF:
            total += 2
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 2
        else:
            total += 1
    return total


class OrdersMixin:
    """Mixin — expects ApiMixin di final class (self._session)."""

    async def _fetch_top_orders(self, api_key: str) -> tuple[dict | None, str | None]:
        url = f"{mkt.ORDERS_URL}?input={mkt._encode({'itemCode': api_key, 'limit': ORDERS_FETCH_LIMIT})}"
        try:
            resp = await mkt._get_json_with_retry(
                self._session, url, headers=mkt.HEADERS, timeout=ORDERS_FETCH_TIMEOUT
            )
            data = resp["result"]["data"]
            if not isinstance(data, dict):
                reason = f"shape respons tak terduga ({type(data).__name__})"
                log.warning(f"spy_order({api_key}): {reason}")
                return None, reason
            return data, None
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            log.error(f"spy_order({api_key}): {reason}")
            return None, reason

    @staticmethod
    def _price_of(order: dict) -> float:
        try:
            return float(order.get("price", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    async def _spy_order_impl(self, ctx: commands.Context, args: str) -> None:
        tokens = (args or "").split()
        side = "sell"
        if tokens and tokens[-1].lower() in ("buy", "sell"):
            side = tokens[-1].lower()
            tokens = tokens[:-1]
        if len(tokens) < 2:
            await ctx.send("⚠️ Usage: `xspy order <username> <item> [buy|sell]`")
            return

        # username = semua token kecuali terakhir; item = token terakhir.
        item_name = tokens[-1]
        username_query = " ".join(tokens[:-1])

        async with ctx.typing():
            user_data, suggestions = await find_player_exact(self._session, username_query)
            if not user_data:
                await ctx.send("⚠️ " + not_found_msg("Player", username_query, suggestions, md=True))
                return
            target_id = user_data["_id"]
            target_name = user_data.get("username", username_query)

            # Resolver item: satu source of truth dengan market/prices.py.
            item_id = mkt._resolve_item_id(item_name)
            api_key = mkt._api_key_from_item_id(item_id) if item_id else None
            if api_key is None:
                await ctx.send(f"⚠️ Item `{item_name}` tidak dikenal.")
                return

            data, err = await self._fetch_top_orders(api_key)
            if data is None:
                await ctx.send(f"❌ Gagal fetch order book `{item_name}` ({err}) — coba lagi.")
                return

            raw = data.get("buyOrders" if side == "buy" else "sellOrders") or []
            if not isinstance(raw, list) or not raw:
                await ctx.send(f"ℹ️ Tidak ada {side} orders untuk `{item_name}`.")
                return

            queue = [o for o in raw if isinstance(o, dict) and o.get("user")]

            # Scan: cari target pertama di harga P, lanjut sampai target
            # TERAKHIR yang masih di harga P. Stop saat harga berubah.
            found_at: int | None = None
            target_price: float | None = None
            last_target_at: int | None = None

            for i, o in enumerate(queue):
                p = self._price_of(o)
                if found_at is None:
                    if o["user"] == target_id:
                        found_at = i
                        target_price = p
                        last_target_at = i
                else:
                    if p != target_price:
                        break
                    if o["user"] == target_id:
                        last_target_at = i

            if found_at is None:
                await ctx.send(
                    f"ℹ️ `{target_name}` not found in top {len(raw)} {side} orders `{item_name}`.\n"
                    f"Check: (1) order side (buy/sell), (2) username spelling, (3) order book limit."
                )
                return

            window = queue[: last_target_at + 1]
            target_indices = [i for i, o in enumerate(window) if o["user"] == target_id]

            sem = asyncio.Semaphore(CONCURRENCY)

            async def _uname(uid: str) -> tuple[str, str]:
                async with sem:
                    ud = await get_user_lite(self._session, uid)
                    return uid, (ud.get("username", "?") if ud else f"uid:{uid[:8]}")

            uids = list({o["user"] for o in window})
            names = dict(await asyncio.gather(*[_uname(u) for u in uids]))
            for ti in target_indices:
                names[window[ti]["user"]] = target_name

            rows: list[tuple[str, str, str, str]] = []
            run = 0
            for o in window:
                try:
                    qty = max(0, int(float(o.get("quantity", 0) or 0)))
                except (TypeError, ValueError):
                    log.warning(f"spy_order: quantity tak valid: {o.get('quantity')!r}")
                    qty = 0
                run += qty

                prefix = ""
                if o.get("mu"):
                    prefix += "⚔️"
                if o.get("country"):
                    prefix += "🏳️"
                uname = prefix + names.get(o["user"], f"uid:{o['user'][:8]}")

                rows.append((
                    uname,
                    fmt_compact(qty),
                    f"{self._price_of(o):.3f}",
                    fmt_compact(run),
                ))

            w_name = max(_w(r[0]) for r in rows)
            w_qty = max(len(r[1]) for r in rows)
            w_price = max(len(r[2]) for r in rows)
            w_cum = max(len(r[3]) for r in rows)

            def _fmt(r: tuple[str, str, str, str]) -> str:
                name, qty_s, price_s, cum_s = r
                pad = " " * (w_name - _w(name))
                return f"{name}{pad} {qty_s:>{w_qty}} {price_s:>{w_price}} {cum_s:>{w_cum}}"

            lines = [_fmt(r) for r in rows]
            for ti in target_indices:
                lines[ti] += " 📌"

        shown: list[str] = []
        used = 0
        truncated = False
        for i, ln in enumerate(lines):
            if len(shown) >= MAX_ROWS_DISPLAY or used + len(ln) + 1 > MAX_DESC_CHARS:
                truncated = True
                break
            shown.append(ln)
            used += len(ln) + 1

        if truncated:
            shown_set = set(range(len(shown)))
            missing_target = [lines[i] for i in target_indices if i not in shown_set]
            if missing_target:
                need = sum(len(x) + 1 for x in missing_target) + 4
                while shown and used + need > MAX_DESC_CHARS:
                    used -= len(shown.pop()) + 1
                shown.append("...")
                shown.extend(missing_target)

        positions = ", ".join(f"#{i + 1}" for i in target_indices)
        title = f"📋 Order book: {item_name} ({side}) — {target_name} ({positions})"
        e = make_embed(title, discord.Color.dark_grey())
        e.description = "```\n" + "\n".join(shown) + "\n```"
        footer = f"top {len(raw)} orders • window {len(window)} baris"
        if truncated:
            footer += " • sebagian dipotong"
        e.set_footer(text=footer)
        await ctx.send(embed=e)

    @commands.command(name="order", aliases=["o"])
    async def spy_order(self, ctx: commands.Context, *, args: str = "") -> None:
        """Posisi player di antrian order book. Contoh: xspy order Sulky iron sell"""
        await self._spy_order_impl(ctx, args)

    @spy_order.error
    async def _err_order(self, ctx, error):
        from core.utils import ChannelNotAllowed
        if isinstance(error, (ChannelNotAllowed, commands.CheckFailure)):
            return
        log.error(f"spy_order error: {error}", exc_info=True)
        await ctx.send("❌ An error occurred.")
