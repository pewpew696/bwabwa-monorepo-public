"""Query tabel web_identities (identitas perangkat)."""
from webapp.core.database import fetch_dicts, web_session


def get_identity(identity_id: str) -> dict | None:
    with web_session() as cursor:
        cursor.execute(
            "SELECT id, name, created_at, last_seen_at "
            "FROM web_identities WHERE id = %s",
            (identity_id,),
        )
        rows = fetch_dicts(cursor)
    return rows[0] if rows else None


def insert_identity(identity_id: str, name: str) -> None:
    with web_session(commit=True) as cursor:
        cursor.execute(
            "INSERT INTO web_identities (id, name, created_at) "
            "VALUES (%s, %s, now())",
            (identity_id, name),
        )


def touch_identity(
    identity_id: str,
    device_info: str,
    last_ip: str,
    min_interval_seconds: int,
) -> None:
    """Satu UPDATE; hanya menulis bila last_seen_at kosong atau sudah lewat interval."""
    with web_session(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE web_identities
               SET last_seen_at = now(), device_info = %s, last_ip = %s
             WHERE id = %s
               AND (last_seen_at IS NULL
                    OR last_seen_at < now() - make_interval(secs => %s))
            """,
            (device_info, last_ip, identity_id, min_interval_seconds),
        )
