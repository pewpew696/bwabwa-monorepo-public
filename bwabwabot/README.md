# Bwabwabot

Discord bot untuk game WarEra (warera.io) — fetch data market dan intel perang, dengan web dashboard.

Prefix: x atau X
Dashboard: https://sulkybwabwabwa.cloud
API: https://api.sulkybwabwabwa.cloud

## Fitur

### Ekonomi & Market
- xitem — harga & info item
- xprofit — kalkulasi profit produksi
- xob — orderbook
- xmarket — overview market
- xhistory — history harga
- xtop — top mover
- xfairprice — estimasi harga wajar
- xequipment — harga equipment
- xdonation — laporan donasi

### Spy & Recon
- xspy player — dossier pemain
- xspy mu — info MU
- xspy country — info negara
- xspy trade — trade profile
- xspy check — cek perusahaan

### Alert
- xalert add/list/remove/test — alert otomatis

### Admin
- xadmin, xannounce, xaddadmin, xremoveadmin, xaddimage, xremoveimage, xreload, xdebug

### Simulator
- Web /simulator — simulator produksi & profit

## Tech Stack

- Python 3.12 + discord.py
- aiohttp untuk HTTP async
- Flask + waitress untuk web API
- PostgreSQL 17 lokal (app_db)
- Supabase untuk storage foto + backup
- YugabyteDB untuk backup pasif
- Nginx + Let's Encrypt + systemd

## Struktur

- main.py — entry point bot
- market.py — WarEra API client
- hub_intel.py — endpoint dashboard
- db_pool.py — PostgreSQL pool
- cogs/ — modul command Discord (economy, spy, alert, admin)
- core/ — shared utilities
- web_api/ — Flask blueprint per route
- simulator/ — mesin simulator produksi

## Setup

1. Clone + venv + pip install -r requirements.txt
2. Copy .env.example ke .env, isi semua key
3. Setup PostgreSQL lokal + user bot_app
4. python3 main.py

## Deploy Systemd

Unit: /etc/systemd/system/bwabwabot.service
- User: ubuntu
- WorkingDirectory: /path/to/bwabwabot
- ExecStart: /usr/bin/python3 main.py
- Restart: always

Perintah: sudo systemctl restart bwabwabot

## Reverse-Sync

Script di /opt/db-migration/reverse-sync/:
- dump_daily.sh — dump app_db (cron 02:00)
- push_target.sh supabase — push ke Supabase (03:00)
- push_target.sh yb — push ke YugabyteDB (03:30)
- watchdog.sh — cek heartbeat (tiap 30 menit)

Kill-switch: SYNC_ENABLED=0 di /etc/environment
