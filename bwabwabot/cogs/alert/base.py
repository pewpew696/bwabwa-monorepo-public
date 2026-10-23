"""
cogs/alerts/base.py  —  Konstanta, formatter, dan mixin dasar Alerts cog.

Sama seperti cogs/economy/base.py: `AlertsBase` TIDAK mewarisi
`commands.Cog` sendiri. Semua file cmd_*.py / poll_*.py di package ini
meng-inherit-nya untuk akses state & helper bersama. discord.py tetap
menemukan semua command/group di seluruh MRO selama class akhir
(`AlertsCog` di `__init__.py`) mewarisi `commands.Cog`.
"""

from __future__ import annotations
from services.db import pool as db_pool

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord.ext import commands

log = logging.getLogger("WarEraBot.alerts")

# --- CONSTANTS ---

POLL_INTERVAL_MIN         = 5
GROUND_ALERT_THRESHOLD    = 220    # ground point > 220 → trigger ground alert
ALERT_AUTO_DELETE_SECONDS = 43200  # 12 jam — khusus notifikasi battle/order/ground otomatis

BONUS_POLL_INTERVAL_MIN   = 15     # Type 3 lebih berat (country+region+party fetch), polling lebih jarang
BONUS_ALERT_EPSILON       = 0.001  # toleransi (persen) — anggap SERI kalau selisih ≤ ini (noise pembulatan)
BONUS_BREAKDOWN_TOP_N     = 50     # ambil top-N negara per resource (cukup buat cari posisi negara lama)

STORAGE_POLL_INTERVAL_MIN   = 15     # sama alasan bonus: fetch banyak company per user, jangan kesering
STORAGE_ALERT_THRESHOLD_PCT = 80.0
STORAGE_CAPACITY_BY_LEVEL   = {1: 200, 2: 400, 3: 600, 4: 800, 5: 1000, 6: 1200, 7: 1400}

ORDERBOOK_POLL_INTERVAL_MIN   = 15    # sama alasan bonus/storage: scan banyak item, jangan kesering
ORDERBOOK_ALERT_RATIO         = 2.0   # default: qty top-3 bid vs top-3 ask >= 2x -> trigger (2 arah)
ORDERBOOK_ALERT_COOLDOWN_H    = 5     # cooldown alert (jam) kalau arah sama; arah berbalik -> langsung alert
ORDERBOOK_DEPTH_LEVELS        = 3     # jumlah level harga terbaik per sisi yang digabung


