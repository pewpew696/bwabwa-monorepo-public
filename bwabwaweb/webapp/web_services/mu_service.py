"""Logika Intel MU: port dari web_api/search_routes.py::search_mu tanpa cog.

Semua network call pakai aiohttp.ClientSession baru per request.
Fungsi murni dari services/spy/ dipakai apa adanya.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

from services.spy.api_client import get_mu, get_mu_upgrade, get_user_lite
from services.spy.search import search_mu
from services.spy.utils import classify_build, not_found_msg
from webapp.core.errors import NotFoundError

MEMBER_LIMIT = 25
CACHE_TTL_SECONDS = 300.0

_cache: dict = {}


@dataclass(frozen=True)
class MuMember:
    user_id: str
    username: str
    level: str
    build: str
    role: str
    hp: tuple[int, int]
    hunger: tuple[int, int]
    pill: str
    avatar_url: str


@dataclass(frozen=True)
class MuReport:
    name: str
    avatar_url: str
    member_count: int
    level: str
    weekly_dmg: float
    total_dmg: float
    roster: list[MuMember]
    hq: dict | None
    dormitory: dict | None


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_pill(md: dict) -> str:
    """Timer buff/debuff dari field buffs. Port 1:1 dari search_routes.py."""
    skills = md.get("skills", {}) or {}
    atk_obj = skills.get("attack", {}) or {}
    buffs_pct = float(atk_obj.get("buffsPercent") or 0)
    deb_pct = float(atk_obj.get("debuffsPercent") or 0)
    buffs = md.get("buffs") or {}
    buff_end = buffs.get("buffEndAt")
    debuff_end = buffs.get("debuffEndAt")
    now = datetime.now(timezone.utc)

    if buff_end and buffs_pct > 0:
        try:
            end_dt = datetime.fromisoformat(buff_end.replace("Z", "+00:00"))
            remaining = (end_dt - now).total_seconds()
            if remaining > 0:
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                return f"💊 {h}h{m:02d}m"
            return "💊 active"
        except Exception:
            return "💊 active"
    if debuff_end and deb_pct > 0:
        try:
            end_dt = datetime.fromisoformat(debuff_end.replace("Z", "+00:00"))
            remaining = (end_dt - now).total_seconds()
            if remaining > 0:
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                return f"🤢 {h}h{m:02d}m"
            return "🤢 debuff"
        except Exception:
            return "🤢 debuff"
    if buffs_pct > 0:
        return "💊 active"
    if deb_pct > 0:
        return "🤢 debuff"
    return "—"


def _build_member(uid: str, md: dict | None, commanders: set, managers: set) -> MuMember:
    if not md:
        return MuMember(
            user_id=uid, username="? (failed to fetch)", level="?",
            build="—", role="—", hp=(0, 1), hunger=(0, 1),
            pill="—", avatar_url="",
        )
    uname = md.get("username", uid[:8])
    lv = md.get("leveling", {}).get("level", "?")
    spent = int(md.get("leveling", {}).get("spentSkillPoints") or 0)
    skills = md.get("skills", {}) or {}
    build = classify_build(skills, spent)

    hp_obj = skills.get("health", {}) or {}
    hu_obj = skills.get("hunger", {}) or {}
    hp_cur = float(hp_obj.get("currentBarValue") or 0)
    hp_max = float(hp_obj.get("value") or 0) or 1
    hu_cur = float(hu_obj.get("currentBarValue") or 0)
    hu_max = float(hu_obj.get("value") or 0) or 1

    if uid in managers:
        role = "Manager"
    elif uid in commanders:
        role = "Commander"
    else:
        role = "Member"

    return MuMember(
        user_id=uid, username=uname, level=lv, build=build, role=role,
        hp=(round(hp_cur), round(hp_max)),
        hunger=(round(hu_cur), round(hu_max)),
        pill=_parse_pill(md),
        avatar_url=md.get("avatarUrl", ""),
    )


class MuService:
    async def get_mu(self, raw_name: str) -> MuReport:
        raw_name = (raw_name or "").strip()
        if not raw_name:
            raise NotFoundError("Nama MU kosong")

        cache_key = raw_name.lower()
        now_mono = time.monotonic()
        cached = _cache.get(cache_key)
        if cached and (now_mono - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        async with aiohttp.ClientSession() as session:
            result, suggestions = await search_mu(session, raw_name)
            if not result:
                raise NotFoundError(not_found_msg("MU", raw_name, suggestions))

            mu_id, _ = result
            mu_data = await get_mu(session, mu_id)
            if not mu_data:
                raise NotFoundError(f"MU '{raw_name}' tidak ditemukan")

            members = mu_data.get("members", []) or []
            all_members = members[:MEMBER_LIMIT]
            member_data = await _gather_members(session, all_members)
            hq_data = await get_mu_upgrade(session, mu_id, "headquarters")
            dorm_data = await get_mu_upgrade(session, mu_id, "dormitories")

        mu_name = mu_data.get("name", raw_name)
        commanders = set(mu_data.get("roles", {}).get("commanders", []) or [])
        managers = set(mu_data.get("roles", {}).get("managers", []) or [])
        rankings = mu_data.get("rankings", {}) or {}
        mu_weekly = _safe_float((rankings.get("muWeeklyDamages") or {}).get("value"))
        mu_total = _safe_float((rankings.get("muDamages") or {}).get("value"))
        level = mu_data.get("leveling", {}).get("level", "?")

        roster = [
            _build_member(uid, md, commanders, managers)
            for uid, md in zip(all_members, member_data)
        ]

        hq_level = int(hq_data.get("level") or 0) if hq_data else 0
        hq_status = hq_data.get("status", "") if hq_data else ""
        dorm_level = int(dorm_data.get("level") or 0) if dorm_data else 0
        dorm_capacity = dorm_level * 5 if dorm_level > 1 else None

        report = MuReport(
            name=mu_name,
            avatar_url=mu_data.get("avatarUrl", ""),
            member_count=len(members),
            level=level,
            weekly_dmg=mu_weekly,
            total_dmg=mu_total,
            roster=roster,
            hq={"level": hq_level, "active": hq_status == "active"} if hq_level > 1 else None,
            dormitory={"level": dorm_level, "capacity": dorm_capacity} if dorm_level > 1 else None,
        )
        _cache[cache_key] = (time.monotonic(), report)
        return report


async def _gather_members(session: aiohttp.ClientSession, uids: list[str]) -> list:
    import asyncio
    return await asyncio.gather(*[get_user_lite(session, uid) for uid in uids])
