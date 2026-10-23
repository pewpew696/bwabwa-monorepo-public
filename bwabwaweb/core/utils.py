"""
core/utils.py — Helper UI Discord terpusat (dipindah dari 5 lokasi duplikat).
"""

from __future__ import annotations

from datetime import datetime

import discord


def make_embed(title: str, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
    e = discord.Embed(title=title, color=color)
    e.set_footer(text=f"bwabwabwa  •  {datetime.now().strftime('%H:%M:%S')}")
    return e

from discord.ext import commands as _commands_for_exc


class ChannelNotAllowed(_commands_for_exc.CheckFailure):
    """Raised saat command diketik di channel yang gak di-allowlist
    (cogs/channels.py). Ditaruh di core/utils.py (bukan main.py) supaya
    identitas class-nya konsisten dimanapun diimport — main.py dijalankan
    sebagai __main__, jadi `from main import X` dari file lain bikin
    re-import terpisah main.py sebagai modul "main", menghasilkan class
    duplikat yang beda identitas dari `isinstance()`."""
    pass

# --- formatter ---

def _display_name(raw: str) -> str:
    """Ubah underscore jadi spasi dan title case untuk tampilan."""
    return raw.replace("_", " ").title()
