"""Akses DB webapp. Impor local_session ditunda supaya env webapp termuat dulu."""
from contextlib import contextmanager

from webapp.core.settings import get_settings


@contextmanager
def web_session(commit: bool = False):
    get_settings()
    from services.db.local import local_session

    with local_session(commit=commit) as cursor:
        yield cursor


def fetch_dicts(cursor) -> list[dict]:
    column_names = [column.name for column in cursor.description]
    return [dict(zip(column_names, row)) for row in cursor.fetchall()]
