# visuals.py

from __future__ import annotations

import io
import logging
from typing import Optional

import discord

log = logging.getLogger("WarEraBot.visuals")


def generate_price_chart(
    name: str,
    data: list[dict],
    days: int,
) -> Optional[discord.File]:
    """Grafik harga + SMA, return discord.File. None kalau data kurang / gagal."""
    if not data or len(data) < 2:
        return None

    fig = None
    try:
        import pandas as pd
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        df = pd.DataFrame(data)
        df["recorded_at"] = pd.to_datetime(df["recorded_at"], utc=True)
        df = df.sort_values("recorded_at")
        df["price"] = df["price"].astype(float)
        window = max(2, len(df) // 5)
        df["sma"] = df["price"].rolling(window=window, min_periods=1).mean()

        with plt.style.context("dark_background"):
            fig, ax = plt.subplots(figsize=(10, 5), dpi=100)

            ax.plot(df["recorded_at"], df["price"], color="#00f2ff",
                    linewidth=2, label="Price", zorder=3)
            ax.fill_between(df["recorded_at"], df["price"],
                             df["price"].min() * 0.99,
                             color="#00f2ff", alpha=0.1)
            ax.plot(df["recorded_at"], df["sma"], color="#ff9900",
                    linestyle="--", alpha=0.7, label="Trend Avg")

            ax.set_title(f" {name} Market History ({days}d)",
                         fontsize=14, fontweight="bold", pad=20)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
            ax.grid(True, linestyle=":", alpha=0.1)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.legend(frameon=False)

            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            buf.seek(0)

            return discord.File(buf, filename="chart.png")

    except Exception as exc:
        log.error(f"generate_price_chart({name}): {exc}")
        return None

    finally:
        if fig is not None:
            try:
                import matplotlib.pyplot as plt
                plt.close(fig)
            except Exception:
                pass


def _safe_font(font_name: str, size: int):
    """Muat font TTF dari berbagai OS. Gagal -> default Pillow."""
    from PIL import ImageFont
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/{font_name}.ttf",
        f"/usr/share/fonts/truetype/liberation/{font_name}.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        f"C:\\Windows\\Fonts\\{font_name}.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        f"/Library/Fonts/{font_name}.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except IOError:
            continue
    return ImageFont.load_default()


def generate_orderbook_images(
    item_name: str,
    bids: list[dict],
    asks: list[dict],
    last_price: Optional[float] = None,
    rows_per_page: int = 20,
) -> list[discord.File]:
    """Order book bid kiri / ask kanan, bar proporsional ke qty. Paginasi rows_per_page baris."""
    if not bids and not asks:
        return []

    files: list[discord.File] = []
    try:
        from PIL import Image, ImageDraw

        def fmt(v: float, decimals: int = 5) -> str:
            return f"{v:,.{decimals}f}"

        total_rows = max(len(bids), len(asks))
        n_pages = max(1, -(-total_rows // rows_per_page))

        font_title = _safe_font("DejaVuSans-Bold", 20)
        font_header = _safe_font("DejaVuSans-Bold", 13)
        font_row = _safe_font("DejaVuSans", 13)
        font_footer_big = _safe_font("DejaVuSans-Bold", 24)
        font_footer_small = _safe_font("DejaVuSans", 12)

        for page_index in range(n_pages):
            start = page_index * rows_per_page
            page_bids = bids[start:start + rows_per_page]
            page_asks = asks[start:start + rows_per_page]
            n_rows = rows_per_page

            w = 980
            h = 140 + n_rows * 32 + (80 if page_index == 0 and last_price is not None else 20)
            bg, panel = (24, 29, 46), (30, 36, 58)
            img = Image.new("RGB", (w, h), bg)
            draw = ImageDraw.Draw(img)

            px1, py1, px2, py2 = 20, 20, w - 20, h - 20
            draw.rounded_rectangle([(px1, py1), (px2, py2)], radius=14, fill=panel)

            title = "Order Book" if page_index == 0 else f"Order Book (cont. page {page_index + 1})"
            draw.text((px1 + 30, py1 + 25), f"{title} — {item_name}", fill=(220, 224, 235), font=font_title)

            header_y = py1 + 65
            center_x = w // 2
            left_x = px1 + 30
            col_depth_w, col_size_w, col_price_w = 150, 130, 100

            bid_depth_x = left_x
            bid_size_x  = bid_depth_x + col_depth_w
            bid_price_x = bid_size_x + col_size_w + col_price_w
            bid_ord_x   = bid_price_x + 20

            ask_ord_x   = center_x + 20
            ask_price_x = ask_ord_x + 50 + 20
            ask_size_x  = ask_price_x + 110
            ask_depth_x = px2 - 30

            headers = [
                (bid_depth_x, "Depth", "left"), (bid_size_x, "Size", "left"),
                (bid_price_x, "Price", "right"), (bid_ord_x, "Ord", "left"),
                (ask_ord_x, "Ord", "left"), (ask_price_x, "Price", "left"),
                (ask_size_x, "Size", "left"), (ask_depth_x, "Depth", "right"),
            ]
            for x, label, align in headers:
                bbox = draw.textbbox((0, 0), label, font=font_header)
                tw = bbox[2] - bbox[0]
                tx = x - tw if align == "right" else x
                draw.text((tx, header_y), label, fill=(140, 148, 165), font=font_header)

            draw.line([(px1 + 20, header_y + 24), (px2 - 20, header_y + 24)], fill=(50, 56, 78))

            max_bid_qty = max((r["qty"] for r in page_bids), default=1) or 1
            max_ask_qty = max((r["qty"] for r in page_asks), default=1) or 1

            row_y = header_y + 34
            row_h = 32
            bid_bar_color, ask_bar_color = (16, 60, 52), (70, 24, 34)

            for i in range(n_rows):
                y = row_y + i * row_h
                bid = page_bids[i] if i < len(page_bids) else None
                ask = page_asks[i] if i < len(page_asks) else None

                if bid:
                    ratio = bid["qty"] / max_bid_qty
                    bar_x0 = bid_price_x - int((bid_price_x - bid_size_x) * ratio)
                    draw.rectangle([(bar_x0, y), (bid_price_x, y + row_h - 4)], fill=bid_bar_color)
                    draw.text((bid_depth_x, y + 6), fmt(bid["cumQty"], 0), fill=(210, 214, 224), font=font_row)
                    draw.text((bid_size_x, y + 6), fmt(bid["qty"], 0), fill=(210, 214, 224), font=font_row)
                    price_txt = fmt(bid["price"], 4)
                    bbox = draw.textbbox((0, 0), price_txt, font=font_row)
                    draw.text((bid_price_x - (bbox[2] - bbox[0]), y + 6), price_txt,
                              fill=(60, 220, 150), font=font_row)
                    draw.text((bid_ord_x, y + 6), fmt(bid.get("count", 1), 0),
                              fill=(150, 155, 178), font=font_row)

                if ask:
                    ratio = ask["qty"] / max_ask_qty
                    bar_max_w = ask_depth_x - ask_price_x
                    bar_x1 = ask_price_x + int(bar_max_w * ratio)
                    draw.rectangle([(ask_price_x, y), (bar_x1, y + row_h - 4)],
                                   fill=ask_bar_color)
                    draw.text((ask_ord_x, y + 6), fmt(ask.get("count", 1), 0),
                              fill=(150, 155, 178), font=font_row)
                    draw.text((ask_price_x, y + 6), fmt(ask["price"], 4), fill=(230, 90, 100), font=font_row)
                    draw.text((ask_size_x, y + 6), fmt(ask["qty"], 0), fill=(210, 214, 224), font=font_row)
                    total_txt = fmt(ask["cumQty"], 0)
                    bbox = draw.textbbox((0, 0), total_txt, font=font_row)
                    draw.text((ask_depth_x - (bbox[2] - bbox[0]), y + 6), total_txt,
                              fill=(210, 214, 224), font=font_row)

            draw.line([(center_x, header_y + 30), (center_x, row_y + n_rows * row_h - 4)], fill=(60, 66, 88))

            if page_index == 0 and last_price is not None:
                fy = py2 - 55
                draw.line([(px1 + 20, fy - 10), (px2 - 20, fy - 10)], fill=(50, 56, 78))
                txt = fmt(last_price, 4)
                bbox = draw.textbbox((0, 0), txt, font=font_footer_big)
                draw.text(((w - (bbox[2] - bbox[0])) / 2, fy), txt, fill=(60, 220, 150), font=font_footer_big)
                label = "Last Market Price"
                bbox2 = draw.textbbox((0, 0), label, font=font_footer_small)
                draw.text(((w - (bbox2[2] - bbox2[0])) / 2, fy + 32), label,
                          fill=(140, 148, 165), font=font_footer_small)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            files.append(discord.File(buf, filename=f"orderbook_p{page_index + 1}.png"))

        return files

    except Exception as exc:
        log.error(f"generate_orderbook_images({item_name}): {exc}", exc_info=True)
        return []


# --- donation leaderboard (background custom + kolom dinamis 1-4) ---

_DONATION_BG_PATH = "assets/donation_bg.png"
_donation_bg_cache = None

_DON_CONTENT_LEFT   = 150
_DON_CONTENT_RIGHT  = 1520
_DON_CONTENT_TOP    = 205
_DON_CONTENT_BOTTOM = 858
_DON_COL_GAP        = 50

_DON_TAB_CENTER_X = 830
_DON_TITLE_Y      = 62
_DON_SUBTITLE_Y   = 128
_DON_COL_HDR_Y    = 172

_DON_RANK_COLOR = {1: (255, 215, 0), 2: (205, 205, 215), 3: (205, 127, 50)}
_DON_ROW_COLOR  = (225, 225, 230)
_DON_GOLD       = (255, 205, 60)
_DON_MUTED      = (185, 188, 198)

_DON_FONT_BY_COLS  = {1: 20, 2: 18, 3: 16}
_DON_TRUNC_BY_COLS = {1: 26, 2: 20, 3: 16}
_DON_ROW_H_MIN = 20
_DON_ROW_H_MAX = 48


def _load_donation_bg():
    """Background donasi di-cache di RAM, baca disk sekali. Return copy (mutable)."""
    global _donation_bg_cache
    from PIL import Image
    if _donation_bg_cache is None:
        _donation_bg_cache = Image.open(_DONATION_BG_PATH).convert("RGB")
    return _donation_bg_cache.copy()


def generate_donation_image(
    country_name: str,
    subtitle: str,
    columns: list[tuple[str, list[tuple[int, str, str, Optional[str]]]]],
    filename: str = "donation.png",
) -> Optional[discord.File]:
    """Leaderboard donasi di atas donation_bg.png, kolom dinamis 1-3."""
    if not columns:
        return None
    columns = columns[:3]

    try:
        from PIL import ImageDraw

        img = _load_donation_bg()
        draw = ImageDraw.Draw(img)

        font_title   = _safe_font("DejaVuSans-Bold", 30)
        font_sub     = _safe_font("DejaVuSans-Bold", 22)
        font_col_hdr = _safe_font("DejaVuSans-Bold", 16)

        n_cols     = len(columns)
        row_font_sz = _DON_FONT_BY_COLS.get(n_cols, 13)
        name_trunc  = _DON_TRUNC_BY_COLS.get(n_cols, 11)
        font_row    = _safe_font("DejaVuSans", row_font_sz)

        title_txt = f"DONATION TRACKER: {country_name.upper()}"
        bbox = draw.textbbox((0, 0), title_txt, font=font_title)
        draw.text((_DON_TAB_CENTER_X - (bbox[2] - bbox[0]) // 2, _DON_TITLE_Y),
                  title_txt, font=font_title, fill=_DON_GOLD)

        W, _ = img.size
        bbox = draw.textbbox((0, 0), subtitle, font=font_sub)
        draw.text(((W - (bbox[2] - bbox[0])) // 2, _DON_SUBTITLE_Y), subtitle,
                  font=font_sub, fill=_DON_MUTED)

        content_w = _DON_CONTENT_RIGHT - _DON_CONTENT_LEFT
        col_w     = (content_w - _DON_COL_GAP * (n_cols - 1)) // n_cols

        max_rows_used = max((len(rows) for _, rows in columns), default=1) or 1
        content_h = _DON_CONTENT_BOTTOM - _DON_CONTENT_TOP
        row_h = max(_DON_ROW_H_MIN, min(_DON_ROW_H_MAX, content_h // max_rows_used))

        for idx, (header, rows) in enumerate(columns):
            col_x0 = _DON_CONTENT_LEFT + idx * (col_w + _DON_COL_GAP)

            draw.text((col_x0, _DON_COL_HDR_Y), header,
                      font=font_col_hdr, fill=_DON_GOLD)

            for i, (rank, name, amount, pct) in enumerate(rows):
                y = _DON_CONTENT_TOP + i * row_h
                if y + row_h > _DON_CONTENT_BOTTOM + row_h:
                    break
                color = _DON_RANK_COLOR.get(rank, _DON_ROW_COLOR)

                draw.text((col_x0, y), f"{rank}.", font=font_row, fill=color)
                draw.text((col_x0 + 34, y), name[:name_trunc], font=font_row, fill=color)

                right_edge = col_x0 + col_w
                if pct is not None:
                    pct_txt = f"({pct})"
                    pbb = draw.textbbox((0, 0), pct_txt, font=font_row)
                    draw.text((right_edge - (pbb[2] - pbb[0]), y), pct_txt,
                              font=font_row, fill=_DON_MUTED)
                    right_edge -= (pbb[2] - pbb[0]) + 12

                amt_txt = f"{amount}g"
                abb = draw.textbbox((0, 0), amt_txt, font=font_row)
                draw.text((right_edge - (abb[2] - abb[0]), y), amt_txt,
                          font=font_row, fill=color)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return discord.File(buf, filename=filename)

    except Exception as exc:
        log.error(f"generate_donation_image({country_name}): {exc}", exc_info=True)
        return None

