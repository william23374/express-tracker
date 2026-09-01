"""Shared provider helpers: datetime parsing and status inference.

Providers keep their own courier-code translation tables (each API uses
different codes), but the genuinely-reused logic lives here so it isn't
re-implemented per provider.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from express.models import TrackingEvent

# Format superset covering several providers.
DEFAULT_TIME_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
)


def parse_time(
    value: str, formats: Sequence[str] = DEFAULT_TIME_FORMATS
) -> datetime:
    """Parse a logistics timestamp string; fall back to now() on mismatch."""
    raw = (value or "").strip()
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return datetime.now()


def infer_status_from_events(
    events: Sequence[TrackingEvent],
    fallback: str = "",
    *,
    delivered: Sequence[str] = (
        "签收", "已签收", "妥投", "代签", "已取出", "投柜", "已代收", "delivered", "signed",
    ),
    out_for_delivery: Sequence[str] = ("派件", "派送", "快递员", "out for delivery", "delivering"),
    returned: Sequence[str] = ("退回", "退件", "拒签"),
    picked_up: Sequence[str] = ("揽收", "已收件", "取件", "已揽收", "picked", "collected"),
    in_transit: Sequence[str] = ("运输", "在途", "离开", "到达", "transit", "en route"),
    default: str = "In Transit",
) -> str:
    """Return the first matching status scanning newest-first; else fallback.

    Keyword sets are per-provider (each courier API words events slightly
    differently). Matching is case-insensitive so English keywords work too.
    """
    for ev in events:
        desc = (ev.description or "").lower()
        if any(k in desc for k in delivered):
            return "Delivered"
        if any(k in desc for k in out_for_delivery):
            return "Out for Delivery"
        if any(k in desc for k in returned):
            return "Returned"
        if any(k in desc for k in picked_up):
            return "Picked Up"
        if any(k in desc for k in in_transit):
            return "In Transit"
    return fallback or default
