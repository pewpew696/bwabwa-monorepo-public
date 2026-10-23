"""
cogs/economy/base.py  —  Konstanta, formatter, dan mixin dasar Economy cog.

Semua file cmd_*.py di package ini meng-inherit `EconomyBase` supaya punya
akses ke state bot (session, cache, dsb) tanpa jadi `commands.Cog` sendiri.
discord.py tetap bisa menemukan semua @commands.command di seluruh MRO
selama class akhir (lihat `economy/__init__.py`) meng-inherit commands.Cog.

Free function `resolve_item()` di file ini juga dipakai web_api/market_routes.py.

Supabase tables needed:
  price_history     : item_name, price, volume, recorded_at
  manual_donations  : country_id, username, amount, donation_date, added_by
  liquidity_anchors : insert-only; baris terbaru = ORDER BY calibrated_at DESC LIMIT 1

RPCs needed: liquidity_basket_medians, item_median_notional_30d, price_extremes_all
"""

from __future__ import annotations
from services.db import pool as db_pool
from services.economy import base_db, liquidity_refresh

import asyncio
import logging

from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord.ext import commands

import market as mkt

log = logging.getLogger("WarEraBot.economy")

# --- helpers ---

from core.utils import make_embed as _embed
from services.economy.formatters import _fmt_pct
from services.economy.items import resolve_item
from services.economy.liquidity import (
    LiquidityScoreResult,
    _anchor_age_days,
    _compute_liquidity_score,
    SCORE_MIN_HISTORY_DAYS,
)

# --- constants ---

AE_PP_PER_DAY: dict[int, int] = {
    1: 24, 2: 48, 3: 72, 4: 96, 5: 120, 6: 144, 7: 168,
}

# PRODUCTION_CHAIN & ITEM_NOT_PRODUCIBLE dipindah ke services/economy/constants.py (session 27 Sep).
# Re-export biar pemakai lama (item.py, __init__.py, web_api) tetap jalan tanpa ubah import.
from services.economy.constants import (  # noqa: E402
    ITEM_EMOJI,
    ITEM_NOT_PRODUCIBLE,
    PRODUCTION_CHAIN,
)

TOP_RANGES:           dict[str, int] = {"1d": 24, "7d": 168, "30d": 720}
DONATION_RANGE_WEEKS: dict[str, int] = {"1w": 1, "2w": 2, "3w": 3, "4w": 4, "5w": 5}

# Layout gambar xdonation — batas fisik gambar dicek juga di visuals.
DON_PER_COL_CAP = 25
DON_MAX_COLS    = 3
DON_PAGE_CAP    = DON_PER_COL_CAP * DON_MAX_COLS  # 75 donor/tanggal per halaman

# --- liquidity calibration ---

# NOTE: histori price_history baru mulai 2026-07-04, jadi 60 dulu (bukan 90) —
# naikkan begitu histori genap.

# 60 hari = syarat membentuk anchor; 7/30 di bawah = syarat skor per-item.



OUT_OF_RANGE_ALERT_DAYS = 5   # konstanta job alert (belum ada implementasinya)
ANCHOR_MAX_AGE_DAYS = 35      # siklus bulanan + grace

DAILY_CACHE_TTL_HOURS = 24.0
DAILY_CACHE_RETRY_HOURS = 0.25   # retry 15 menit kalau refresh gagal total



class _BotAttr:
    """Descriptor: self._X -> self.bot.<bot_attr>.

    lazy=True: inisialisasi {} kalau attribute bot belum ada
    (dipakai cache harian biar aman sebelum on_ready).
    """
    __slots__ = ("bot_attr", "lazy")

    def __init__(self, bot_attr: str, lazy: bool = False):
        self.bot_attr = bot_attr
        self.lazy = lazy

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        if self.lazy and not hasattr(obj.bot, self.bot_attr):
            setattr(obj.bot, self.bot_attr, {})
        return getattr(obj.bot, self.bot_attr)

    def __set__(self, obj, value):
        setattr(obj.bot, self.bot_attr, value)


