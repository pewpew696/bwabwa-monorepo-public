# services/spy/naming.py — helper normalisasi nama untuk matching (diekstrak 28 Sep 2026)

from __future__ import annotations


# --- normalisasi nama ---

def norm_name(text: str) -> str:
        """Normalisasi buat bandingin nama: lowercase + spasi dirapikan."""
        return " ".join((text or "").strip().lower().split())

def name_variants(nama: str) -> list[str]:
        """Query pertama = input apa adanya. Kalau ada spasi, tambah maks 2 query
        ulang (spasi -> `_`, spasi -> `-`) — dipakai HANYA kalau belum ada nama
        yang persis sama. Username WarEra sering pakai `_` atau `-`."""
        nama = nama.strip()
        variants = [nama]
        if " " in nama:
            variants += [nama.replace(" ", "_"), nama.replace(" ", "-")]
        return variants
