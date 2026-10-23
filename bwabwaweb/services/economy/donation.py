# services/economy/donation.py — agregasi & grouping donasi (kalkulasi murni)

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def get_week_range_start(weeks_back: int) -> datetime:
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()
    last_monday = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return last_monday - timedelta(weeks=weeks_back - 1)


def aggregate_donations(items: list[dict]) -> tuple[list[tuple[str, float]], float]:
    totals: dict[str, float] = {}
    for item in items:
        buyer = item.get("buyerId")
        if not buyer:
            continue
        money = float(item.get("money", 0) or 0)
        totals[buyer] = totals.get(buyer, 0.0) + money

    grand_total = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return ranked, grand_total


def group_donations_by_day(items: list[dict], top_n: int = 15) -> dict[str, list[tuple[str, float]]]:
    """Kelompokkan donasi per hari (UTC, 'YYYY-MM-DD'), ranking top_n per
    hari berdasarkan buyerId. Nilai sama di hari sama dijumlahkan. Hari
    dengan donatur > top_n dipotong ke top_n aja, biar tabel tetep rapi."""
    daily_totals: dict[str, dict[str, float]] = {}
    for item in items:
        created = item.get("createdAt", "")
        day = created[:10]
        buyer = item.get("buyerId")
        if not day or not buyer:
            continue
        money = float(item.get("money", 0) or 0)
        bucket = daily_totals.setdefault(day, {})
        bucket[buyer] = bucket.get(buyer, 0.0) + money

    result: dict[str, list[tuple[str, float]]] = {}
    for day, totals in daily_totals.items():
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
        result[day] = ranked
    return result
