"""Apizero (极数本源) express API — free tier with real tracking data.

Docs: https://apizero.cn/aidocs/express
- No API key: ~30 requests/day per IP
- With key: ~100 requests/day (register at apizero.cn)
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from express.models import CompanyHint, TrackingEvent, TrackResult
from express.providers.base import ProviderError, register
from express.providers._common import infer_status_from_events, parse_time
from express.providers._guess import _guess_companies as _local_guess
from express.status import to_en_status, extract_location
from express.validation import (
    courier_requires_phone,
    normalize_phone_tail,
    phone_query_hint,
)

API_URL = "https://v1.apizero.cn/api/express"

# Internal / Juhe codes -> Apizero com codes
_TO_APIZERO: dict[str, str] = {
    "sf": "sf",
    "shunfeng": "sf",
    "zto": "zto",
    "zhongtong": "zto",
    "yt": "yto",
    "yuantong": "yto",
    "yto": "yto",
    "sto": "sto",
    "shentong": "sto",
    "yd": "yunda",
    "yunda": "yunda",
    "jtexpress": "jt",
    "jt": "jt",
    "jitu": "jt",
    "jd": "jd",
    "ems": "ems",
    "db": "debang",
    "debangwuliu": "debang",
}

_STATUS_MAP = {
    "COLLECT": "Picked Up",
    "TRANSPORT": "In Transit",
    "TRANSIT": "In Transit",
    "DELIVERING": "Out for Delivery",
    "SIGN": "Delivered",
    "SIGNIN": "Delivered",
    "SIGNED": "Delivered",
    "DELIVERED": "Delivered",
    "EMPTY": "Unknown",
    "PROBLEM": "Exception",
    "RETURN": "Returned",
}


def _normalize_com(company: str) -> str:
    c = (company or "").strip().lower()
    return _TO_APIZERO.get(c, c)


@register("apizero")
class ApizeroProvider:
    """Apizero free express API (real data, daily quota)."""

    name = "apizero"

    def __init__(self, key: str = "", timeout: float = 20.0):
        self.key = key.strip()
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": "express-tracker/0.2",
            "Accept": "application/json",
        }
        if self.key:
            token = self.key if self.key.startswith("Bearer ") else f"Bearer {self.key}"
            headers["Authorization"] = token
        return headers

    def detect_company(self, tracking_number: str) -> list[CompanyHint]:
        local = _local_guess(tracking_number)
        hints: list[CompanyHint] = []
        for h in local:
            code = _normalize_com(h.code)
            if code and not any(x.code == code for x in hints):
                hints.append(CompanyHint(code=code, name=h.name or code))
        return hints

    def _raise_api_error(
        self,
        payload: dict[str, Any],
        tracking_number: str,
        phone: Optional[str] = None,
    ) -> None:
        code = int(payload.get("code", -1))
        msg = str(payload.get("msg") or payload)
        if code == 4030 or "今日免费额度" in msg or "额度已用完" in msg:
            raise ProviderError(
                "Apizero daily free quota exhausted (今日免费额度已用完). "
                "Wait until tomorrow, or buy more calls at https://apizero.cn"
            )
        if code == 4029:
            raise ProviderError("Apizero rate limit — wait a few seconds and retry.")
        if any(k in msg for k in ("手机", "尾号", "phone", "验证")) or code in (
            4000,
            400,
        ):
            tail = normalize_phone_tail(phone) or "????"
            raise ProviderError(
                f"Apizero: {msg} "
                f"(***{tail} rejected — Taobao/Pinduoduo often bind a privacy/"
                f"virtual number, not your real mobile last-4)"
            )
        raise ProviderError(f"Apizero error {code}: {msg}")

    def track(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        company_code = _normalize_com(company or "")
        phone_tail = normalize_phone_tail(phone) or None

        if company_code and courier_requires_phone(company_code) and not phone_tail:
            raise ProviderError(phone_query_hint(tracking_number, company_code, phone))

        params: dict[str, str] = {"number": tracking_number}
        if company_code:
            params["com"] = company_code
        if phone_tail:
            params["phone"] = phone_tail
        # Docs also accept key as query param (in addition to Bearer header)
        if self.key:
            raw_key = self.key.removeprefix("Bearer ").strip()
            params["key"] = raw_key

        try:
            payload = None
            last_http_err: Optional[Exception] = None
            for attempt in range(4):
                resp = httpx.get(
                    API_URL,
                    params=params,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                # Parse body even on 429 — 4030 = daily quota, not just QPS
                try:
                    payload = resp.json()
                except ValueError:
                    payload = None

                if resp.status_code == 429:
                    if isinstance(payload, dict) and int(payload.get("code", -1)) == 4030:
                        self._raise_api_error(payload, tracking_number, phone)
                    if attempt < 3:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    if isinstance(payload, dict) and payload.get("msg"):
                        self._raise_api_error(payload, tracking_number, phone)
                    raise ProviderError(
                        "Apizero rate limit (429) — too many requests. "
                        "Wait ~30s then retry."
                    )

                if isinstance(payload, dict) and resp.status_code >= 400:
                    if payload.get("msg") or payload.get("code") is not None:
                        if not company_code:
                            hints = self.detect_company(tracking_number)
                            if hints:
                                return self.track(
                                    tracking_number,
                                    company=hints[0].code,
                                    phone=phone,
                                )
                        self._raise_api_error(payload, tracking_number, phone)
                if resp.status_code >= 400:
                    last_http_err = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    if attempt < 3:
                        time.sleep(0.8 * (attempt + 1))
                        continue
                    raise ProviderError(
                        f"Apizero request failed: {last_http_err}"
                    ) from last_http_err
                break
            if not isinstance(payload, dict):
                raise ProviderError(
                    f"Invalid Apizero response: {(resp.text if resp else '')[:200]}"
                )
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(f"Apizero request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError(f"Invalid Apizero response: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderError(f"Unexpected Apizero response: {payload!r}")

        if int(payload.get("code", -1)) != 0:
            # Retry with explicit company from auto-detect hint
            if not company_code:
                hints = self.detect_company(tracking_number)
                if hints:
                    return self.track(
                        tracking_number,
                        company=hints[0].code,
                        phone=phone,
                    )
            self._raise_api_error(payload, tracking_number, phone)

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError(f"Apizero: no data — {payload.get('msg')}")

        resolved_code = _normalize_com(str(data.get("com") or company_code))
        company_name = str(data.get("com_name") or resolved_code)
        status_key = str(data.get("status") or "")
        status_desc = str(data.get("status_desc") or "")
        status_text = _STATUS_MAP.get(status_key, status_desc or status_key)

        raw_traces = data.get("traces") or []
        events: list[TrackingEvent] = []
        if isinstance(raw_traces, list):
            for item in raw_traces:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("content") or "").strip()
                events.append(
                    TrackingEvent(
                        time=parse_time(str(item.get("time") or "")),
                        description=content,
                        location=extract_location(content),
                        status="",
                    )
                )

        events.sort(key=lambda e: e.time, reverse=True)
        status_text = infer_status_from_events(events, status_text)
        status_text = to_en_status(status_text)
        current = events[0] if events else None

        return TrackResult(
            tracking_number=str(data.get("number") or tracking_number),
            company_code=resolved_code,
            company_name=company_name,
            status=status_text,
            status_code=status_key,
            current=current,
            events=events,
            raw=payload,
        )
