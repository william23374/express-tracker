"""ALAPI (alapi.cn) express API — free tier with real tracking data.

Docs: https://www.alapi.cn
- Endpoint: https://v2.alapi.cn/api/kd
- Params: token (required), number (required), com (optional, kuaidi100-style)
- Free tier: daily quota per token; the kd interface may require membership
  (error 10012) depending on account level.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from express.models import CompanyHint, TrackingEvent, TrackResult
from express.providers.base import ProviderError, register
from express.providers._common import infer_status_from_events, parse_time
from express.status import extract_location, to_en_status

API_URL = "https://v2.alapi.cn/api/kd"

# Internal (juhe-style) code -> ALAPI com code (kuaidi100-style)
_TO_ALAPI: dict[str, str] = {
    "sf": "shunfeng",
    "shunfeng": "shunfeng",
    "nsf": "shunfeng",
    "fengwang": "shunfeng",
    "zto": "zhongtong",
    "zhongtong": "zhongtong",
    "yt": "yuantong",
    "yuantong": "yuantong",
    "yto": "yuantong",
    "sto": "shentong",
    "shentong": "shentong",
    "yd": "yunda",
    "yunda": "yunda",
    "ems": "ems",
    "jd": "jd",
    "jtexpress": "jtexpress",
    "jt": "jtexpress",
    "jitu": "jtexpress",
    "db": "debangwuliu",
    "debangwuliu": "debangwuliu",
    "ht": "huitongkuaidi",
    "huitongkuaidi": "huitongkuaidi",
    "baishi": "huitongkuaidi",
    "tt": "tiantian",
    "tiantian": "tiantian",
    "kuayue": "kuayue",
    "ky": "kuayue",
}

# ALAPI com code -> internal code
_FROM_ALAPI: dict[str, str] = {
    "shunfeng": "sf",
    "zhongtong": "zto",
    "yuantong": "yt",
    "shentong": "sto",
    "yunda": "yd",
    "ems": "ems",
    "jd": "jd",
    "jtexpress": "jtexpress",
    "debangwuliu": "db",
    "huitongkuaidi": "ht",
    "tiantian": "tt",
    "kuayue": "kuayue",
}

# ALAPI deliverystatus values
_STATUS_MAP = {
    "0": "Picked Up",  # 揽件
    "1": "In Transit",  # 在途中
    "2": "Out for Delivery",  # 正在派件
    "3": "Delivered",  # 已签收
    "4": "Exception",  # 派送失败
    "5": "Exception",  # 疑难件
    "6": "Returned",  # 退件签收
}

# ALAPI platform error codes
_ERROR_HINTS = {
    "10001": "token missing",
    "10002": "token invalid",
    "10003": "account unavailable",
    "10004": "kd interface not subscribed — apply first at alapi.cn",
    "10005": "remaining quota exhausted — recharge at alapi.cn",
    "10008": "token disabled",
    "10009": "token has no kd interface permission",
    "10010": "daily quota exhausted — upgrade at alapi.cn",
    "10012": "member-only interface — upgrade membership at alapi.cn",
    "10011": "interface temporarily unavailable",
}


def _normalize_com(company: str) -> str:
    c = (company or "").strip().lower()
    return _TO_ALAPI.get(c, c)


@register("alapi")
class AlapiProvider:
    """ALAPI express API — free account with daily query quota."""

    name = "alapi"

    def __init__(self, key: str = "", timeout: float = 20.0):
        self.key = (key or "").strip()
        self.timeout = timeout

    def _require_key(self) -> None:
        if not self.key:
            raise ProviderError(
                "ALAPI token missing. Get one at https://www.alapi.cn then set "
                "[alapi] key in ~/.express/config.toml (or EXPRESS_ALAPI_TOKEN)"
            )

    def _raise_api_error(self, payload: dict[str, Any]) -> None:
        code = str(payload.get("code") or "")
        message = str(payload.get("message") or payload)
        hint = _ERROR_HINTS.get(code)
        if code in ("10005", "10010"):
            raise ProviderError(
                f"ALAPI daily quota exhausted ({code}): {message}. "
                "Wait for reset or upgrade at alapi.cn"
            )
        if code == "429":
            raise ProviderError("ALAPI rate limit (429) — wait a few seconds.")
        if code == "10012":
            raise ProviderError(
                f"ALAPI kd requires membership ({code}): {message}. "
                "Upgrade at alapi.cn, or remove alapi from provider_chain."
            )
        raise ProviderError(f"ALAPI error {code}: {message or hint or payload}")

    def detect_company(self, tracking_number: str) -> list[CompanyHint]:
        # ALAPI has no free auto-detect endpoint; use local heuristics.
        from express.providers._guess import _guess_companies

        hints: list[CompanyHint] = []
        for h in _guess_companies(tracking_number):
            if not any(x.code == h.code for x in hints):
                hints.append(h)
        return hints

    def track(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        self._require_key()
        params: dict[str, str] = {"number": tracking_number, "token": self.key}
        if company:
            params["com"] = _normalize_com(company)

        try:
            resp = httpx.get(API_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ALAPI request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError(f"Invalid ALAPI response: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderError(f"Unexpected ALAPI response: {payload!r}")

        if not payload.get("success"):
            self._raise_api_error(payload)

        data = payload.get("data")
        if not isinstance(data, dict):
            # Success with no data = no records found
            raise ProviderError(
                f"ALAPI: no tracking data for {tracking_number}"
                + (f" ({params.get('com')})" if params.get("com") else "")
            )

        raw_list = data.get("list") or []
        events: list[TrackingEvent] = []
        if isinstance(raw_list, list):
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                desc = str(item.get("status") or "").strip()
                if not desc:
                    continue
                events.append(
                    TrackingEvent(
                        time=parse_time(str(item.get("time") or "")),
                        description=desc,
                        location=extract_location(desc),
                        status="",
                    )
                )

        events.sort(key=lambda e: e.time, reverse=True)
        state = str(data.get("deliverystatus") or "")
        status_text = _STATUS_MAP.get(state, "")
        status_text = infer_status_from_events(events, status_text)
        status_text = to_en_status(status_text)
        current = events[0] if events else None

        resolved_code = _FROM_ALAPI.get(
            str(data.get("type") or "").lower(),
            _FROM_ALAPI.get(_normalize_com(company or ""), company or ""),
        )
        if not resolved_code:
            resolved_code = str(data.get("type") or company or "")
        company_name = str(
            data.get("expName") or data.get("typename") or resolved_code
        )

        return TrackResult(
            tracking_number=str(data.get("number") or tracking_number),
            company_code=resolved_code,
            company_name=company_name,
            status=status_text,
            status_code=state,
            current=current,
            events=events,
            raw=payload,
        )
