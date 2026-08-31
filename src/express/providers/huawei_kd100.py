"""Huawei Cloud marketplace express API — 快递100/百递云 (深圳前海百递网络有限公司).

Purchased at Huawei Cloud Marketplace (商品编号 af4f963a-0894-4aa3-860d-acab425267e7
/ OFFI1000695969623982080): 快递100实时查询接口文档-华为云.

Auth REUSES the Huawei APIG APP signature (SDK-HMAC-SHA256) from
``providers/huawei_jm.py``, but this product lives on its own gateway:

    POST https://kdapi.apistore.huaweicloud.com/poll/channelquery.do?param=<json>

``param`` is a URL-QUERY JSON string::

    {"com": "<kuaidi100 lowercase>", "num": "<waybill>",
     "phone": "<receiver/sender phone; SF/丰网 required>", "resultv2": "1"}

``com`` uses kuaidi100 lowercase codes ("shunfeng", "zhongtong", "jtexpress", ...);
``"auto"`` lets the API auto-detect the courier (recommended).

Response::

    {"message": "ok", "nu": "...", "com": "jtexpress", "ischeck": "0",
     "state": "0", "status": "200", "condition": "00",
     "data": [{"time": "...", "ftime": "...", "context": "...",
               "areaCode": "...", "areaName": "...", "status": "派件"}]}

``state``: 0在途 1揽收 2疑难 3签收 4退签 5派件 8清关 14拒签.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

import httpx

from express.models import CompanyHint, TrackingEvent, TrackResult
from express.providers._common import infer_status_from_events, parse_time
from express.providers._guess import _guess_companies as _local_guess
from express.providers.base import ProviderError, register
from express.providers.huawei_jm import HuaweiSigner, _url_encode
from express.status import extract_location, to_en_status
from express.validation import normalize_phone_tail

API_HOST = "kdapi.apistore.huaweicloud.com"
API_PATH = "/poll/channelquery.do"
API_URL = f"https://{API_HOST}{API_PATH}"

# Internal (juhe style) lowercase code -> kuaidi100 ``com`` code.
_TO_KD100: dict[str, str] = {
    "sf": "shunfeng",
    "shunfeng": "shunfeng",
    "zto": "zhongtong",
    "zhongtong": "zhongtong",
    "yto": "yuantong",
    "yuantong": "yuantong",
    "yt": "yuantong",
    "yunda": "yunda",
    "yd": "yunda",
    "sto": "shentong",
    "shentong": "shentong",
    "jd": "jd",
    "ems": "ems",
    "jtexpress": "jtexpress",
    "jt": "jtexpress",
    "jitu": "jtexpress",
}

# kuaidi100 ``com`` back to an internal lowercase code (single canonical form).
_FROM_KD100: dict[str, str] = {
    "shunfeng": "sf",
    "sf": "sf",
    "zhongtong": "zto",
    "yuantong": "yt",
    "yunda": "yunda",
    "shentong": "sto",
    "jd": "jd",
    "ems": "ems",
    "jtexpress": "jtexpress",
}

# state code -> display status (English, matching the rest of the app).
_STATE_MAP: dict[str, str] = {
    "0": "In Transit",
    "1": "Picked Up",
    "2": "Exception",
    "3": "Delivered",
    "4": "Returned",
    "5": "Out for Delivery",
    "8": "In Transit",
    "14": "Returned",
}


def _to_kd100_code(company: Optional[str]) -> str:
    c = (company or "").strip().lower()
    return _TO_KD100.get(c, "")


def _from_kd100_code(code: Optional[str]) -> str:
    return _FROM_KD100.get((code or "").lower(), (code or "").lower())


# 顺丰/丰网 need the receiver-or-sender phone (kuaidi100 accepts last-4).
_REQUIRES_PHONE: set[str] = {"shunfeng", "sf", "fengwang", "sf_express"}


@register("huawei_kd100")
class HuaweiKd100Provider:
    """Huawei Cloud marketplace express API — 快递100/百递云 (paid, per-call)."""

    name = "huawei_kd100"

    def __init__(self, app_key: str = "", app_secret: str = "", timeout: float = 20.0):
        self.app_key = app_key.strip()
        self.app_secret = app_secret.strip()
        self.timeout = timeout
        self._signer = HuaweiSigner(self.app_key, self.app_secret)

    def detect_company(self, tracking_number: str) -> list[CompanyHint]:
        hints = _local_guess(tracking_number)
        out: list[CompanyHint] = []
        for h in hints:
            code = _to_kd100_code(h.code)
            ken = _from_kd100_code(code) or h.code
            if ken and not any(x.code == ken for x in out):
                out.append(CompanyHint(code=ken, name=h.name or ken))
        return out

    def _headers(self, params: dict[str, Any], body: str = "") -> dict[str, str]:
        x_date, auth = self._signer.sign("POST", API_PATH, params, body, host=API_HOST)
        return {
            "Host": API_HOST,
            "X-Sdk-Date": x_date,
            "Authorization": auth,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "express-tracker/0.2",
        }

    def _raise_error(self, payload: dict[str, Any]) -> None:
        # Successful envelope; nothing to raise.
        if payload.get("status") == "200" and payload.get("message") == "ok":
            return
        # Error envelope (e.g. {"returnCode": "500", "message": "..."}).
        msg = str(payload.get("message") or payload.get("error_msg") or "")
        code = str(payload.get("returnCode") or payload.get("status") or "")
        if payload.get("result") is False:
            raise ProviderError(f"Kuaidi100 (HuaweiCloud): {msg} (returnCode={code})")
        if msg:
            raise ProviderError(f"Kuaidi100 (HuaweiCloud) error {code}: {msg}")
        raise ProviderError(f"Kuaidi100 (HuaweiCloud) error: {payload}")

    def track(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        com = _to_kd100_code(company) or "auto"

        param: dict[str, Any] = {"com": com, "num": tracking_number, "resultv2": "1"}
        # 顺丰/丰网 need the receiver-or-sender phone (kuaidi100 takes last-4).
        if com in _REQUIRES_PHONE or phone:
            tail = normalize_phone_tail(phone)
            if tail:
                param["phone"] = tail

        param_json = self._json_dumps(param)
        # ``param`` travels as a URL query param, so it must be url-encoded the
        # same way the signer encodes canonical query values (safe='~').
        enc = _url_encode(param_json)
        url = f"{API_URL}?param={enc}"

        try:
            resp = httpx.post(
                url,
                headers=self._headers({"param": param_json}),
                timeout=self.timeout,
            )
            try:
                payload = resp.json()
            except ValueError:
                payload = None
        except httpx.HTTPError as exc:
            raise ProviderError(f"Kuaidi100 (HuaweiCloud) request failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderError(
                f"Invalid Kuaidi100 (HuaweiCloud) response: {(resp.text if resp else '')[:200]}"
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

    @staticmethod
    def _json_dumps(obj: Any) -> str:
        import json

        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
