"""
cogs/spy/constants.py — semua konstanta yang dipakai SpyCog.

Dipisah dari __init__.py murni buat readability: __init__.py isinya logic/command,
file ini isinya angka/tabel yang gampang di-tweak tanpa scroll ratusan baris.
"""

from __future__ import annotations

from core.permissions import OWNER_ID

# ITEM_EMOJI dipindah ke services/economy/constants.py (session 29 Sep).
# Re-export biar caller lama (player.py, check.py, country.py) tetap jalan.
from services.economy.constants import ITEM_EMOJI  # noqa: F401

# Pill ATK bonus
PILL_BONUS = 0.60

# --- xspy check v2 — rekonsiliasi wealth pakai ledger transaksi asli ---
GOLD_TX_TYPES = {"wage", "trading", "itemMarket", "donation", "articleTip", "battleLoot"}
ITEM_ONLY_TX_TYPES = {"openCase", "craftItem", "dismantleItem"}
UNRESOLVED_TX_TYPES = {"applicationFee"}

CASE_REWARD_MAX_GOLD = 75.0
CASE_OPEN_QUEST_LIMIT_PER_WEEK = 10

TX_PAGE_LIMIT = 100
TX_MAX_PAGES = 50

COMPANY_SCAN_INTERVAL_HOURS = 12  # diturunkan dari 3 jam (lihat catatan migrasi
# storage company_index -> app_db, Agustus 2026): scan ini SEKARANG cuma
# demi data agregat region/negara (xspy country, web API halaman negara,
# estimasi pajak negara) -- akurasi xspy player SUDAH ditangani terpisah lewat
# market.fetch_and_cache_user_companies (on-demand per user), tidak lagi
# bergantung pada scan berjadwal ini. Data region company jarang berubah &
# worker_count/production di fitur2 itu memang cuma estimasi kasar, jadi
# refresh 2x/hari (bukan 8x/hari) cukup & motong beban API 75%.
COMPANY_STALE_DAYS = 30  # company yang gak ke-"sentuh" (updated_at) scan manapun selama
# lebih dari ini dianggap udah dijual/dibubarkan di game, dibersihin otomatis. 30 hari
# dipilih biar scan gak perlu buru-buru nutupin seluruh company tiap siklus — data gak
# gampang kosong walau scan berjalan bertahap/nyicil. Trade-off: company yang BENERAN
# udah dijual bisa nyangkut sampai 30 hari sebelum kehapus dari cache.
# --- deteksi company mati lebih cepat (is_full stale) ---
COMPANY_FULL_STALE_DAYS = 3  # company is_full=True yang updated_at-nya lebih tua dari
# ini = kandidat kuat mati/dibongkar (pabrik yang masih jalan biasanya is_full=False
# atau ke-update di scan). Diproses task terpisah (lihat interval di bawah) yang
# verifikasi langsung ke API sebelum hapus, jadi false positive tetep aman.
COMPANY_FULL_STALE_BATCH = 500  # maks kandidat is_full-stale per putaran verifikasi
# --- refresh prioritas company yang datanya berubah ---
COMPANY_PRIORITY_SCAN_INTERVAL_HOURS = 6  # task loop buat (1) verifikasi kandidat
# is_full-stale di atas, sekaligus (2) nomor cadangan kalau daftar prioritas
# item_code/region_id berubah sempat numpuk — daftar prioritas sendiri diproses
# tiap cycle refresh_company_index (12 jam) di refresh_company_index.
COMPANY_PRIORITY_BATCH = 1000  # maks company prioritas (item/region berubah) per cycle
TAX_ESTIMATE_MAX_COMPANIES = 150
WORKER_FETCH_CONCURRENCY = 8
ENERGY_HOURS_PER_DAY = 24
CLICK_ENERGY_COST = 10

# xspy player halaman 2 — Companies Owned / AE Slot Status
COMPANY_PRODUCTION_MAX_ROWS = 30

# Perkiraan total company di game — cuma buat tampilan persentase progress di
# `xspy scan` (bukan angka pasti dari API, gak ada endpoint buat itu). Update
# manual kalau ternyata meleset jauh dari total aktual yang kekumpul.
COMPANY_ESTIMATED_TOTAL = 100_000

# --- lapisan aktivitas pemain (21 Sept 2026) ---
PLAYER_ACTIVE_DAYS = 3             # 'aktif' utama = pemilik login <= 3 hari
PLAYER_ACTIVE_DAYS_WIDE = 30       # angka pembanding
PLAYER_ACTIVITY_INTERVAL_MIN = 10  # jeda antar putaran refresh
PLAYER_ACTIVITY_BATCH_OWNERS = 3000  # maks pemilik per putaran (= 60 request batch)
PLAYER_ACTIVITY_BOOT_DELAY_S = 300   # tunda putaran pertama setelah boot

# --- refresh company per-owner (pengganti scan company lama, 22 Sept 2026) ---
COMPANY_OWNER_REFRESH_INTERVAL_MIN = 180  # tiap 3 jam
COMPANY_OWNER_REFRESH_LOOKBACK_MIN = 190  # jendela login (sedikit > interval, jaga-jaga telat jalan)
COMPANY_OWNER_REFRESH_BATCH_OWNERS = 500  # maks pemilik diproses per putaran
COMPANY_OWNER_REFRESH_BOOT_DELAY_S = 300  # tunda putaran pertama setelah boot