# --- SHARED FORMAT / RESOLVE HELPERS ---
# fmt_k: duplikat dihapus, redirect ke canonical (netral, bukan spy lagi).
from core.formatters import fmt_compact as _fmt_k
def _utc_str(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y %H:%M UTC")
    except Exception:
        return str(iso)[:16]


def _fmt_pct_id(v: float) -> str:
    """Format percent, 2 decimal places."""
    return f"{v:.2f}"


def _resolve_resource(query: str) -> tuple[str, str] | None:
    """Resolve nama/alias resource jadi (item_id, item_label). None kalau tidak ketemu.
    Delegasi ke market._resolve_item_id (satu implementasi matching terpusat)."""
    import market as mkt
    iid = mkt._resolve_item_id(query)
    if iid is None:
        return None
    return iid, mkt.ITEM_LABELS[iid]


def _bounty_str(b) -> str:
    try:
        if b and float(b) > 0:
            return f"{float(b):.2f} gold/1K dmg"
    except Exception:
        pass
    return "None"


def _resolve_id_list(
    id_list: list,
    country_cache: dict,
    mu_cache: dict,
    direct_id: str = "",
    label_direct: bool = True,
) -> list[str]:
    """Terima list of ID string, kembalikan list nama yang sudah di-resolve (tanpa limit)."""
    names = []
    for raw_id in id_list:
        if not isinstance(raw_id, str):
            continue
        name = country_cache.get(raw_id) or mu_cache.get(raw_id) or (raw_id[:8] + "...")
        if label_direct and raw_id == direct_id:
            name += " *(fighting)*"
        names.append(name)
    return names


def _wrap_line(names: list[str], icon: str) -> str:
    """Gabung nama jadi 1 baris horizontal dipisah spasi. Daftar lengkap, tidak dipotong."""
    if not names:
        return "   —"
    return f"   " + " ".join(f"{icon} {name}" for name in names)


def _orders_field(
    country_orders: list,
    country_cache: dict,
    mu_cache: dict,
    direct_country_id: str = "",
) -> str:
    """
    Bangun teks field: daftar LENGKAP negara yang pasang order untuk satu sisi
    (attacker atau defender). Daftar MU tidak lagi ditampilkan.
    """
    country_names = _resolve_id_list(
        country_orders, country_cache, mu_cache,
        direct_id=direct_country_id, label_direct=True
    )
    if not country_names:
        return "   —"
    return _wrap_line(country_names, "🏳️")


# --- BASE MIXIN — state & helper bersama ---

class AlertsBase:
    """Mixin dasar: state (cache in-memory), shortcut ke bot, helper Supabase,
    dan helper data-fetch yang dipakai bersama oleh poll_war / poll_bonus /
    seluruh command `xalert ...`.

    Tidak mewarisi `commands.Cog` — hanya `AlertsCog` (di `__init__.py`) yang
    melakukannya, dengan menggabungkan mixin ini bersama semua mixin lainnya.
    """

    bot: commands.Bot

    def __init__(self, bot: commands.Bot) -> None:
        self.bot             = bot
        self._country_cache: dict[str, str] = {}
        self._mu_cache:      dict[str, str] = {}
        self._war_alerted:   set[str]       = set()   # battle_id yang sudah di-alert Type 1
        self._order_alerted: set[str]       = set()   # "battle_id:raw_id" sudah di-alert Type 2
        self._ground_alerted: set[str]      = set()   # round_id yang sudah di-alert Ground Alert
        self._bonus_cache: dict[str, tuple[str, float]] = {}  # item_id -> (negara_top, pct) Type 3
        self._orderbook_cache: dict[tuple[str, str, float], tuple[str, float, datetime]] = {}
        # (item_id, ratio_threshold) -> (direction, ratio) Type 4 — key gabungan
        # supaya guild dgn threshold beda utk item yg sama tidak berbagi baseline
        self._storage_watchlist: dict[str, int] = {}           # warera_user_id -> discord_user_id
        self._storage_state: dict[str, dict[str, float]] = {}  # warera_user_id -> {company_name: storage_pct}

    @property
    def _session(self):
        return self.bot._session

    # --- lifecycle ---

    async def cog_load(self) -> None:
        await self._load_cache_from_db()
        await self._refresh_country_cache()
        self.poll_wars.start()
        self.poll_bonus.start()
        self.poll_orderbook.start()
        self.poll_storage.start()
        log.info("AlertsCog loaded.")

    async def cog_unload(self) -> None:
        self.poll_wars.cancel()
        self.poll_bonus.cancel()
        self.poll_orderbook.cancel()
        self.poll_storage.cancel()

    # --- notif auto-delete ---

    async def _queue_alert_delete(self, message: discord.Message) -> None:
        """Jadwalkan hapus notifikasi alert otomatis 12 jam dari sekarang,
        disimpan di Supabase (bukan delete_after bawaan discord.py) supaya
        tetap kesusul kehapus walau bot sempat restart."""
        try:
            delete_at = (
                datetime.now(timezone.utc) + timedelta(seconds=ALERT_AUTO_DELETE_SECONDS)
            ).isoformat()
            await asyncio.to_thread(
                lambda: db_pool.table("auto_delete_queue").insert({
                    "channel_id": str(message.channel.id),
                    "message_id": str(message.id),
                    "delete_at": delete_at,
                }).execute()
            )
        except Exception as exc:
            log.warning(f"_queue_alert_delete: {exc}")

    # --- Data fetchers ---

    async def _refresh_country_cache(self, force_refresh: bool = False) -> None:
        """Isi self._country_cache (id -> nama) dari sumber cache BERSAMA di
        market.py (get_country_list), bukan fetch COUNTRIES_URL sendiri lagi.
        Ini dipanggil dari 2 tempat dengan niat beda:
        - cog_load (bot baru nyala): force_refresh=False, pakai cache 1 bulan
          yang mungkin masih valid (lintas restart, lewat Supabase).
        - command `xalert refresh` (manual): force_refresh=True, paksa fetch
          API baru sekarang juga, sesuai maksud command itu."""
        import market as mkt
        try:
            countries = await mkt.get_country_list(
                self._session, with_cache=True, force_refresh=force_refresh
            )
            self._country_cache = {c["_id"]: c["name"] for c in countries if c.get("_id")}
            log.info(f"Country cache: {len(self._country_cache)} entries.")
        except Exception as exc:
            log.error(f"_refresh_country_cache: {exc}")

    async def _fetch_regions_object(self) -> dict:
        """Satu-satunya sumber data untuk Type 1 dan Type 2."""
        import market as mkt
        try:
            resp = await mkt._get_json_with_retry(self._session, mkt.REGIONS_URL, headers=mkt.HEADERS, timeout=30)
            return resp["result"]["data"] or {}
        except Exception as exc:
            log.error(f"_fetch_regions_object: {type(exc).__name__}: {exc!r}")
            return {}

    # --- Supabase cache ---

    async def _load_cache_from_db(self) -> None:
        try:
            res = await asyncio.to_thread(
                lambda: db_pool.table("war_alert_cache").select("war_id").execute()
            )
            self._war_alerted = {r["war_id"] for r in (res or [])}
            res2 = await asyncio.to_thread(
                lambda: db_pool.table("order_alert_cache").select("war_id,target_id").execute()
            )
            self._order_alerted = {
                f"{r['war_id']}:{r['target_id']}" for r in (res2 or [])
            }
            res3 = await asyncio.to_thread(
                lambda: db_pool.table("ground_alert_cache").select("round_id").execute()
            )
            self._ground_alerted = {r["round_id"] for r in (res3 or [])}
            res4 = await asyncio.to_thread(
                lambda: db_pool.table("bonus_alert_cache").select("item_id,country_name,pct").execute()
            )
            self._bonus_cache = {
                r["item_id"]: (r["country_name"], float(r["pct"])) for r in (res4 or [])
            }
            res5 = await asyncio.to_thread(
                lambda: db_pool.table("storage_watchlist").select("warera_user_id,discord_user_id").execute()
            )
            self._storage_watchlist = {r["warera_user_id"]: int(r["discord_user_id"]) for r in (res5 or [])}
            res6 = await asyncio.to_thread(
                lambda: db_pool.table("storage_alert_state").select("warera_user_id,companies").execute()
            )
            self._storage_state = {r["warera_user_id"]: (r["companies"] or {}) for r in (res6 or [])}
            res7 = await asyncio.to_thread(
                lambda: db_pool.table("orderbook_alert_cache")
                .select("guild_id,item_id,ratio_threshold,direction,ratio,updated_at").execute()
            )
            self._orderbook_cache = {
                (str(r["guild_id"]), r["item_id"], float(r["ratio_threshold"])): (r["direction"], float(r["ratio"]), self._parse_pg_ts(r.get("updated_at")))
                for r in (res7 or [])
            }
            log.info(
                f"Cache loaded: {len(self._war_alerted)} wars, "
                f"{len(self._order_alerted)} orders, "
                f"{len(self._ground_alerted)} ground alerts, "
                f"{len(self._bonus_cache)} bonus records, "
                f"{len(self._orderbook_cache)} orderbook records."
            )
        except Exception as exc:
            log.warning(f"_load_cache_from_db: {exc}")

    async def _mark_war_alerted(self, battle_id: str) -> None:
        self._war_alerted.add(battle_id)
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("war_alert_cache").upsert({"war_id": battle_id}, on_conflict="war_id").execute()
            )
        except Exception as exc:
            log.warning(f"_mark_war_alerted: {exc}")

    async def _mark_ground_alerted(self, round_id: str, battle_id: str) -> None:
        self._ground_alerted.add(round_id)
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("ground_alert_cache").upsert({
                    "round_id": round_id, "battle_id": battle_id
                }, on_conflict="round_id").execute()
            )
        except Exception as exc:
            log.warning(f"_mark_ground_alerted: {exc}")

    async def _set_bonus_cache(self, item_id: str, country: str, pct: float) -> None:
        self._bonus_cache[item_id] = (country, pct)
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("bonus_alert_cache").upsert({
                    "item_id": item_id, "country_name": country, "pct": pct,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="item_id").execute()
            )
        except Exception as exc:
            log.warning(f"_set_bonus_cache: {exc}")

    @staticmethod
    def _parse_pg_ts(v) -> datetime:
        """Parse timestamptz dari PostgREST (pecahan detik bisa 1-6 digit). Gagal -> epoch (cooldown dianggap habis)."""
        import re
        try:
            s = str(v).replace("Z", "+00:00").replace(" ", "T")
            m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(.*)$", s)
            if not m:
                raise ValueError(s)
            head, frac, tz = m.groups()
            frac = (frac or "0")[:6].ljust(6, "0")
            tz = tz or "+00:00"
            if re.fullmatch(r"[+-]\d{2}", tz):
                tz += ":00"
            dt = datetime.fromisoformat(f"{head}.{frac}{tz}")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return datetime.fromtimestamp(0, timezone.utc)

    async def _set_orderbook_cache(
        self, guild_id: str, item_id: str, ratio_threshold: float, direction: str, ratio: float
    ) -> None:
        self._orderbook_cache[(str(guild_id), item_id, ratio_threshold)] = (
            direction, ratio, datetime.now(timezone.utc),
        )
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("orderbook_alert_cache").upsert({
                    "guild_id": str(guild_id), "item_id": item_id, "ratio_threshold": ratio_threshold,
                    "direction": direction, "ratio": ratio,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="guild_id,item_id,ratio_threshold").execute()
            )
        except Exception as exc:
            log.warning(f"_set_orderbook_cache: {exc}")

    async def _add_storage_watch(self, warera_user_id: str, discord_user_id: int) -> None:
        self._storage_watchlist[warera_user_id] = discord_user_id
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("storage_watchlist").upsert({
                    "warera_user_id": warera_user_id, "discord_user_id": str(discord_user_id),
                }, on_conflict="warera_user_id").execute()
            )
        except Exception as exc:
            log.warning(f"_add_storage_watch: {exc}")

    async def _remove_storage_watch(self, warera_user_id: str) -> bool:
        existed = self._storage_watchlist.pop(warera_user_id, None) is not None
        if existed:
            try:
                await asyncio.to_thread(
                    lambda: db_pool.table("storage_watchlist").delete().eq("warera_user_id", warera_user_id).execute()
                )
            except Exception as exc:
                log.warning(f"_remove_storage_watch: {exc}")
        return existed

    async def _set_storage_state(self, warera_user_id: str, companies_pct: dict) -> None:
        self._storage_state[warera_user_id] = companies_pct
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("storage_alert_state").upsert({
                    "warera_user_id": warera_user_id, "companies": companies_pct,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="warera_user_id").execute()
            )
        except Exception as exc:
            log.warning(f"_set_storage_state: {exc}")

    async def _mark_order_alerted(self, battle_id: str, raw_id: str) -> None:
        key = f"{battle_id}:{raw_id}"
        self._order_alerted.add(key)
        try:
            await asyncio.to_thread(
                lambda: db_pool.table("order_alert_cache").upsert({
                    "war_id": battle_id, "target_id": raw_id
                }, on_conflict="id").execute()
            )
        except Exception as exc:
            log.warning(f"_mark_order_alerted: {exc}")

    async def _get_configs(self, alert_type: int) -> list[dict]:
        try:
            res = await asyncio.to_thread(
                lambda: (
                    db_pool.table("alert_configs")
                    .select("*")
                    .eq("alert_type", alert_type)
                    .execute()
                )
            )
            return res or []
        except Exception as exc:
            log.error(f"_get_configs({alert_type}): {exc}")
            return []

    async def _resolve_mu_names_batch(self, mu_ids: list[str]) -> None:
        """Fetch dan cache nama MU yang belum ada di _mu_cache.

        Versi BATCH: maks 50 MU per request (1 batch = 1 kuota WarEra, diuji
        20 Sept 2026 di bucket tanpa key). Kalau gagal, cache diisi placeholder
        id[:8]... (embed tetap aman) dan ID dicatat di _mu_failed supaya dicoba
        lagi di siklus poll berikutnya, bukan menetap sampai restart."""
        import market as mkt
        if not hasattr(self, "_mu_failed"):
            self._mu_failed = set()
        unique = list(dict.fromkeys(
            mid for mid in mu_ids if mid not in self._mu_cache or mid in self._mu_failed
        ))
        if not unique:
            return
        ok = fail = reqs = 0
        for start in range(0, len(unique), 50):
            chunk = unique[start:start + 50]
            results = None
            try:
                reqs += 1
                methods = ",".join(["mu.getById"] * len(chunk))
                inputs = {str(i): {"muId": mid} for i, mid in enumerate(chunk)}
                url = f"{mkt.BASE_URL}/{methods}?batch=1&input={mkt._encode(inputs)}"
                results = await mkt._get_json_with_retry(
                    self._session, url, headers=mkt.HEADERS, timeout=30
                )
            except Exception as exc:
                log.warning(f"_resolve_mu_names_batch: batch {len(chunk)} MU gagal: {type(exc).__name__}: {exc!r}")
            if not isinstance(results, list):
                results = []
            for i, mid in enumerate(chunk):
                res = results[i] if i < len(results) else None
                data = res.get("result", {}).get("data") if isinstance(res, dict) else None
                if isinstance(data, dict) and data:
                    self._mu_cache[mid] = data.get("name", mid[:8] + "...")
                    self._mu_failed.discard(mid)
                    ok += 1
                else:
                    self._mu_cache[mid] = mid[:8] + "..."
                    self._mu_failed.add(mid)
                    fail += 1
        log.info(f"_resolve_mu_names_batch: {ok} ok, {fail} gagal dari {len(unique)} MU ({reqs} request)")

    # --- flow interaktif "xalert add war/order" (dipakai 2 command) ---

    async def _interactive_add(
        self, ctx: commands.Context, alert_type: int, target_name: str
    ) -> None:
        import market as mkt
        async with ctx.typing():
            target_id     = None
            resolved_type = None

            result = await mkt.fetch_country_id_by_name(self._session, target_name, with_cache=True)
            if result:
                target_id, target_name = result
                resolved_type = "country"

            if not target_id:
                url = f"{mkt.BASE_URL}/search.searchAnything?input={mkt._encode({'searchText': target_name})}"
                try:
                    resp   = await mkt._get_json_with_retry(self._session, url, headers=mkt.HEADERS, timeout=10)
                    mu_ids = resp["result"]["data"].get("muIds", [])
                    if mu_ids:
                        target_id     = mu_ids[0]
                        resolved_type = "mu"
                        url2 = f"{mkt.BASE_URL}/mu.getById?input={mkt._encode({'muId': target_id})}"
                        resp2 = await mkt._get_json_with_retry(self._session, url2, headers=mkt.HEADERS, timeout=10)
                        target_name = resp2["result"]["data"].get("name", target_name)
                        self._mu_cache[target_id] = target_name
                except Exception as exc:
                    log.warning(f"_interactive_add MU: {type(exc).__name__}: {exc!r}")

        if not target_id:
            await ctx.send(f"⚠️ `{target_name}` not found as a country or MU.")
            return

        type_label = "War Alert" if alert_type == 1 else "Order Alert"
        await ctx.send(
            f"✅ Target: **{target_name}** ({resolved_type})\n"
            f"📌 Type the **#channel** for this **{type_label}**:"
        )

        def check(m: discord.Message) -> bool:
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timeout.")
            return

        channel = None
        if msg.channel_mentions:
            channel = msg.channel_mentions[0]
        else:
            name    = msg.content.strip().lstrip("#")
            channel = discord.utils.get(ctx.guild.text_channels, name=name)

        if not channel:
            await ctx.send("⚠️ Channel not found.")
            return

        await ctx.send("🔔 Type **@role** to ping, or type `skip`:")
        try:
            msg2 = await self.bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            msg2 = None

        role_ping = None
        if msg2 and msg2.content.strip().lower() != "skip" and msg2.role_mentions:
            role_ping = ",".join(str(r.id) for r in msg2.role_mentions)

        try:
            await asyncio.to_thread(
                lambda: db_pool.table("alert_configs").insert({
                    "guild_id":    str(ctx.guild.id),
                    "alert_type":  alert_type,
                    "target_type": resolved_type,
                    "target_id":   target_id,
                    "target_name": target_name,
                    "channel_id":  str(channel.id),
                    "role_ping":   role_ping,
                }).execute()
            )
        except Exception as exc:
            log.error(f"alert_add save: {exc}")
            await ctx.send("❌ Failed to save.")
            return

        e = discord.Embed(title="✅ Alert Saved", color=discord.Color.green())
        e.add_field(name="Type",       value=type_label,      inline=True)
        e.add_field(name="Target",     value=target_name,     inline=True)
        e.add_field(name="Channel",    value=channel.mention, inline=True)
        e.add_field(
            name="Role Ping",
            value=" ".join(f"<@&{rid}>" for rid in role_ping.split(",") if rid) if role_ping else "—",
            inline=True,
        )
        e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
        await ctx.send(embed=e)
