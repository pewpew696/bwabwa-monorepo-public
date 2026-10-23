"""Query Intel: pengguna aktif dalam jendela waktu (dari web_identities)."""
from webapp.core.database import fetch_dicts, web_session

ACTIVE_WINDOW_MINUTES = 15

ACTIVE_USERS_SQL = """
SELECT name, last_seen_at
FROM web_identities
WHERE last_seen_at >= now() - make_interval(mins => %s)
ORDER BY last_seen_at DESC
"""


def get_active_users(minutes: int = ACTIVE_WINDOW_MINUTES) -> list[dict]:
    with web_session() as cursor:
        cursor.execute(ACTIVE_USERS_SQL, (minutes,))
        return fetch_dicts(cursor)
