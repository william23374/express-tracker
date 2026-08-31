"""Local heuristics for courier detection — no external API required.

Shared by providers that lack a dedicated auto-detect endpoint (apizero, alapi).
Returns juhe-style internal company codes.
"""

from __future__ import annotations

import re

from express.models import CompanyHint


def _guess_companies(tracking_number: str) -> list[CompanyHint]:
    """Guess possible couriers from a tracking-number pattern (best first)."""
    n = tracking_number.strip().upper()
    hints: list[CompanyHint] = []

    def add(code: str, name: str) -> None:
        if not any(h.code == code for h in hints):
            hints.append(CompanyHint(code=code, name=name))

    # Prefix rules first (strong signals) — JT/SF/JD before digit heuristics
    if n.startswith("JT") or re.match(r"^JT\d+", n):
        add("jtexpress", "极兔速递")
    if n.startswith("SF") or re.match(r"^SF\d+", n):
        add("sf", "顺丰")
    if n.startswith("JD") or re.match(r"^JD[A-Z0-9]+", n):
        add("jd", "京东")
    if re.match(r"^YT\d+", n):
        add("yt", "圆通")
    if re.match(r"^ZTO\d+", n) or (
        n.isdigit() and (n.startswith("75") or n.startswith("78"))
    ):
        add("zto", "中通")
    if re.match(r"^STO\d+", n) or (n.isdigit() and n.startswith("77")):
        add("sto", "申通")
    if n.startswith("YD") or (n.isdigit() and re.match(r"^43\d+", n)):
        add("yd", "韵达")
    if re.match(r"^(EA|EB|EC|ED|EE|EF)\d+CN$", n) or "EMS" in n:
        add("ems", "EMS")

    # Length-based soft guesses for pure digit numbers
    if n.isdigit():
        length = len(n)
        if length == 12:
            add("zto", "中通")
            add("sto", "申通")
            add("yt", "圆通")
        elif length == 13:
            add("yt", "圆通")
            add("yd", "韵达")
        elif length == 14:
            add("sf", "顺丰")
            add("yd", "韵达")
        elif length == 15:
            add("yt", "圆通")
            add("zto", "中通")

    if not hints:
        # No confident guess — caller must pass -c <com>
        return []
    return hints
