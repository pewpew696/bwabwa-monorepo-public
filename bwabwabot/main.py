# main.py

from __future__ import annotations

import os
import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta, time as dt_time

import aiohttp
import discord
from discord.ext import commands, tasks
from supabase import create_client, Client
from dotenv import load_dotenv


# --- config ---
# load_dotenv(override=True) wajib sebelum import market — token dibaca saat import.
load_dotenv(override=True)

from services.db import pool as db_pool  # setelah load_dotenv — local_db baca env saat import, bukan saat dipakai
from services.db.helpers import (
    db_save_prices, db_save_snapshot, db_get_history,
    db_save_volume_hourly, db_save_bonus_snapshot,
)

import market as mkt
from services.market import snapshot as msnap
from services.territory import collector as tax_collector
from services.territory import tax_store

from core.permissions import OWNER_ID
from core.utils import ChannelNotAllowed

BOT_TOKEN: str = os.environ["DISCORD_TOKEN"]
SUPABASE_STORAGE_URL: str = os.environ["SUPABASE_STORAGE_URL"]
SUPABASE_STORAGE_KEY: str = os.environ["SUPABASE_STORAGE_KEY"]

PRICE_REFRESH_MIN: int = 10
BONUS_REFRESH_MIN: int = 60
VOLUME_REFRESH_MIN: int = 60
TAX_COLLECTOR_INTERVAL_MIN: int = 3
WAGE_EVENTS_RETENTION_DAYS: int = 30


# Guard: start_sync_scheduler() cuma sekali (on_ready bisa re-fire saat reconnect).
_sync_scheduler_started: bool = False

# --- auto-delete ---
COMMAND_AUTO_DELETE_SECONDS: int = 1800   # 30 menit — default delay OUTPUT bot (ctx.send)

COMMAND_MESSAGE_DELETE_SECONDS: int = 60  # 1 menit

# --- logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("WarEraBot")

# --- supabase storage (guide-images) ---
supabase_storage: Client = create_client(SUPABASE_STORAGE_URL, SUPABASE_STORAGE_KEY)


_last_applied_ts = None


async def apply_market_snapshot(snap: dict) -> bool:
    global _last_applied_ts
    if _last_applied_ts is not None and snap["ts"] <= _last_applied_ts:
        return False
    _last_applied_ts = snap["ts"]
    _price_cache.update(snap["prices"])
    for item, price in snap["prices"].items():
        _price_history[item].append((snap["ts"], price))
    await db_save_snapshot(snap, _volume_cache)
    return True


async def restore_price_history(hours: int = 24) -> int:
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = await asyncio.to_thread(
            lambda: (
                db_pool.table("price_history")
                .select("item_name, price, recorded_at")
                .gte("recorded_at", cutoff)
                .order("recorded_at", desc=False)
                .limit(20000)
                .execute()
            )
        )
    except Exception as exc:
        log.error(f"restore_price_history: {exc}")
        return 0
    per_item: dict[str, list] = defaultdict(list)
    for r in rows or []:
        try:
            ts = datetime.fromisoformat(str(r["recorded_at"])).astimezone(timezone.utc)
            price = float(r["price"])
        except (KeyError, TypeError, ValueError):
            continue
        per_item[r["item_name"]].append((ts, price))
    restored = 0
    for item, pts in per_item.items():
        if _price_history.get(item):
            continue
        _price_history[item].extend(pts)   # deque maxlen 144 -> yang terbaru tersisa
        restored += min(len(pts), 144)
    log.info(f"restore_price_history: {restored} titik untuk {len(per_item)} item")
    return restored


# Queue di DB (bukan asyncio.sleep) — jadwal hapus tetap walau bot restart.

