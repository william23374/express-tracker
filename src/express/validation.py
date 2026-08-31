"""Validate tracking numbers before calling courier APIs."""

from __future__ import annotations

import re

from express.providers.base import ProviderError

# Full command → short aliases (2-letter etc.)
COMMAND_ALIASES: dict[str, tuple[str, ...]] = {
    "list": ("li", "ls"),
    "add": (),
    "track": ("tr",),
    "query": (),
    "status": ("st",),
    "history": ("hist",),
    "update": ("edit", "up"),
    "remove": ("rm",),
    "config": ("cf",),
    "providers": ("prov",),
    "use": ("provider",),
    "version": (),
    "help": (),
}

# Words that are CLI commands — never treat as tracking numbers
RESERVED_WORDS = frozenset(
    {
        "list",
        "li",
        "ls",
        "add",
        "track",
        "tr",
        "query",
        "status",
        "st",
        "history",
        "hist",
        "update",
        "edit",
        "up",
        "remove",
        "rm",
        "config",
        "cf",
        "providers",
        "prov",
        "use",
        "provider",
        "version",
        "help",
        "exit",
        "quit",
        "el",
    }
)

_ALIAS_TO_FULL = {
    alias: full
    for full, aliases in COMMAND_ALIASES.items()
    for alias in aliases
}
_ALIAS_TO_FULL.update({full: full for full in COMMAND_ALIASES})

# Juhe / common APIs: typically 6–32 alphanumerics (may include -)
_TRACK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{4,31}$")


def normalize_tracking_number(value: str) -> str:
    return (value or "").strip().upper().replace(" ", "")


def validate_tracking_number(value: str) -> str:
    """Return normalized tracking number or raise ProviderError."""
    raw = (value or "").strip()
    if not raw:
        raise ProviderError("Tracking number is empty")

    lower = raw.lower()
    if lower in RESERVED_WORDS:
        tip = _ALIAS_TO_FULL.get(lower, lower)
        raise ProviderError(
            f"'{raw}' is a command, not a tracking number. Try: el {tip.upper()}"
        )

    num = normalize_tracking_number(raw)
    if not _TRACK_RE.match(num):
        raise ProviderError(
            f"Invalid tracking number '{raw}'. "
            "Expected 5–32 alphanumeric chars (e.g. JT4006721151302). "
            "Usage: el QUERY:NUMBER (optional: C courier, P phone, H history)"
        )
    # Pure letters / short words are almost never valid waybills
    if num.isalpha() and len(num) < 8:
        raise ProviderError(
            f"Invalid tracking number '{raw}'. "
            "Usage: el QUERY:NUMBER (optional: C sf|yt|zto|jtexpress|..., P phone)"
        )
    return num


# Juhe docs: SF / ZTO / Kuayue need senderPhone or receiverPhone (last 4 digits).
# SF sub-brands (fengwang, nsf) follow the same rule on most aggregators.
PHONE_REQUIRED_COURIERS = frozenset(
    {
        "sf",
        "shunfeng",
        "nsf",  # 新顺丰
        "fengwang",  # 丰网速运 (SF family)
        "zto",
        "zhongtong",
        "kuayue",  # 跨越快递
        "ky",
    }
)

# Juhe API / error text hints that phone is missing or wrong
_PHONE_ERROR_MARKERS = (
    "204305",
    "手机",
    "电话",
    "尾号",
    "receiverPhone",
    "senderPhone",
    "验证码",  # Juhe returns this for SF/ZTO when phone is absent
)


def courier_requires_phone(company_code: str | None) -> bool:
    code = (company_code or "").strip().lower()
    return code in PHONE_REQUIRED_COURIERS


def is_phone_related_error(message: str) -> bool:
    return any(marker in (message or "") for marker in _PHONE_ERROR_MARKERS)


def normalize_phone_tail(phone: str | None) -> str:
    """Juhe wants last 4 digits of sender/receiver phone for SF/ZTO/etc."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 4:
        return digits[-4:]
    return digits


def require_phone_for_courier(company_code: str, phone: str | None) -> None:
    """Raise if courier needs phone but none was given."""
    if not courier_requires_phone(company_code):
        return
    if normalize_phone_tail(phone):
        return
    raise ProviderError(
        f"{company_code} requires phone last-4 digits. "
        f"Example: SAVE:NUMBER/C{company_code}/P13800138000"
    )


def phone_query_hint(
    tracking_number: str,
    company_code: str,
    phone: str | None,
    *,
    action: str = "SAVE",
) -> str:
    """User-facing hint when Juhe rejects phone verification."""
    tail = normalize_phone_tail(phone)
    if tail:
        return (
            f"Phone last-4 (***{tail}) may be wrong for {company_code}. "
            f"Use the receiver's mobile last 4 digits. "
            f"Update: {action}:{tracking_number}/C{company_code}/P{tail}"
        )
    return (
        f"{company_code} requires phone when adding. "
        f"Example: {action}:{tracking_number}/C{company_code}/P<last-4>"
    )
