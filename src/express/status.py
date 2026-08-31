"""Normalize logistics status labels to English for display."""

from __future__ import annotations

import re

# Canonical English statuses
IN_TRANSIT = "In Transit"
OUT_FOR_DELIVERY = "Out for Delivery"
DELIVERED = "Delivered"
PICKED_UP = "Picked Up"
EXCEPTION = "Exception"
RETURNED = "Returned"
UNKNOWN = "Unknown"

# 【深圳转运中心】 / [深圳市]
_BRACKET_LOC = re.compile(r"【([^】]{2,40})】")
_SQUARE_LOC = re.compile(r"\[([^\]]{2,40})\]")


def extract_location(text: str, fallback: str = "") -> str:
    """Pull place name from logistics text (e.g. 深圳转运中心 from 【深圳转运中心】)."""
    raw = (fallback or "").strip()
    if raw:
        return raw
    desc = text or ""
    m = _BRACKET_LOC.search(desc) or _SQUARE_LOC.search(desc)
    if not m:
        return ""
    loc = m.group(1).strip()
    # Skip non-place noise inside brackets
    if any(k in loc for k in ("952300", "电话", "投诉", "专属号码")):
        return ""
    return loc


_CN_TO_EN = {
    "在途": IN_TRANSIT,
    "运输中": IN_TRANSIT,
    "派件": OUT_FOR_DELIVERY,
    "派送": OUT_FOR_DELIVERY,
    "派送中": OUT_FOR_DELIVERY,
    "正在派件": OUT_FOR_DELIVERY,
    "签收": DELIVERED,
    "已签收": DELIVERED,
    "妥投": DELIVERED,
    "已完结": DELIVERED,
    "揽收": PICKED_UP,
    "收件": PICKED_UP,
    "疑难": EXCEPTION,
    "异常": EXCEPTION,
    "退签": RETURNED,
    "退回": RETURNED,
    "拒签": RETURNED,
}


def to_en_status(status: str) -> str:
    raw = (status or "").strip()
    if not raw:
        return UNKNOWN
    if raw in _CN_TO_EN:
        return _CN_TO_EN[raw]
    lower = raw.lower()
    # Already English / API codes
    mapping = {
        "pending": IN_TRANSIT,
        "en_route": IN_TRANSIT,
        "in transit": IN_TRANSIT,
        "delivering": OUT_FOR_DELIVERY,
        "out for delivery": OUT_FOR_DELIVERY,
        "signed": DELIVERED,
        "delivered": DELIVERED,
        "rejected": RETURNED,
        "return": RETURNED,
        "returen": RETURNED,
        "problem": EXCEPTION,
        "error": EXCEPTION,
        "no_record": UNKNOWN,
    }
    if lower in mapping:
        return mapping[lower]
    # Fuzzy Chinese fragments still in stored DB
    for cn, en in _CN_TO_EN.items():
        if cn in raw:
            return en
    if any(k in lower for k in ("deliver", "signed", "妥投")):
        return DELIVERED
    if any(k in lower for k in ("out for", "delivering")):
        return OUT_FOR_DELIVERY
    if any(k in lower for k in ("transit", "en_route", "route")):
        return IN_TRANSIT
    return raw
