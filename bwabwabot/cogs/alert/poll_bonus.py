"""
cogs/alerts/poll_bonus.py  —  Task loop poll_bonus: Type 3 (Production Bonus Alert).
"""

from __future__ import annotations

from datetime import datetime

from discord.ext import commands, tasks

from .base import AlertsBase, log, _resolve_resource, BONUS_POLL_INTERVAL_MIN, BONUS_ALERT_EPSILON, BONUS_BREAKDOWN_TOP_N
from .embeds import build_bonus_embed


class PollBonusCommands(AlertsBase):

    @tasks.loop(minutes=BONUS_POLL_INTERVAL_MIN)
    async def poll_bonus(self) -> None:
        try:
            configs3 = await self._get_configs(3)
            if not configs3:
                return

            import market as mkt
            breakdown = await mkt.fetch_bonus_breakdown(
                self._session, top_n=BONUS_BREAKDOWN_TOP_N, with_cache=True
            )
            if not breakdown:
                return

            watch_all     = any(c["target_id"] == "all" for c in configs3)
            watched_items = {c["target_id"] for c in configs3 if c["target_id"] != "all"}

            for item_label, ranked in breakdown.items():
                if not ranked:
                    continue
                resolved = _resolve_resource(item_label)
                item_id  = resolved[0] if resolved else item_label.lower()

                if not watch_all and item_id not in watched_items:
                    continue

                new_top_pct = ranked[0][1]
                # Semua negara yang SERI di puncak (selisih <= epsilon = noise pembulatan).
                tied = [
                    (name, pct) for name, pct in ranked
                    if abs(pct - new_top_pct) <= BONUS_ALERT_EPSILON
                ]
                old = self._bonus_cache.get(item_id)

                # Belum ada baseline → simpan diam-diam, jangan alert (hindari spam saat start).
                if old is None:
                    if len(tied) == 1:
                        baseline = tied[0][0]
                    else:
                        baseline, _ = await self._resolve_bonus_top(item_label, tied)
                    await self._set_bonus_cache(item_id, baseline, new_top_pct)
                    continue

                old_country, old_pct = old

                # Top-1 lama masih di puncak (termasuk kalau negara lain ikut seri) → bukan
                # pergantian, jangan alert (hindari spam). Cache tetap pegang negara lama,
                # cuma pct-nya yang di-update.
                if any(name == old_country for name, _ in tied):
                    await self._set_bonus_cache(item_id, old_country, new_top_pct)
                    continue

                # Cari nilai TERKINI negara lama (kalau masih ada di top-N; kalau tidak, anggap 0).
                old_country_now_pct = next(
                    (pct for name, pct in ranked if name == old_country), 0.0
                )

                # Pengganti top-1. Kalau ada beberapa kandidat seri: durasi deposit terlama
                # (tanpa deposit = paling lama) → income tax terkecil → abjad.
                new_top_country, new_top_ends_at = await self._resolve_bonus_top(item_label, tied)

                targets = [c for c in configs3 if c["target_id"] in ("all", item_id)]
                for cfg in targets:
                    channel = self.bot.get_channel(int(cfg["channel_id"]))
                    if not channel:
                        continue
                    ping, embed = build_bonus_embed(
                        item_label=item_label,
                        old_country=old_country,
                        old_pct=old_pct,
                        old_country_now_pct=old_country_now_pct,
                        new_top_country=new_top_country,
                        new_top_pct=new_top_pct,
                        role_ping=cfg.get("role_ping"),
                        new_top_ends_at=new_top_ends_at,
                    )
                    try:
                        from .alert_mute import guarded_alert_send  # boot-fix: auto-mute guard
                        sent = await guarded_alert_send(channel, content=ping or None, embed=embed)
                        if sent is not None:
                            await self._queue_alert_delete(sent)
                    except Exception as exc:
                        log.warning(f"Bonus alert send: {exc}")

                await self._set_bonus_cache(item_id, new_top_country, new_top_pct)

        except Exception as exc:
            log.error(f"poll_bonus: {exc}", exc_info=True)

    async def _resolve_bonus_top(
        self, item_label: str, tied: list[tuple[str, float]]
    ) -> tuple[str, datetime | None]:
        """Pilih SATU negara top-1 dari kandidat yang seri + waktu berakhir deposit-nya
        (None kalau bonusnya tanpa deposit). Urutan penentu: durasi terlama (tanpa
        deposit = paling lama) → income tax terkecil (tax gagal diambil = paling akhir)
        → abjad, biar hasilnya selalu sama."""
        import market as mkt
        ends = (await mkt.fetch_bonus_deposit_ends(
            self._session, {item_label: tied}, with_cache=True
        )).get(item_label, {})
        names = [name for name, _pct in tied]

        def _dur(name: str) -> float:
            end = ends.get(name)
            return float("inf") if end is None else end.timestamp()

        if len(names) > 1:
            best = max(_dur(n) for n in names)
            names = [n for n in names if _dur(n) == best]
        if len(names) > 1:
            tax = await mkt.fetch_country_tax_breakdown(
                self._session, {item_label: [(n, 0.0) for n in names]}, with_cache=True
            )
            names.sort(key=lambda n: (tax[n] if tax.get(n) is not None else float("inf"), n))
        winner = names[0]
        return winner, ends.get(winner)

    @poll_bonus.before_loop
    async def _before_poll_bonus(self) -> None:
        await self.bot.wait_until_ready()