async def queue_auto_delete(channel_id: int, message_id: int, delete_after_seconds: int) -> None:
    """Jadwalkan sebuah pesan untuk dihapus `delete_after_seconds` dari sekarang."""
    try:
        delete_at = (
            datetime.now(timezone.utc) + timedelta(seconds=delete_after_seconds)
        ).isoformat()
        await asyncio.to_thread(
            lambda: db_pool.table("auto_delete_queue").insert({
                "channel_id": str(channel_id),
                "message_id": str(message_id),
                "delete_at": delete_at,
            }).execute()
        )
    except Exception as exc:
        log.error(f"queue_auto_delete: {exc}")


async def process_auto_delete_queue() -> None:
    """Cek Supabase, hapus semua pesan yang jadwal hapusnya sudah lewat."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        res = await asyncio.to_thread(
            lambda: (
                db_pool.table("auto_delete_queue")
                .select("*")
                .lte("delete_at", now)
                .limit(200)
                .execute()
            )
        )
        rows = res or []
    except Exception as exc:
        log.error(f"process_auto_delete_queue (select): {exc}")
        return

    for row in rows:
        try:
            channel = bot.get_channel(int(row["channel_id"]))
            if channel is None:
                channel = await bot.fetch_channel(int(row["channel_id"]))
            msg = await channel.fetch_message(int(row["message_id"]))
            await msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        except Exception as exc:
            log.warning(f"process_auto_delete_queue (delete): {exc}")
        finally:
            try:
                await asyncio.to_thread(
                    lambda: db_pool.table("auto_delete_queue").delete().eq("id", row["id"]).execute()
                )
            except Exception as exc:
                log.error(f"process_auto_delete_queue (cleanup row): {exc}")


# --- global state ---
_price_cache: dict[str, float] = {}
_price_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=144))
_auto_bonus_cache: dict[str, float] = {}
_median_bonus_cache: dict[str, float] = {}
_bonus_breakdown: dict[str, list] = {}
_bonus_deposit_ends: dict[str, dict] = {}
_country_tax_cache: dict[str, float] = {}
_volume_cache: dict[str, dict] = {}
_manual_overrides: dict[str, dict] = {}
_username_cache: dict[str, str] = {}
_session: aiohttp.ClientSession | None = None

# --- bot ---

def _prefix(_bot: commands.Bot, message: discord.Message) -> list[str]:
    return commands.when_mentioned_or("x", "X")(_bot, message)


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix=_prefix,
    intents=intents,
    help_command=None,
    case_insensitive=True,
)


@bot.check
async def _block_dm(ctx: commands.Context) -> bool:
    """Bot cuma boleh dipakai di server (guild), bukan DM — tolak diam-diam
    (lihat on_command_error: NoPrivateMessage tidak dibalas apa-apa)."""
    if ctx.guild is None:
        raise commands.NoPrivateMessage()
    return True


@bot.check
async def _restrict_channels(ctx: commands.Context) -> bool:
    """Allowlist per-guild (cogs/channels.py). Command 'channel'/'ch' selalu
    exempt supaya admin gak kejebak gak bisa benerin allowlist."""
    if ctx.command and ctx.command.qualified_name.split()[0] in {"channel", "ch"}:
        return True
    allowed = getattr(bot, "_allowed_channels", {}).get(str(ctx.guild.id)) if ctx.guild else None
    if allowed and ctx.channel.id not in allowed:
        raise ChannelNotAllowed()
    return True

# Patch ctx.send global: jadwalkan hapus via queue Supabase.
_original_ctx_send = commands.Context.send
_NO_OVERRIDE = object()


async def _auto_delete_send(self: commands.Context, *args, delete_after=_NO_OVERRIDE, **kwargs):
    seconds = COMMAND_AUTO_DELETE_SECONDS if delete_after is _NO_OVERRIDE else delete_after
    # delete_after tidak diteruskan ke discord.py — pakai queue DB.
    msg = await _original_ctx_send(self, *args, **kwargs)
    if seconds:
        await queue_auto_delete(msg.channel.id, msg.id, seconds)
    return msg


commands.Context.send = _auto_delete_send  # type: ignore[assignment]


@bot.event
async def on_command_completion(ctx: commands.Context) -> None:
    """Jadwalkan hapus command message yang diketik user, 30 menit setelah
    dieksekusi. xannounce dikecualikan karena sudah menghapus message-nya
    sendiri secara instan di cogs/admin.py."""
    if ctx.command and ctx.command.qualified_name in ("announce",):
        return
    await queue_auto_delete(ctx.message.channel.id, ctx.message.id, COMMAND_MESSAGE_DELETE_SECONDS)

# --- background tasks ---

async def _fetch_volume_safe(session, allow_fallback: bool = False) -> dict[str, dict]:
    """Volume 24h via batch (market.fetch_volume_24h_batched). Kalau hasil kosong
    atau semua tx == 0 (batch gagal total): periodik -> {} supaya cache lama TIDAK
    ditimpa; boot (allow_fallback=True) -> jatuh sekali ke fetch_volume_24h lama."""
    try:
        volume = await mkt.fetch_volume_24h_batched(session)
    except Exception as exc:
        log.warning(f"fetch_volume_24h_batched exception: {exc!r}")
        volume = {}
    if volume and any(v.get("tx", 0) > 0 for v in volume.values()):
        return volume
    log.warning("fetch_volume_24h_batched: hasil kosong / semua nol")
    if allow_fallback:
        log.info("Volume: fallback ke fetch_volume_24h (versi lama)")
        return await mkt.fetch_volume_24h(session)
    return {}


@tasks.loop(minutes=PRICE_REFRESH_MIN)
async def refresh_prices() -> None:
    global _price_cache
    if _session is None:
        return
    try:
        snap = await msnap.get_market_snapshot(_session, force=True)
        if not snap:
            return
        if await apply_market_snapshot(snap):
            log.info(f"Prices updated: {len(snap['prices'])} items")
    except Exception:
        log.exception("refresh_prices: galat tak terduga (loop tetap jalan)")


@tasks.loop(minutes=BONUS_REFRESH_MIN)
async def refresh_bonuses() -> None:
    global _auto_bonus_cache, _median_bonus_cache, _bonus_breakdown, _country_tax_cache
    if _session is None:
        return
    # FR-18: fetch raw_data sekali, dipakai bareng median & max bonus.
    raw_data = await mkt.get_bonus_raw_data(_session, with_cache=True)
    _countries_by_id = {c["_id"]: c for c in raw_data[0] if c.get("_id")}
    _party_ids = list({c.get("rulingParty") for c in _countries_by_id.values() if c.get("rulingParty")})
    parties_by_id = await mkt._fetch_parties_batch(_session, _party_ids)

    bonuses = await mkt.fetch_max_bonuses(_session, raw_data=raw_data, parties_by_id=parties_by_id)
    if bonuses:
        _auto_bonus_cache.clear()
        _auto_bonus_cache.update(bonuses)
        log.info(f"Production bonus updated: {len(bonuses)} items")

    median_bonuses = await mkt.fetch_median_bonuses(_session, raw_data=raw_data, parties_by_id=parties_by_id)
    if median_bonuses:
        _median_bonus_cache.clear()
        _median_bonus_cache.update(median_bonuses)
        log.info(f"Median production bonus updated: {len(median_bonuses)} items")

    breakdown = await mkt.fetch_bonus_breakdown(_session, top_n=5, raw_data=raw_data, parties_by_id=parties_by_id)
    if breakdown:
        _bonus_breakdown.clear()
        _bonus_breakdown.update(breakdown)
        log.info(f"Bonus breakdown updated: {len(breakdown)} items")
        _bonus_deposit_ends.clear()
        _bonus_deposit_ends.update(
            await mkt.fetch_bonus_deposit_ends(_session, breakdown, raw_data=raw_data, parties_by_id=parties_by_id)
        )

    # Tax cuma di-fetch untuk negara yang muncul di breakdown.
    tax = await mkt.fetch_country_tax_breakdown(_session, _bonus_breakdown, with_cache=True)
    if tax:
        _country_tax_cache.clear()
        _country_tax_cache.update(tax)
        log.info(f"Country income tax updated: {len(tax)} countries")

    # snapshot ke DB (webapp baca dari sini, bukan memori bot)
    await db_save_bonus_snapshot(_bonus_breakdown, _bonus_deposit_ends, _country_tax_cache)


@tasks.loop(minutes=VOLUME_REFRESH_MIN)
async def refresh_volume() -> None:
    global _volume_cache
    if _session is None:
        return
    volume = await _fetch_volume_safe(_session)
    if volume:
        _volume_cache.clear()
        _volume_cache.update(volume)
        log.info(f"Volume 24h updated: {len(volume)} items")
        await db_save_volume_hourly(volume)


@tasks.loop(minutes=TAX_COLLECTOR_INTERVAL_MIN)
async def refresh_territory_tax() -> None:
    if _session is None:
        return
    try:
        count = await tax_collector.run_collector_once(_session)
        if count:
            log.info(f"Territory tax collector: {count} wage event diproses")
    except Exception as exc:
        log.error(f"refresh_territory_tax: gagal ({exc!r})", exc_info=True)
@tasks.loop(time=dt_time(hour=3, minute=30, tzinfo=timezone.utc))
async def purge_old_wage_events() -> None:
    """Jalan harian jam 03:30 UTC. Dump baris territory_wage_events yg lebih
    tua dari WAGE_EVENTS_RETENTION_DAYS ke data_exports/*.csv.gz, lalu hapus
    dari tabel (satu transaksi, konsisten)."""
    try:
        ok, deleted = await asyncio.to_thread(
            tax_store.purge_old_wage_events, WAGE_EVENTS_RETENTION_DAYS
        )
        if ok and deleted:
            log.info(f"purge_old_wage_events: {deleted} baris lama dihapus (dump tersimpan).")
        elif not ok:
            log.error("purge_old_wage_events: gagal, cek log territory_tax_store.")
    except Exception as exc:
        log.error(f"purge_old_wage_events: gagal ({exc!r})", exc_info=True)




@tasks.loop(minutes=1)
async def auto_delete_worker() -> None:
    """Jalan tiap 1 menit, hapus semua pesan di queue yang sudah waktunya.
    Juga langsung jalan begitu bot startup, jadi kalau bot sempat restart,
    pesan yang ketinggalan tetap kesusul dihapus."""
    await process_auto_delete_queue()


@refresh_prices.before_loop
@refresh_bonuses.before_loop
@refresh_volume.before_loop
@refresh_territory_tax.before_loop
@auto_delete_worker.before_loop
async def _before_loops() -> None:
    await bot.wait_until_ready()

# --- events ---

_bot_initialized: bool = False


@bot.event
async def on_ready() -> None:
    """on_ready dipanggil ULANG tiap reconnect — guard _bot_initialized tetap
    dipakai. Initial data load TIDAK menunggu di sini: cogs di-load duluan
    supaya bot bisa dipakai dalam hitungan detik, data market dimuat sebagai
    background task (_initial_data_load), periodic loop start setelahnya."""
    global _session, _bot_initialized
    log.info(f"✅ Bot online: {bot.user}")
    if _bot_initialized:
        log.info("on_ready re-fired (reconnect) — skip re-init, state lama tetap dipakai.")
        return
    _bot_initialized = True
    _session = aiohttp.ClientSession()

    # Expose shared state ke cogs
    bot._session = _session
    bot._supabase_storage = supabase_storage
    bot._price_cache = _price_cache
    bot._price_history = _price_history
    bot._auto_bonus_cache = _auto_bonus_cache
    bot._median_bonus_cache = _median_bonus_cache
    bot._bonus_breakdown_cache = _bonus_breakdown
    bot._bonus_deposit_ends_cache = _bonus_deposit_ends
    bot._country_tax_cache = _country_tax_cache
    bot._volume_cache = _volume_cache
    bot._manual_overrides = _manual_overrides
    bot._username_cache = _username_cache
    bot._db_save_prices = db_save_prices
    bot._apply_market_snapshot = apply_market_snapshot
    bot._db_get_history = db_get_history

    # 1) Cogs DULU — inilah yang membuat bot bisa menjawab command dengan cepat.
    for ext in ("cogs.economy", "cogs.spy", "cogs.alert", "cogs.images", "cogs.admin", "cogs.help", "cogs.ping", "cogs.channels", "cogs.blocklist"):
        try:
            await bot.load_extension(ext)
            log.info(f"Loaded: {ext}")
        except Exception as exc:
            log.error(f"Failed to load {ext}: {exc}")

    # 2) Initial data load di BACKGROUND — tidak menunggu di sini.
    asyncio.create_task(_initial_data_load())


async def _initial_data_load() -> None:
    """Semua initial fetch yang dulu membuat on_ready menunggu ~2 menit.
    Periodic loop baru di-start SETELAH initial load selesai (di finally,
    supaya tetap jalan walau error) — menghindari dua gelombang request
    bersamaan saat boot yang memicu badai 429."""
    try:
        # NOTE: volume di-load duluan sebelum harga (ketergantungan db_save_prices).
        volume = await _fetch_volume_safe(_session, allow_fallback=True)
        if volume:
            _volume_cache.update(volume)
            log.info(f"Initial volume loaded: {len(volume)} items")
            await db_save_volume_hourly(volume)

        await restore_price_history()
        snap = await msnap.get_market_snapshot(_session)
        if snap and await apply_market_snapshot(snap):
            log.info(f"Initial prices loaded: {len(snap['prices'])} items")

        initial_raw_data = await mkt.get_bonus_raw_data(_session, with_cache=True)
        _init_countries_by_id = {c["_id"]: c for c in initial_raw_data[0] if c.get("_id")}
        _init_party_ids = list({c.get("rulingParty") for c in _init_countries_by_id.values() if c.get("rulingParty")})
        initial_parties_by_id = await mkt._fetch_parties_batch(_session, _init_party_ids)

        bonuses = await mkt.fetch_max_bonuses(_session, raw_data=initial_raw_data, parties_by_id=initial_parties_by_id)
        if bonuses:
            _auto_bonus_cache.update(bonuses)
            log.info(f"Initial bonuses loaded: {len(bonuses)} items")

        median_bonuses = await mkt.fetch_median_bonuses(_session, raw_data=initial_raw_data, parties_by_id=initial_parties_by_id)
        if median_bonuses:
            _median_bonus_cache.update(median_bonuses)
            log.info(f"Initial median bonuses loaded: {len(median_bonuses)} items")

        breakdown = await mkt.fetch_bonus_breakdown(_session, top_n=5, raw_data=initial_raw_data, parties_by_id=initial_parties_by_id)
        if breakdown:
            _bonus_breakdown.update(breakdown)
            log.info(f"Initial bonus breakdown loaded: {len(breakdown)} items")
            _bonus_deposit_ends.update(
                await mkt.fetch_bonus_deposit_ends(_session, breakdown, raw_data=initial_raw_data, parties_by_id=initial_parties_by_id)
            )
    except Exception:
        log.exception("Initial data load gagal sebagian/seluruhnya — periodic loop tetap dijalankan.")
    finally:
        if not refresh_prices.is_running():
            refresh_prices.start()
        if not refresh_bonuses.is_running():
            refresh_bonuses.start()
        if not refresh_volume.is_running():
            refresh_volume.start()
        if not refresh_territory_tax.is_running():
            refresh_territory_tax.start()
        if not purge_old_wage_events.is_running():
            purge_old_wage_events.start()
        if not auto_delete_worker.is_running():
            auto_delete_worker.start()


@bot.event
async def on_close() -> None:
    if _session:
        await _session.close()


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.NoPrivateMessage):
        return
    if isinstance(error, ChannelNotAllowed):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Argumennya mana sayang? coba cek `xhelp`.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ Invalid argument format.")
        return
    log.error(f"Error on '{ctx.command}': {error}", exc_info=True)
    await ctx.send("❌ Internal error occurred.")

# --- entry point ---

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
