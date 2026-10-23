"""Filter Jinja: format angka gaya WarEra (titik desimal, koma ribuan) dan waktu WIB."""

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

PLACEHOLDER = "—"
WIB_ZONE_NAME = "Asia/Jakarta"
PRICE_DECIMALS = 3
MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1440


@lru_cache(maxsize=1)
def _wib_zone() -> ZoneInfo:
    return ZoneInfo(WIB_ZONE_NAME)


def format_price(value: float | None) -> str:
    if value is None:
        return PLACEHOLDER
    return f"{value:,.{PRICE_DECIMALS}f}"


def format_amount(value: float | None) -> str:
    if value is None:
        return PLACEHOLDER
    return f"{value:,.0f}"


def format_percent(value: float | None, signed: bool = False) -> str:
    if value is None:
        return PLACEHOLDER
    rounded = round(float(value), 1)
    if rounded == 0:
        rounded = 0.0
    sign = "+" if signed and rounded > 0 else ""
    return f"{sign}{rounded:,.1f}%"


def format_wib(value: datetime | None) -> str:
    if value is None:
        return PLACEHOLDER
    return value.astimezone(_wib_zone()).strftime("%d/%m %H:%M") + " WIB"


def format_age(minutes: int | None) -> str:
    if minutes is None:
        return PLACEHOLDER
    if minutes < MINUTES_PER_HOUR:
        return f"{minutes} mnt"
    if minutes < MINUTES_PER_DAY:
        return f"{minutes // MINUTES_PER_HOUR} jam"
    return f"{minutes // MINUTES_PER_DAY} hari"


def trend_class(value: float | None) -> str:
    if value is None or round(float(value), 1) == 0:
        return ""
    return "is-up" if value > 0 else "is-down"




ITEM_ICON_BASE = "https://media.warera.io/images/items"

ITEM_ICON_CODE: dict[str, str] = {
    "Iron": "iron",
    "Grain": "grain",
    "Wood": "wood",
    "Oil": "oil",
    "Limestone": "limestone",
    "Lead": "lead",
    "Mysterious Plant": "coca",
    "Fish": "fish",
    "Livestock": "livestock",
    "Scraps": "scraps",
    "Steel": "steel",
    "Bread": "bread",
    "Paper": "paper",
    "Concrete": "concrete",
    "Petroleum": "petroleum",
    "Pill": "cocain",
    "Cooked Fish": "cookedFish",
    "Steak": "steak",
    "Ammo": "ammo",
    "Light Ammo": "lightAmmo",
    "Heavy Ammo": "heavyAmmo",
    "Case 1": "case1",
    "Case 2": "case2",
    "Wooden Case": "woodenCase",
}


def format_item_icon(label: str | None) -> str:
    if not label:
        return ""
    code = ITEM_ICON_CODE.get(label)
    if not code:
        return ""
    return f"{ITEM_ICON_BASE}/{code}.png"


FILTERS = {
    "price": format_price,
    "amount": format_amount,
    "percent": format_percent,
    "wib": format_wib,
    "age": format_age,
    "trend": trend_class,
    "item_icon": format_item_icon,
    # Alias nama panjang (dipakai template builder).
    "format_price": format_price,
    "format_amount": format_amount,
}
