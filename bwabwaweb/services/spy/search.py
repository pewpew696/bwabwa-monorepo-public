# services/spy/search.py — cari player & MU exact (diekstrak 28 Sep 2026)

from __future__ import annotations

import asyncio

from services.spy.api_client import api_get, get_mu, get_user_lite, search_user_ids
from services.spy.naming import name_variants, norm_name


# --- search ---

async def find_player_exact(session, nama: str) -> tuple[dict | None, list[str]]:
        """Cari player yang username-nya PERSIS sama dengan input (case-insensitive).
        Return (data_user_lite, saran). Ketemu persis -> (data, []). Gak ada yang
        persis (atau ada 2+ yang persis) -> (None, nama-nama yang ketemu, maks 5).
        Search API cuma balikin 5 player & urutannya gak sesuai kemiripan, jadi
        hasil pertama TIDAK boleh langsung dipercaya."""
        target = norm_name(nama)
        seen: dict[str, dict] = {}
        for query in name_variants(nama):
            user_ids = await search_user_ids(session, query)
            new_ids = [uid for uid in user_ids if uid not in seen]
            fetched = await asyncio.gather(*[get_user_lite(session, uid) for uid in new_ids])
            for uid, d in zip(new_ids, fetched):
                if d:
                    d.setdefault("_id", uid)
                    seen[uid] = d
            exact = [d for d in seen.values() if norm_name(d.get("username", "")) == target]
            if len(exact) == 1:
                return exact[0], []
            if exact:
                break
        names = list(dict.fromkeys(d.get("username", "?") for d in seen.values()))
        return None, names[:5]


async def search_mu(session, query: str) -> tuple[tuple[str, str] | None, list[str]]:
        """Cari MU. Return ((mu_id, nama_mu), saran). Prioritas: nama PERSIS sama
        (case-insensitive); kalau gak ada, nama dengan kata yang sama tapi urutan
        beda ("akatsuki clan" ~ "Clan Akatsuki"), hanya kalau tepat 1 MU. Selain
        itu (None, saran). Input ID 24-hex tetap dipakai apa adanya (jalur lama)."""
        if len(query) == 24 and all(c in "0123456789abcdef" for c in query):
            return (query, query[:8] + "..."), []
        target = norm_name(query)
        target_words = sorted(target.split())
        seen: dict[str, str] = {}
        exact: list[tuple[str, str]] = []
        for q in name_variants(query):
            data = await api_get(session, "search.searchAnything", {"searchText": q})
            mu_ids = (data or {}).get("muIds", [])
            new_ids = [mid for mid in mu_ids if mid not in seen]
            fetched = await asyncio.gather(*[get_mu(session, mid) for mid in new_ids])
            for mid, m in zip(new_ids, fetched):
                if m:
                    seen[mid] = m.get("name", "")
            exact = [(mid, n) for mid, n in seen.items() if norm_name(n) == target]
            if len(exact) == 1:
                return exact[0], []
            if exact:
                break
        if not exact:
            reordered = [
                (mid, n) for mid, n in seen.items()
                if sorted(norm_name(n).split()) == target_words
            ]
            if len(reordered) == 1:
                return reordered[0], []
        names = list(dict.fromkeys(n for n in seen.values() if n))
        return None, names[:5]
