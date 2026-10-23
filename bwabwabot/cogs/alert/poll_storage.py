"""
cogs/alerts/poll_storage.py — Task loop poll_storage: Type 4 (Company Storage Alert).

Beda dari Type 1-3: alert dikirim via DM ke discord_user_id yang daftar,
bukan ke channel guild + role ping. Gak lewat alert_configs / _interactive_add
— pakai tabel Supabase sendiri (storage_watchlist + storage_alert_state).
"""

from __future__ import annotations

import discord
from discord.ext import tasks

from .base import (
    AlertsBase, log,
    STORAGE_POLL_INTERVAL_MIN, STORAGE_ALERT_THRESHOLD_PCT, STORAGE_CAPACITY_BY_LEVEL,
)


class PollStorageCommands(AlertsBase):

    async def _fetch_warera_json(self, method: str, input_obj: dict) -> dict:
        import market as mkt
        url = f"{mkt.BASE_URL}/{method}?input={mkt._encode(input_obj)}"
        resp = await mkt._get_json_with_retry(self._session, url, headers=mkt.HEADERS, timeout=15)
        return resp["result"]["data"]

    @tasks.loop(minutes=STORAGE_POLL_INTERVAL_MIN)
    async def poll_storage(self) -> None:
        if not self._storage_watchlist:
            return
        for warera_user_id, discord_user_id in list(self._storage_watchlist.items()):
            try:
                await self._check_storage_account(warera_user_id, discord_user_id)
            except Exception as exc:
                log.error(f"poll_storage({warera_user_id}): {exc}", exc_info=True)

    @poll_storage.before_loop
    async def _before_poll_storage(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_storage_account(self, warera_user_id: str, discord_user_id: int) -> None:
        user_data = await self._fetch_warera_json("user.getUserById", {"userId": warera_user_id})
        company_ids = (await self._fetch_warera_json(
            "company.getCompanies", {"userId": warera_user_id}
        )).get("items", [])

        companies = []
        for company_id in company_ids:
            c = await self._fetch_warera_json("company.getById", {"companyId": company_id})
            level = c.get("activeUpgradeLevels", {}).get("storage", 1)
            capacity = STORAGE_CAPACITY_BY_LEVEL.get(level, max(STORAGE_CAPACITY_BY_LEVEL.values()))
            # ⚠️ asumsi "production" = isi storage saat ini — VERIFIKASI dulu manual
            # sebelum trust angka ini (lihat catatan review sebelumnya).
            storage_pct = round(c.get("production", 0) / capacity * 100, 1)
            companies.append({
                "name": c.get("name", company_id),
                "item": c.get("itemCode", "?"),
                "storage_pct": storage_pct,
            })

        prev_pct = self._storage_state.get(warera_user_id, {})
        # Trigger per-company (fix bug: sebelumnya pakai max() gabungan, bikin company
        # lain gak pernah ke-alert selama ada 1 company yang udah nangkring >=80%).
        triggered = [
            c for c in companies
            if c["storage_pct"] >= STORAGE_ALERT_THRESHOLD_PCT > prev_pct.get(c["name"], 0.0)
        ]

        if triggered:
            try:
                await self._send_storage_alert(discord_user_id, user_data, companies)
            except Exception as exc:
                log.warning(f"_send_storage_alert({warera_user_id}): {exc}")
                return  # jangan commit state kalau alert gagal — biar crossing dicoba lagi next poll

        await self._set_storage_state(warera_user_id, {c["name"]: c["storage_pct"] for c in companies})

    async def _send_storage_alert(self, discord_user_id: int, user_data: dict, companies: list) -> None:
        user = await self.bot.fetch_user(discord_user_id)
        skills = user_data.get("skills", {})
        energy = skills.get("energy", {})
        health = skills.get("health", {})

        embed = discord.Embed(
            title=f"👋 Hi, {user_data.get('username', '?')}!",
            description="You have company storage that needs checking:",
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="📦 Storage Company",
            value="\n".join(
                f"• **{c['name']}** ({c['item']}) — **{c['storage_pct']}%** full" for c in companies
            ) or "No companies",
            inline=False,
        )
        embed.add_field(
            name="📊 Character Status",
            value=(
                f"⚡ Energy: {energy.get('currentBarValue', 0):.0f}/{energy.get('total', '?')}\n"
                f"❤️ HP: {health.get('currentBarValue', 0):.0f}/{health.get('total', '?')}"
            ),
            inline=False,
        )
        embed.set_footer(text="Company & Character Alert")

        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            log.warning(f"Gak bisa DM user {discord_user_id}")
