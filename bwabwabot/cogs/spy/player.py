"""
cogs/spy/player.py — `xspy player` & `xspy raw`.

PlayerMixin butuh ApiMixin (self._search_user_ids, self._get_user_lite, dst)
dan disatukan ke SpyCog di __init__.py. Command di sini didefinisikan lepas
(@commands.command, bukan @cmd_spy.command) supaya file ini tidak perlu
import balik dari __init__.py (yang justru import file ini) — subcommand-nya
disambungkan ke group `xspy` secara manual di __init__.py lewat cmd_spy.add_command().
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

import discord
from discord.ext import commands
from core.blocklist import is_player_blocked
from core.permissions import get_level, LEVEL_BOT_ADMIN
from core.messages import MSG_NO_PERM_ADMIN, MSG_BLOCKED_SPY

from .api import _bot_admin_check
from .constants import COMPANY_SCAN_INTERVAL_HOURS, ITEM_EMOJI
from .spy_report import generate_spy_report
from core.utils import make_embed
from services.spy.report import build_report_data
from services.spy.avatar import download_avatar
from services.spy.search import find_player_exact
from services.spy.resolve import resolve_country_name, resolve_mu_name
from services.spy.api_client import get_current_equipment, get_owned_companies, get_wage_info
from services.spy.utils import (
    rarity_from_code,
    classify_stat_range,
    not_found_msg,
)

log = logging.getLogger("WarEraBot.spy")


class PlayerMixin:
    """Mixin — expects ApiMixin di final class (self._search_user_ids,
    self._get_user_lite, self._get_current_equipment, self._resolve_mu_name,
    self._resolve_country_name, self._download_avatar, self._get_owned_companies,
    self._session)."""

    # --- helpers ---

    async def _resolve_player_candidates(self, ctx: commands.Context, nama: str) -> dict | None:
        """Cari player dengan nama PERSIS sama (lihat _find_player_exact). Kalau
        gak ada yang persis: kirim 'not found' + opsi terdekat (teks saja, tanpa
        pemilih nomor) dan balikin None. Balikin data user_lite kalau ketemu."""
        data, suggestions = await find_player_exact(self._session, nama)
        if data:
            return data
        await ctx.send(f"⚠️ {not_found_msg('Player', nama, suggestions, md=True)}")
        return None

    def _gear_stat_tag(self, stat_category: str, value: float, item: dict | None) -> str:
        """current_equipment (kalau berhasil fetch) ngasih data per-slot mentah,
        jadi armor Chest vs Pants bisa dipisah. Rarity ditentukan dari
        RARITY_STAT_RANGES (tabel riset user, basis utama) — rarity_from_code
        cuma dipakai sebagai cross-check kecil, ditampilkan hanya kalau HASILNYA
        BEDA dari classifier stat-range (buat nangkep kalau ada yang perlu dicek
        ulang, bukan buat nentuin rarity utama)."""
        primary = classify_stat_range(stat_category, value)
        secondary = rarity_from_code(item.get("code")) if item else None
        if secondary and secondary != "❓" and secondary != primary:
            return f" ({primary}, check: {secondary}?)"
        return f" ({primary})" if primary != "❓" else ""

    # --- susun dict buat generate_spy_report() (gambar report card) dari data
    #    getUserLite, pakai helper yang sama dengan yang dipakai buat Gear
    #    Stats/embed supaya angka di gambar & embed konsisten ---


    # --- embed pendamping gambar report — HANYA info yang belum ada di gambar:
    #    Gear Stats (equipment + rarity), Companies Owned & Inventory ---
    def _build_player_info_embed(
        self, username: str, data: dict, current_equipment: dict | None,
        wage_data: dict | None = None,
    ) -> discord.Embed:
        skills = data.get("skills", {})
        attack_obj = skills.get("attack", {})
        crit_c_obj = skills.get("criticalChance", {})
        crit_d_obj = skills.get("criticalDamages", {})
        armor_obj = skills.get("armor", {})
        dodge_obj = skills.get("dodge", {})
        prec_obj = skills.get("precision", {})

        wp_atk = float(attack_obj.get("weapon") or 0)
        wp_crit_c = float(crit_c_obj.get("weapon") or 0)
        eq_crit_d = float(crit_d_obj.get("equipment") or 0)
        eq_armor = float(armor_obj.get("equipment") or 0)
        eq_prec = float(prec_obj.get("equipment") or 0)
        eq_dodge = float(dodge_obj.get("equipment") or 0)
        atk_overflow = float(attack_obj.get("overflow") or 0)

        e = make_embed(f"🔍 Intel: {username} — Equipment & Companies", discord.Color.gold())

        # --- Wage info (di atas Gear Stats) ---
        if wage_data:
            wage_line = f"💰 **Wage:** {wage_data['gold_per_pp']:.2f} gold/PP"
            if wage_data.get("company_name"):
                wage_line += f" ({wage_data['company_name']}"
                if wage_data.get("boss_name"):
                    wage_line += f" — {wage_data['boss_name']}"
                wage_line += ")"
            e.add_field(name="💼 Work", value=wage_line, inline=False)

        gear_lines = ["🔫 **Weapon:**"]
        wp_item = (current_equipment or {}).get("weapon") or {}
        wp_suffix = self._gear_stat_tag("weapon_atk", wp_atk, wp_item) if current_equipment else ""
        gear_lines.append(f"   🗡️ ATK: +{wp_atk:.0f}{wp_suffix}")
        gear_lines.append(f"   💥 Crit: +{wp_crit_c:.0f}%")
        gear_lines.append("🛡️ **Equipment:**")
        helmet_item = (current_equipment or {}).get("helmet") or {}
        helmet_suffix = self._gear_stat_tag("helmet_crit_dmg", eq_crit_d, helmet_item) if current_equipment else ""
        gear_lines.append(f"   💢 Crit DMG: +{eq_crit_d:.0f}%{helmet_suffix}")

        if current_equipment:
            chest_item = current_equipment.get("chest") or {}
            pants_item = current_equipment.get("pants") or {}
            gloves_item = current_equipment.get("gloves") or {}
            boots_item = current_equipment.get("boots") or {}

            if chest_item or pants_item:
                chest_armor = float((chest_item.get("skills") or {}).get("armor") or 0)
                pants_armor = float((pants_item.get("skills") or {}).get("armor") or 0)
                if chest_item:
                    gear_lines.append(
                        f"   🛡️ Armor (Chest): +{chest_armor:.0f}{self._gear_stat_tag('armor', chest_armor, chest_item)}"
                    )
                if pants_item:
                    gear_lines.append(
                        f"   🛡️ Armor (Pants): +{pants_armor:.0f}{self._gear_stat_tag('armor', pants_armor, pants_item)}"
                    )
            else:
                gear_lines.append(f"   🛡️ Armor: +{eq_armor:.0f} _(empty slot)_")

            gloves_suffix = self._gear_stat_tag("precision", eq_prec, gloves_item)
            boots_suffix = self._gear_stat_tag("dodge", eq_dodge, boots_item)
            gear_lines.append(f"   🎯 Precision: +{eq_prec:.0f}{gloves_suffix}")
            gear_lines.append(f"   💨 Dodge: +{eq_dodge:.0f}{boots_suffix}")
        else:
            gear_lines.append(
                f"   🛡️ Armor: +{eq_armor:.0f} "
                f"_(Chest+Pants combined, rarity can't be determined per-slot)_"
            )
            prec_tag = classify_stat_range("precision", eq_prec)
            gear_lines.append(
                f"   🎯 Precision: +{eq_prec:.0f}"
                f"{' (' + prec_tag + ')' if prec_tag != '❓' else ''}"
            )
            dodge_tag = classify_stat_range("dodge", eq_dodge)
            gear_lines.append(
                f"   💨 Dodge: +{eq_dodge:.0f}"
                f"{' (' + dodge_tag + ')' if dodge_tag != '❓' else ''}"
            )

        if atk_overflow > 0:
            gear_lines.append(f"   ⚡ Prec→ATK: +{atk_overflow:.0f}")

        e.add_field(name="🎽 Gear Stats", value="\n".join(gear_lines), inline=False)
        return e

    async def _add_companies_field(self, e: discord.Embed, user_id: str) -> None:
        """Nambahin field 'Companies Owned' (nama, item diproduksi, AE level,
        lokasi negara) ke embed yang sudah ada. AE Slot Status summary
        SENGAJA di-drop (tidak lagi relevan buat ditampilkan)."""
        import market as mkt

        company_rows = await get_owned_companies(self._session, user_id)

        region_to_country_name: dict[str, str] = {}
        if company_rows:
            try:
                regions_obj = await mkt.get_regions_object(self._session, with_cache=True)
            except Exception as exc:
                log.warning(f"spy_player regions fetch: {type(exc).__name__}: {exc!r}")
                regions_obj = {}
            try:
                resp = await mkt._get_json_with_retry(self._session, mkt.COUNTRIES_URL, headers=mkt.HEADERS, timeout=15)
                countries_list = resp["result"]["data"] or []
            except Exception as exc:
                log.warning(f"spy_player countries fetch: {type(exc).__name__}: {exc!r}")
                countries_list = []
            countries_by_id = {c["_id"]: c for c in countries_list if c.get("_id")}

            needed_region_ids = {row.get("region_id") for row in company_rows if row.get("region_id")}
            for rid in needed_region_ids:
                rdata = regions_obj.get(rid) or {}
                country_id = rdata.get("country")
                country_name = countries_by_id.get(country_id, {}).get("name", "?") if country_id else "?"
                region_to_country_name[rid] = country_name

        company_lines = []
        if company_rows:
            def _sort_key(row: dict) -> str:
                raw_code = row.get("item_code") or ""
                item_id = mkt.API_KEY_TO_ITEM_ID.get(raw_code, raw_code)
                return mkt.ITEM_LABELS.get(item_id, item_id)

            for row in sorted(company_rows, key=_sort_key):
                raw_code = row.get("item_code") or "?"
                item_id = mkt.API_KEY_TO_ITEM_ID.get(raw_code, raw_code)
                label = mkt.ITEM_LABELS.get(item_id, item_id)
                emoji = ITEM_EMOJI.get(label, "📦")
                ae_level = int(row.get("ae_level") or 0)
                ae_str = f"AE Lv{ae_level}" if ae_level > 0 else "AE Lv0 (idle)"
                fname = row.get("name") or "?"
                country = region_to_country_name.get(row.get("region_id"), "?")
                company_lines.append(f"{emoji} {label} — {ae_str} — {fname}, {country}")
            company_lines.append(f"\n**Total: `{len(company_rows)}` company** (from cache scan)")
        else:
            company_lines.append(
                "ℹ️ No company data cached yet (next scan in "
                f"~{COMPANY_SCAN_INTERVAL_HOURS}h), or this player has no company."
            )

        e.add_field(name="🏭 Companies Owned", value="\n".join(company_lines), inline=False)

    _INVENTORY_RARITY_EMOJI = {
        "mythic": "🔴", "legendary": "🟠", "epic": "🟣",
        "rare": "🔵", "uncommon": "🟢", "common": "⚪",
    }
    _INVENTORY_SLOT_ORDER = ["weapon", "helmet", "chest", "gloves", "pants", "boots"]
    _INVENTORY_SLOT_LABEL = {
        "weapon": "Weapon", "helmet": "Helmet", "chest": "Chest",
        "gloves": "Gloves", "pants": "Pants", "boots": "Boots",
    }

    async def _add_inventory_field(self, e: discord.Embed, user_id: str) -> None:
        """Nambahin 1 field per slot equipment (Weapon/Helmet/Chest/Gloves/
        Pants/Boots) ke embed, isinya rarity + kode item + stats per item
        (TANPA tanggal masuk & ID — sesuai keputusan user, itu detail yang
        di-drop dari versi back.py). Data diambil lewat self._get_inventory()
        — cache-first (TTL 6 jam di Supabase)."""
        inv = await self._get_inventory(user_id)
        if not inv:
            e.add_field(
                name="🎒 Inventory",
                value="ℹ️ Failed to fetch inventory data (empty transaction history or fetch failed).",
                inline=False,
            )
            return

        inventory = inv.get("inventory") or {}
        ordered_slots = [s for s in self._INVENTORY_SLOT_ORDER if inventory.get(s)]
        ordered_slots += [s for s in inventory if s not in self._INVENTORY_SLOT_ORDER and inventory.get(s)]

        if not ordered_slots:
            e.add_field(name="🎒 Inventory", value="ℹ️ No tracked items.", inline=False)
            return

        for slot in ordered_slots:
            if len(e) > 4500:
                e.add_field(name="🎒 …", value="… remaining slots truncated (embed size limit)", inline=False)
                break
            items = inventory[slot]
            lines = []
            for it in items:
                rarity = (it.get("rarity") or "common").lower()
                emoji = self._INVENTORY_RARITY_EMOJI.get(rarity, "❓")
                skills = it.get("skills") or {}
                stats_str = ", ".join(f"{k}:{v}" for k, v in skills.items()) if skills else "-"
                lines.append(f"{emoji} [{rarity.upper()}] {it.get('code', '?')} — {stats_str}")

            value = "\n".join(lines)
            if len(value) > 1024:
                kept, running = [], 0
                for ln in lines:
                    running += len(ln) + 1
                    if running > 970:
                        break
                    kept.append(ln)
                value = "\n".join(kept) + f"\n… +{len(lines) - len(kept)} more items"

            slot_label = self._INVENTORY_SLOT_LABEL.get(slot, slot.title())
            e.add_field(name=f"🎒 {slot_label} ({len(items)})", value=value, inline=False)

        source_note = "cache" if inv.get("from_cache") else "just refreshed"
        capped_note = " ⚠️ history may be incomplete" if inv.get("capped") else ""
        e.add_field(
            name="🎒 Inventory — Total",
            value=f"`{inv.get('total_items', 0)}` item ({source_note}{capped_note})",
            inline=False,
        )

    # --- commands (disambungkan ke group `xspy` di __init__.py) ---

    @commands.command(name="player", aliases=["pl"])
    async def spy_player(self, ctx: commands.Context, *, nama: str) -> None:
        """Player intel sebagai gambar report card + embed equipment, companies
        & inventory. Example: xspy player Vincapervinca"""
        async with ctx.typing():
            data = await self._resolve_player_candidates(ctx, nama)
        if not data:
            return

        username = data.get("username", "?")
        user_id = data.get("_id")
        if await is_player_blocked(user_id):
            if await get_level(ctx.author) < LEVEL_BOT_ADMIN:
                await ctx.send(MSG_BLOCKED_SPY)
                return

        mu_name = await resolve_mu_name(self._session, data.get("mu"))
        country_name = await resolve_country_name(self._session, data.get("country"))

        current_equipment = await get_current_equipment(self._session, user_id) if user_id else None
        wage_data = await get_wage_info(self._session, user_id) if user_id else None

        async with ctx.typing():
            report_data = build_report_data(data, mu_name, country_name)

            avatar_path = await download_avatar(self._session, 
                data.get("avatarUrl", ""), f"/tmp/{username}_avatar.png"
            )

            output_path = f"/tmp/{username}_report.png"
            try:
                await asyncio.to_thread(generate_spy_report, report_data, avatar_path, output_path)
            except Exception as exc:
                log.error(f"spy_player generate report: {exc}", exc_info=True)
                await ctx.send(f"❌ Failed to generate report image: {exc}")
                return

        await ctx.send(file=discord.File(output_path))

        if not user_id:
            return

        async with ctx.typing():
            e = self._build_player_info_embed(username, data, current_equipment, wage_data)
            await self._add_companies_field(e, user_id)
            await ctx.send(embed=e)
            # 🎒 Inventory embed sementara dinonaktifkan (akurasi item nyangkut,
            # lihat sesi debug 2026-09-23) — sampai ada solusi.

    @commands.command(name="raw")
    @commands.check(_bot_admin_check)
    async def spy_raw(self, ctx: commands.Context, *, nama: str) -> None:
        async with ctx.typing():
            data, suggestions = await find_player_exact(self._session, nama)
            if not data:
                await ctx.send(f"⚠️ {not_found_msg('Player', nama, suggestions, md=True)}")
                return

        top_keys = list(data.keys())
        preview = json.dumps(data, indent=2, default=str)

        e = make_embed(f"🔧 Raw Keys: {data.get('username', nama)}", discord.Color.dark_grey())
        e.description = (
            f"**Top-level keys:**\n```{', '.join(top_keys)}```\n"
            f"Full JSON file attached below."
        )
        await ctx.send(embed=e)

        buf = io.BytesIO(preview.encode("utf-8"))
        await ctx.send(file=discord.File(buf, filename=f"{data.get('username', nama)}_raw.json"))

    @spy_raw.error
    async def spy_raw_error(self, ctx: commands.Context, error: Exception) -> None:
        from core.utils import ChannelNotAllowed
        if isinstance(error, ChannelNotAllowed):
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send(MSG_NO_PERM_ADMIN)
        else:
            log.error(f"spy_raw error: {error}", exc_info=True)
            await ctx.send("❌ An error occurred.")