class EconomyBase:
    """Mixin dasar: shortcut ke shared state di bot + helper item/db.

    Tidak mewarisi commands.Cog — hanya EconomyCog di __init__.py yang
    melakukannya, menggabungkan mixin ini bersama semua *Commands mixin.
    """

    bot: commands.Bot

    # --- shortcuts ke shared state bot ---

    _session              = _BotAttr("_session")
    _price_cache          = _BotAttr("_price_cache")
    _volume_cache         = _BotAttr("_volume_cache")
    _price_history        = _BotAttr("_price_history")
    _auto_bonus_cache     = _BotAttr("_auto_bonus_cache")
    _manual_overrides     = _BotAttr("_manual_overrides")
    _username_cache       = _BotAttr("_username_cache")

    # lazy-init cache (nama attribute bot kadang beda dari nama property)
    _median_bonus_cache   = _BotAttr("_median_bonus_cache", lazy=True)
    _bonus_breakdown      = _BotAttr("_bonus_breakdown_cache", lazy=True)
    _bonus_deposit_ends   = _BotAttr("_bonus_deposit_ends_cache", lazy=True)
    _country_tax_cache    = _BotAttr("_country_tax_cache", lazy=True)

    # cache harian (punya setter implicit lewat descriptor)
    _liquidity_score_cache  = _BotAttr("_liquidity_score_cache", lazy=True)
    _liquidity_anchor_meta  = _BotAttr("_liquidity_anchor_meta", lazy=True)
    _price_extremes_cache   = _BotAttr("_price_extremes_cache", lazy=True)

    # --- item helpers ---

    def _resolve(self, query: str) -> Optional[str]:
        return resolve_item(self._price_cache, query)

    def _cleanup_overrides(self) -> None:
        now     = datetime.now(timezone.utc)
        expired = [k for k, v in self._manual_overrides.items() if v["expires_at"] <= now]
        for k in expired:
            del self._manual_overrides[k]

    def _get_bonus(self, item: str) -> tuple[float, str]:
        self._cleanup_overrides()
        for k, v in self._manual_overrides.items():
            if k.lower() == item.lower():
                return v["pct"], "manual"
        for k, v in self._auto_bonus_cache.items():
            if k.lower() == item.lower():
                return v, "auto"
        return 0.0, "none"

    def _get_median_bonus(self, item: str) -> tuple[float, str]:
        # Khusus fairprice engine — bukan pengganti _get_bonus.
        for k, v in self._median_bonus_cache.items():
            if k.lower() == item.lower():
                return v, "median"
        return 0.0, "none"

    def _trend(self, item: str, current: float) -> str:
        history = list(self._price_history.get(item, []))
        if len(history) < 2:
            return "⚪ Sideways (insufficient data)"
        now    = datetime.now(timezone.utc)
        recent = [p for ts, p in history if (now - ts).total_seconds() / 60 <= 60]
        if not recent:
            return "⚪ Sideways"
        avg = sum(recent) / len(recent)
        if avg == 0:
            return "⚪ Sideways"
        chg = ((current - avg) / avg) * 100
        if chg > 1.0:
            return f"🟢 Bullish (+{_fmt_pct(chg)}%)"
        elif chg < -1.0:
            return f"🔴 Bearish ({_fmt_pct(chg)}%)"
        s = f"+{_fmt_pct(chg)}" if chg >= 0 else _fmt_pct(chg)
        return f"⚪ Sideways ({s}%)"
    # --- manual donation (data yang gak terdeteksi API WarEra) ---

    async def _db_get_manual_donations(self, country_id: str, since_date: str) -> list[dict]:
        return await base_db.get_manual_donations(country_id, since_date)

    async def _db_add_manual_donation(
        self, country_id: str, username: str, amount: float, donation_date: str, added_by: str
    ) -> dict | None:
        return await base_db.add_manual_donation(
            country_id, username, amount, donation_date, added_by
        )

    async def _db_delete_manual_donation(self, entry_id: int) -> bool:
        return await base_db.delete_manual_donation(entry_id)

    # --- liquidity anchors ---

    async def get_latest_liquidity_anchor(self) -> Optional[dict]:
        return await liquidity_refresh.fetch_latest_anchor()

    async def recalibrate_liquidity_anchors(self, force: bool = False) -> Optional[dict]:
        return await liquidity_refresh.recalibrate_anchors(force)

    async def get_liquidity_score(self, item: str) -> LiquidityScoreResult:
        """Skor 1 item — jalur ad-hoc (admin/debug). Produksi pakai
        refresh_liquidity_scores() (batch, satu RPC)."""
        history_days, median_notional_30d = await self._item_notional_history(item)
        anchor = await self.get_latest_liquidity_anchor()
        return _compute_liquidity_score(item, history_days, median_notional_30d, anchor)

    async def _item_notional_history(self, item: str) -> tuple[int, Optional[float]]:
        return await liquidity_refresh.get_item_notional_history(item)

    # --- job refresh harian ---

    async def refresh_liquidity_scores(self) -> bool:
        """Job harian: isi _liquidity_score_cache untuk semua item
        PRODUCTION_CHAIN dari satu RPC. Return True kalau ada data valid baru
        (menentukan retry 15 menit vs TTL 24 jam di _ensure_daily_caches)."""
        try:
            anchor = await self.get_latest_liquidity_anchor()

            # jaring pengaman: anchor belum ada / terlalu tua (cron terlewat)
            # -> kalibrasi sekarang; insert-only jadi idempotent
            age = _anchor_age_days(anchor)
            if anchor is None or (age is not None and age > ANCHOR_MAX_AGE_DAYS):
                new_anchor = await self.recalibrate_liquidity_anchors(force=True)
                if new_anchor is not None:
                    anchor = new_anchor

            cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=SCORE_MIN_HISTORY_DAYS)).isoformat()

            def _query():
                return db_pool.rpc(
                    "liquidity_basket_medians",
                    {"cutoff": cutoff_7d, "lookback_days": 30},
                ).execute()

            result = await asyncio.to_thread(_query)
            rows = result or []
            by_item = {r["item_name"]: r for r in rows}

            new_cache: dict[str, LiquidityScoreResult] = {}
            for item in PRODUCTION_CHAIN:
                r = by_item.get(item)
                if r is None or r.get("median_notional") is None:
                    # absen dari RPC = histori < 7 hari -> exclude
                    new_cache[item] = _compute_liquidity_score(item, 0, None, anchor)
                else:
                    new_cache[item] = _compute_liquidity_score(
                        item,
                        int(r.get("history_days") or 0),
                        float(r["median_notional"]),
                        anchor,
                    )

            valid_new = sum(1 for v in new_cache.values() if v["score"] is not None)
            if valid_new == 0:
                old = self._liquidity_score_cache
                valid_old = sum(1 for v in old.values() if v["score"] is not None)
                if valid_old > 0:
                    # Supabase bermasalah — cache lama (stale) lebih baik
                    # daripada kosong.
                    log.error(
                        "refresh_liquidity_scores: 0/20 skor valid — cache lama "
                        "dipertahankan (stale), akan diretry."
                    )
                    return False
                # belum pernah ada data valid — simpan apa adanya
                self._liquidity_score_cache = new_cache
                self._liquidity_anchor_meta = {
                    "calibrated_at": (anchor or {}).get("calibrated_at"),
                    "anchor_age_days": _anchor_age_days(anchor),
                }
                return False

            # replace atomik
            self._liquidity_score_cache = new_cache
            self._liquidity_anchor_meta = {
                "calibrated_at": (anchor or {}).get("calibrated_at"),
                "anchor_age_days": _anchor_age_days(anchor),
            }
            log.info(f"refresh_liquidity_scores: {valid_new}/{len(new_cache)} item punya skor valid")
            return True
        except Exception as exc:
            log.error(f"refresh_liquidity_scores: {exc}")
            return False

    async def refresh_price_extremes(self) -> bool:
        """Job harian: isi _price_extremes dari satu RPC aggregate.

        Pakai seluruh histori — label display wajib qualifier tracked_since
        (lihat fairprice.py), tracking baru mulai 2026-07-04."""
        try:
            def _query():
                return db_pool.rpc("price_extremes_all", {}).execute()

            result = await asyncio.to_thread(_query)
            rows = result or []
            new_cache: dict[str, dict] = {}
            for r in rows:
                name = r.get("item_name")
                if not name or r.get("recorded_high") is None or r.get("recorded_low") is None:
                    continue
                new_cache[name] = {
                    "recorded_high": float(r["recorded_high"]),
                    "recorded_high_date": str(r.get("recorded_high_date") or ""),
                    "recorded_low": float(r["recorded_low"]),
                    "recorded_low_date": str(r.get("recorded_low_date") or ""),
                    "tracked_since": str(r.get("tracked_since") or ""),
                }

            if not new_cache:
                old = self._price_extremes_cache
                if old:
                    log.error("refresh_price_extremes: 0 baris — cache lama dipertahankan (stale).")
                    return False
                return False

            self._price_extremes_cache = new_cache
            log.info(f"refresh_price_extremes: {len(new_cache)} item")
            return True
        except Exception as exc:
            log.error(f"refresh_price_extremes: {exc}")
            return False

    async def _ensure_daily_caches(self) -> None:
        """Pastikan cache harian tidak stale — murah kalau fresh (cuma cek
        timestamp). Timestamp di-set sebelum refresh; kalah race = query dobel
        yang idempotent. asyncio.Lock sengaja gak dipakai (rawan
        cross-event-loop dari web)."""
        now = datetime.now(timezone.utc)
        last = getattr(self.bot, "_daily_caches_refreshed_at", None)
        if last is not None:
            ok = getattr(self.bot, "_daily_caches_ok", False)
            age_h = (now - last).total_seconds() / 3600.0
            if ok and age_h < DAILY_CACHE_TTL_HOURS:
                return
            if not ok and age_h < DAILY_CACHE_RETRY_HOURS:
                return

        # tandai dulu — request paralel skip
        self.bot._daily_caches_refreshed_at = now
        self.bot._daily_caches_ok = False

        ok_any = False
        try:
            ok_liq = await self.refresh_liquidity_scores()
            ok_ext = await self.refresh_price_extremes()
            ok_any = ok_liq and ok_ext
        except Exception as exc:
            log.error(f"_ensure_daily_caches: gagal — {exc}")
            ok_any = False

        self.bot._daily_caches_ok = ok_any

    # --- shared batch: jalur tunggal Discord + web ---

    async def _fp_analyze_batch(self, session, candidates: list) -> list:
        """Batch analysis tunggal untuk xfp Discord dan /api/fairprice.

        Filter kandidat CUMA cek keberadaan di price cache — jangan prefilter
        PRODUCTION_CHAIN/ITEM_NOT_PRODUCIBLE (Scraps/Case 1/Case 2 harus tetap
        ke-analisis; keputusan producible ada di _fp_analyze).
        """
        # cache harian — self-healing
        await self._ensure_daily_caches()

        candidates = [
            n for n in candidates
            if self._price_cache.get(n) is not None
        ]
        orderbooks = await asyncio.gather(
            *[mkt.fetch_orderbook(session, n) for n in candidates],
            return_exceptions=True,
        )
        analyses = await asyncio.gather(
            *[self._fp_analyze(n, "error" if isinstance(ob, Exception) else ob)
              for n, ob in zip(candidates, orderbooks)],
            return_exceptions=True,
        )
        results = []
        for name, a in zip(candidates, analyses):
            if isinstance(a, dict):
                results.append(a)
            elif isinstance(a, Exception):
                # exception yang di-drop wajib kelihatan di log
                log.warning(f"_fp_analyze({name}) gagal: {a}")
        return results
