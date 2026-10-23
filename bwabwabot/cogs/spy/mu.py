"""
cogs/spy/mu.py — `xspy mu`.

MuMixin butuh ApiMixin (self._search_mu, self._get_mu, self._get_user_lite).
Command didefinisikan lepas (@commands.command) lalu disambungkan ke group
`xspy` secara manual di __init__.py lewat cmd_spy.add_command().
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from core.utils import make_embed
from services.spy.utils import fmt_k, classify_build, not_found_msg
from services.spy.search import search_mu
from services.spy.api_client import get_mu, get_mu_upgrade, get_user_lite

log = logging.getLogger("WarEraBot.spy")


class MuMixin:
    """Mixin — expects ApiMixin di final class."""

    def _mu_member_row(self, md: dict, uid: str, commanders: set, managers: set) -> str:
        uname = md.get("username", uid[:8])
        lv = md.get("leveling", {}).get("level", "?")
        spent = int(md.get("leveling", {}).get("spentSkillPoints") or 0)
        skills = md.get("skills", {})
        build = classify_build(skills, spent)

        hp_obj = skills.get("health", {})
        hu_obj = skills.get("hunger", {})
        hp_cur = float(hp_obj.get("currentBarValue") or 0)
        hp_max = float(hp_obj.get("value") or 0)
        hu_cur = float(hu_obj.get("currentBarValue") or 0)
        hu_max = float(hu_obj.get("value") or 0)

        if uid in managers:
            role = "Manager"
        elif uid in commanders:
            role = "Commander"
        else:
            role = "Member"

        buffs = md.get("buffs") or {}
        buff_end = buffs.get("buffEndAt")
        debuff_end = buffs.get("debuffEndAt")
        atk_obj = skills.get("attack", {})
        buffs_pct = float(atk_obj.get("buffsPercent") or 0)
        deb_pct = float(atk_obj.get("debuffsPercent") or 0)

        pill = "—"
        now = datetime.now(timezone.utc)
        if buff_end and buffs_pct > 0:
            try:
                end_dt = datetime.fromisoformat(buff_end.replace("Z", "+00:00"))
                remaining = (end_dt - now).total_seconds()
                if remaining > 0:
                    h = int(remaining // 3600)
                    m = int((remaining % 3600) // 60)
                    pill = f"💊 {h}h{m:02d}m"
                else:
                    pill = "💊 active"
            except Exception:
                pill = "💊 active"
        elif debuff_end and deb_pct > 0:
            try:
                end_dt = datetime.fromisoformat(debuff_end.replace("Z", "+00:00"))
                remaining = (end_dt - now).total_seconds()
                if remaining > 0:
                    h = int(remaining // 3600)
                    m = int((remaining % 3600) // 60)
                    pill = f"🤢 {h}h{m:02d}m"
                else:
                    pill = "🤢 debuff"
            except Exception:
                pill = "🤢 debuff"
        elif buffs_pct > 0:
            pill = "💊 active"
        elif deb_pct > 0:
            pill = "🤢 debuff"

        return (
            f"{build} **{uname}** Lv{lv} · {role}\n"
            f"❤️ {hp_cur:.0f}/{hp_max:.0f} · 🍖 {hu_cur:.1f}/{hu_max:.0f} · {pill}"
        )

    @commands.command(name="mu")
    async def spy_mu(self, ctx: commands.Context, *, nama: str) -> None:
        """MU roster. Example: xspy mu 10th Para SF"""
        async with ctx.typing():
            result, suggestions = await search_mu(self._session, nama)
            if not result:
                await ctx.send(f"⚠️ {not_found_msg('MU', nama, suggestions, md=True)}")
                return
            mu_id, _ = result

            mu_data = await get_mu(self._session, mu_id)
            if not mu_data:
                await ctx.send("❌ Failed to fetch MU data.")
                return

            mu_name = mu_data.get("name", nama)
            members = mu_data.get("members", [])
            commanders = set(mu_data.get("roles", {}).get("commanders", []))
            managers = set(mu_data.get("roles", {}).get("managers", []))
            rankings = mu_data.get("rankings", {})
            mu_weekly = float((rankings.get("muWeeklyDamages") or {}).get("value") or 0)
            mu_total = float((rankings.get("muDamages") or {}).get("value") or 0)

            hq_data = await get_mu_upgrade(self._session, mu_id, "headquarters")
            dorm_data = await get_mu_upgrade(self._session, mu_id, "dormitories")

            all_members = members[:25]
            member_data = await asyncio.gather(*[
                get_user_lite(self._session, uid) for uid in all_members
            ])

        rows = []
        for i, (uid, md) in enumerate(zip(all_members, member_data)):
            if not md:
                rows.append(f"❓ *Member {i+1} — failed to fetch*")
                continue
            rows.append(self._mu_member_row(md, uid, commanders, managers))

        hq_level = int(hq_data.get("level") or 0) if hq_data else 0
        hq_status = hq_data.get("status", "") if hq_data else ""
        dorm_level = int(dorm_data.get("level") or 0) if dorm_data else 0

        header_parts = []
        if dorm_level > 1:
            capacity = dorm_level * 5
            header_parts.append(f"Members: {len(members)}/{capacity}")
        else:
            header_parts.append(f"Members: {len(members)}")

        if hq_level > 1:
            status_emoji = "✅" if hq_status == "active" else "❌"
            header_parts.append(f"HQ: Lv{hq_level} {status_emoji}")

        if dorm_level > 1:
            header_parts.append(f"Dorm: Lv{dorm_level}")

        header = "  |  ".join(header_parts) + "\n"
        header += f"**Weekly DMG:** {fmt_k(mu_weekly)}  |  **Total DMG:** {fmt_k(mu_total)}"
        sep = "─────────────────────────────"

        chunk1 = rows[:13]
        chunk2 = rows[13:]

        e1 = make_embed(f"🔍 Intel MU: {mu_name}", discord.Color.gold())
        e1.description = header + "\n" + sep + "\n" + f"\n{sep}\n".join(chunk1)
        await ctx.send(embed=e1)

        if chunk2:
            e2 = make_embed(f"🔍 Intel MU: {mu_name} (continued)", discord.Color.gold())
            e2.description = f"\n{sep}\n".join(chunk2)
            await ctx.send(embed=e2)