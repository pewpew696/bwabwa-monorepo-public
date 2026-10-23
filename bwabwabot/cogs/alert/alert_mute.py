"""Auto-mute channel yang gagal kirim alert 403/50013 (Missing Permissions)
berturut-turut — supaya bot tidak spam log & buang kuota Discord tiap cycle."""
import time
import logging

import discord

log = logging.getLogger("WarEraBot.alert_mute")

_MUTE_AFTER_STREAK = 3
_MUTE_SECONDS = 3600.0
_fail_streak: dict[int, int] = {}
_muted_until: dict[int, float] = {}


def _is_muted(channel_id: int) -> bool:
    until = _muted_until.get(channel_id)
    return bool(until and time.monotonic() < until)


async def guarded_alert_send(channel, **kwargs):
    """Pengganti channel.send() khusus alert:
    - channel sedang di-mute -> return None (tidak kirim apa pun);
    - gagal karena Forbidden (403/50013) -> streak +1; 3x berturut-turut ->
      channel di-diamkan 1 jam (satu baris log, bukan spam per menit).
    Return Message yang terkirim, atau None kalau tidak terkirim —
    caller wajib handle None."""
    cid = channel.id
    if _is_muted(cid):
        return None
    try:
        sent = await channel.send(**kwargs)
        _fail_streak[cid] = 0
        return sent
    except discord.Forbidden as exc:
        streak = _fail_streak.get(cid, 0) + 1
        _fail_streak[cid] = streak
        if streak >= _MUTE_AFTER_STREAK:
            _muted_until[cid] = time.monotonic() + _MUTE_SECONDS
            log.warning(
                "alert auto-mute: channel %d di-diamkan %d menit setelah %dx gagal kirim (%s)",
                cid, int(_MUTE_SECONDS // 60), streak, exc,
            )
        else:
            log.warning("Alert send gagal (%dx berturut-turut): %s", streak, exc)
        return None
