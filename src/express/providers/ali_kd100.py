"""Aliyun Cloud Marketplace express API — 快递100/百递云 (AppCode auth).

Product: 快递物流轨迹查询单号识别时效预估服务
  https://market.aliyun.com/detail/cmapi00053347  (yuncode47347000010 / ...021)

Same kuaidi100 poll API as ``providers/huawei_kd100.py``, but served by the
Aliyun Cloud Marketplace gateway (``kdapi.kuaidi100.com``) and authenticated
with the simple AppCode header instead of a Huawei APIG APP signature::

    GET https://kdapi.kuaidi100.com/poll/query?num=<waybill>&com=<com>[&phone=<tail>][&resultv2=1]

Auth:  Authorization: APPCODE <appCode>

``com`` uses kuaidi100 lowercase codes ("shunfeng", "zhongtong", "jtexpress",
...); ``"auto"`` lets the API auto-detect the courier. ``phone`` is the
receiver/sender last-4 (顺丰/中通/跨越 need it).

The Aliyun product serves the query at ``/test/poll/query`` (the console
sample path); ``/poll/query`` returns 404 on this gateway.

Response (kuaidi100 poll envelope)::

    {"message": "ok", "nu": "...", "com": "jtexpress", "ischeck": "0",
     "state": "0", "status": "200", "condition": "00",
     "data": [{"time": "...", "ftime": "...", "context": "...",
               "areaCode": "...", "areaName": "...", "status": "派件"}]}

``state``: 0在途 1揽收 2疑难 3签收 4退签 5派件 8清关 14拒签.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from express.models import CompanyHint, TrackingEvent, TrackResult
from express.providers._common import infer_status_from_events, parse_time
from express.providers._guess import _guess_companies as _local_guess
from express.providers.base import ProviderError, register
from express.providers.huawei_kd100 import (
    _REQUIRES_PHONE,
    _STATE_MAP,
    _from_kd100_code,
    _to_kd100_code,
)
from express.status import extract_location, to_en_status
from express.validation import normalize_phone_tail

API_HOST = "kdapi.kuaidi100.com"
# The Aliyun product exposes the kuaidi100 poll query at this exact path
# (verified live: ``/poll/query`` returns 404, ``/test/poll/query`` returns data).
API_PATH = "/test/poll/query"
API_URL = f"https://{API_HOST}{API_PATH}"


@register("ali_kd100")
class AliKd100Provider:
    """Aliyun Cloud Marketplace 快递100/百递云 express API (AppCode auth)."""

    name = "ali_kd100"

    def __init__(self, app_code: str = "", timeout: float = 20.0):
        self.app_code = (app_code or "").strip()
        self.timeout = timeout

    def detect_company(self, tracking_number: str) -> list[CompanyHint]:
        hints = _local_guess(tracking_number)
        out: list[CompanyHint] = []
        for h in hints:
            code = _to_kd100_code(h.code)
            ken = _from_kd100_code(code) or h.code
            if ken and not any(x.code == ken for x in out):
                out.append(CompanyHint(code=ken, name=h.name or ken))
        return out

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"APPCODE {self.app_code}",
            "User-Agent": "express-tracker/0.2",
            "Accept": "application/json",
        }

    def _require_code(self) -> None:
        if not self.app_code:
            raise ProviderError(
                "ali_kd100 needs an Aliyun Cloud Marketplace AppCode. "
                "Set [ali_kd100] app_code in ~/.express/config.toml "
                "(or EXPRESS_ALI_KD100_APPCODE)"
            )

    def _raise_error(self, payload: dict[str, Any]) -> None:
        # Successful envelope; nothing to raise.
        if payload.get("status") == "200" and payload.get("message") == "ok":
            return
        # Error envelope (e.g. {"returnCode": "500", "message": "..."}).
        msg = str(payload.get("message") or payload.get("error_msg") or "")
        code = str(payload.get("returnCode") or payload.get("status") or "")
        if payload.get("result") is False:
            raise ProviderError(f"Kuaidi100 (AliyunCloud): {msg} (returnCode={code})")
        if msg:
            raise ProviderError(f"Kuaidi100 (AliyunCloud) error {code}: {msg}")
        raise ProviderError(f"Kuaidi100 (AliyunCloud) error: {payload}")

    def track(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        self._require_code()
        com = _to_kd100_code(company) or "auto"

        params: dict[str, str] = {"num": tracking_number, "com": com, "resultv2": "1"}
        # 顺丰/丰网 need the receiver-or-sender phone (kuaidi100 takes last-4).
        if com in _REQUIRES_PHONE or phone:
            tail = normalize_phone_tail(phone)
            if tail:
                params["phone"] = tail

        try:
            resp = httpx.get(
                API_URL,
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
            try:
                payload = resp.json()
            except ValueError:
                payload = None
        except httpx.HTTPError as exc:
            raise ProviderError(f"Kuaidi100 (AliyunCloud) request failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderError(
                f"Invalid Kuaidi100 (AliyunCloud) response: {(resp.text if resp else '')[:200]}"
            )

        self._raise_error(payload)

        raw_traces = payload.get("data") or []
        events: list[TrackingEvent] = []
        if isinstance(raw_traces, list):
            for item in raw_traces:
                if not isinstance(item, dict):
                    continue
                description = str(item.get("context") or "").strip()
                area = str(item.get("areaName") or "").strip()
                when = parse_time(str(item.get("time") or item.get("ftime") or ""))
                events.append(
                    TrackingEvent(
                        time=when,
                        description=description,
                        location=area or extract_location(description),
                        status=to_en_status(str(item.get("status") or "")),
                    )
                )

        events.sort(key=lambda e: e.time, reverse=True)

        # Prefer the API's explicit ``state``; fall back to event inference.
        state = str(payload.get("state") or "")
        status_text = _STATE_MAP.get(state) or infer_status_from_events(events)
        # ``ischeck`` = 1 means signed, even if state is missing.
        if str(payload.get("ischeck")) == "1":
            status_text = "Delivered"
        status_text = to_en_status(status_text)

        resolved_com = _from_kd100_code(str(payload.get("com") or com)) or com
        current = events[0] if events else None

        return TrackResult(
            tracking_number=str(payload.get("nu") or tracking_number),
            company_code=resolved_com,
            company_name=resolved_com,
            status=status_text,
            status_code=state,
            current=current,
            events=events,
            raw=payload,
        )
