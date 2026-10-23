"""
Dijalankan pytest otomatis SEBELUM collect/import test module manapun.

1. Mastiin root project ada di sys.path, biar modul kayak
   'cogs.economy.base' bisa di-import pakai dotted path.
2. Kasih dummy env var buat config yang biasanya cuma keisi asli di
   VPS (Discord token, Supabase, DB) — supaya modul yang baca
   os.environ pas import-time (module-level client init) gak langsung
   crash di test_imports.py.

PENTING: nilai di bawah CUMA buat lolos import, BUKAN buat dipakai
jalan beneran (jangan pernah connect ke Supabase/DB asli pakai ini).
setdefault dipakai supaya kalau env asli udah di-export duluan
(misal pas jalan manual di VPS), nilai asli itu yang menang.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DUMMY_ENV = {
    "WEB_API_KEY": "dummy-web-api-key",
    "JWT_SECRET": "dummy-jwt-secret",
    "DISCORD_TOKEN": "dummy-discord-token",
    "SUPABASE_URL": "https://dummy.supabase.co",
    "SUPABASE_KEY": "dummy-supabase-key",
    "SUPABASE_STORAGE_URL": "https://dummy.supabase.co/storage/v1",
    "SUPABASE_STORAGE_KEY": "dummy-supabase-storage-key",
    "APP_DB_HOST": "localhost",
    "APP_DB_PORT": "5432",
    "APP_DB_DBNAME": "dummy_db",
    "APP_DB_USER": "dummy_user",
    "APP_DB_PASSWORD": "dummy_password",
}

for _key, _val in _DUMMY_ENV.items():
    os.environ.setdefault(_key, _val)
