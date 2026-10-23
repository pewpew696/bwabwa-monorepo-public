# services/spy/trade.py — hitung win rate trading (FIFO) (diekstrak 28 Sep 2026)

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone, timedelta

log = logging.getLogger("WarEraBot.trade")


# --- trade win rate ---

async def fetch_trade_winrate(session, user_id: str, days: int | None = None) -> dict:
        """
        Ambil seluruh histori transactionType="trading" milik user_id (paginate
        penuh, delay 0.5s/halaman biar ramah rate-limit gateway warerastats),
        lalu FIFO-match beli<->jual per item buat hitung win rate & profit.

        Definisi 1 "closed trade" = 1 transaksi jual yang berhasil dicocokkan
        ke >=1 batch beli sebelumnya (FIFO, item sama). Kalau jual tidak punya
        cost basis sama sekali di histori yang ke-fetch (item didapat dari
        sumber lain: produksi/gift/beli sebelum histori kita capture penuh),
        baris itu di-skip dari FIFO win-rate tapi tetap dihitung di total
        volume sell mentah -- supaya "Total Volume" tetap representatif walau
        "Closed Trades" cuma nangkep yang bisa dibuktikan untung/rugi-nya.

        Return dict:
          win_rate, closed_trades, wins, losses, net_profit,
          total_buy_qty, total_sell_qty, total_volume,
          best_item (label, profit), worst_item (label, profit),
          first_trade_at, last_trade_at, active_days,
          pages_fetched, capped
        """
        import market as mkt

        # sync dulu (cuma ambil tx baru sejak checkpoint terakhir -- kalau
        # udah pernah di-sync sebelumnya ini praktis no-op/cepat), baru baca
        # seluruh histori "trading" milik user dari cache app_db. Cache
        # ini dipakai bareng xspy pl & hub_intel C4 juga (sekali sync di
        # sini, dua fitur itu gak perlu fetch API sendiri lagi).
        try:
            sync_result = await mkt.sync_user_tx_incremental(session, user_id)
            capped = sync_result.get("capped", False)
        except Exception as exc:
            log.error(f"_fetch_trade_winrate: sync_user_tx_incremental gagal — {exc!r}, lanjut baca cache apa adanya.")
            capped = False

        # days (opsional): hanya transaksi N hari terakhir yang dibaca lalu di-FIFO.
        # Beli di luar rentang + jual di dalam rentang = tidak punya cost basis,
        # jadi di-skip dari closed trades (tetap masuk total_sell_qty).
        since_iso = None
        if days:
            since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        all_items = await mkt.get_user_tx_cache(user_id, tx_type="trading", since=since_iso)
        pages = 0  # gak relevan lagi (cache-based) -- tetap dikirim biar shape return gak berubah

        if not all_items:
            return {
                "win_rate": None, "closed_trades": 0, "wins": 0, "losses": 0,
                "net_profit": 0.0, "total_buy_qty": 0, "total_sell_qty": 0,
                "total_volume": 0, "best_item": None, "worst_item": None,
                "first_trade_at": None, "last_trade_at": None, "active_days": 0,
                "pages_fetched": pages, "capped": capped,
            }

        def _parse_dt(iso: str | None):
            if not iso:
                return None
            try:
                return datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except Exception:
                return None

        for it in all_items:
            it["_dt"] = _parse_dt(it.get("createdAt"))
        all_items = [it for it in all_items if it.get("itemCode") and it.get("quantity")]
        all_items.sort(key=lambda it: it["_dt"] or datetime.min.replace(tzinfo=timezone.utc))

        open_buys: dict[str, deque] = {}
        total_buy_qty = 0
        total_sell_qty = 0
        closed_trades = 0
        wins = 0
        net_profit = 0.0
        profit_by_item: dict[str, float] = {}
        first_dt = all_items[0]["_dt"]
        last_dt = all_items[-1]["_dt"]

        for it in all_items:
            item_code = it["itemCode"]
            qty = float(it["quantity"])
            money = float(it.get("money") or 0)
            price = money / qty if qty else 0.0
            is_buy = it.get("buyerId") == user_id
            is_sell = it.get("sellerId") == user_id

            if is_buy:
                total_buy_qty += qty
                open_buys.setdefault(item_code, deque()).append([qty, price])

            elif is_sell:
                total_sell_qty += qty
                queue = open_buys.get(item_code)
                if not queue:
                    continue

                matched_qty = 0.0
                cost_total = 0.0
                remaining = qty
                while remaining > 1e-9 and queue:
                    batch_qty, batch_price = queue[0]
                    take = min(batch_qty, remaining)
                    cost_total += take * batch_price
                    matched_qty += take
                    remaining -= take
                    batch_qty -= take
                    if batch_qty <= 1e-9:
                        queue.popleft()
                    else:
                        queue[0][0] = batch_qty

                if matched_qty <= 1e-9:
                    continue

                avg_cost = cost_total / matched_qty
                trade_profit = (price - avg_cost) * matched_qty

                closed_trades += 1
                net_profit += trade_profit
                profit_by_item[item_code] = profit_by_item.get(item_code, 0.0) + trade_profit
                if trade_profit > 0:
                    wins += 1

        losses = closed_trades - wins
        win_rate = (wins / closed_trades * 100) if closed_trades else None
        total_volume = total_buy_qty + total_sell_qty
        active_days = (last_dt - first_dt).days if (first_dt and last_dt) else 0

        best_item = max(profit_by_item.items(), key=lambda kv: kv[1]) if profit_by_item else None
        worst_item = min(profit_by_item.items(), key=lambda kv: kv[1]) if profit_by_item else None

        return {
            "win_rate": win_rate,
            "closed_trades": closed_trades,
            "wins": wins,
            "losses": losses,
            "net_profit": net_profit,
            "total_buy_qty": total_buy_qty,
            "total_sell_qty": total_sell_qty,
            "total_volume": total_volume,
            "best_item": best_item,
            "worst_item": worst_item,
            "first_trade_at": first_dt,
            "last_trade_at": last_dt,
            "active_days": active_days,
            "pages_fetched": pages,
            "capped": capped,
        }
