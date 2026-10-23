"""
cogs/spy/api/__init__.py — "data layer" SpyCog: semua pemanggilan WarEra API +
Supabase (company index, wealth reconciliation, tax estimate). Tidak ada
command Discord atau embed-building di sini — murni fetch & compute data
mentah, dipakai oleh player.py / mu.py / country.py / check.py.

Dipecah dari api.py (dulu 1 file 1175 baris) jadi package: tiap kelompok
method jadi mixin terpisah, digabung di sini via multiple inheritance —
pola yang SAMA seperti SpyCog sendiri menggabungkan PlayerMixin/MuMixin/dst
di cogs/spy/__init__.py. Interface publik (`from .api import ApiMixin` dan
`from .api import _bot_admin_check`) TIDAK BERUBAH — semua file lain di
package spy/ tetap jalan tanpa modifikasi.

ApiMixin (gabungan) diasumsikan dipakai bareng commands.Cog (butuh self.bot,
dan _session dari sana — didefinisikan di CompanyScanMixin).
"""

from __future__ import annotations

from discord.ext import commands

from .company_scan import CompanyScanMixin
from .inventory import InventoryMixin
from .snapshots import SnapshotMixin
from .companies import CompanyDataMixin
from .wealth import WealthMixin


async def _bot_admin_check(ctx: commands.Context) -> bool:
    """Sama seperti AdminCog._is_admin: pakai tabel bot_admins + OWNER_ID,
    BUKAN izin `administrator` bawaan Discord — supaya konsisten dengan
    xadmin dan seluruh command admin-only lainnya.
    Delegasi ke core.permissions.is_bot_admin (satu implementasi terpusat)."""
    from core.permissions import is_bot_admin
    return await is_bot_admin(ctx.author.id)


class ApiMixin(
    CompanyScanMixin,
    InventoryMixin,
    SnapshotMixin,
    CompanyDataMixin,
    WealthMixin,
):
    """Mixin gabungan — expects self.bot, self._session dari
    class final (SpyCog di __init__.py). Lihat masing-masing sub-mixin untuk
    detail method per kelompok fungsi."""
    pass
