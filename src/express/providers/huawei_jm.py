"""Huawei Cloud marketplace express API (聚美智数 / 杭州安那其科技).

Purchased at Huawei Cloud Marketplace: 快递查询【最新版】.
Auth: Huawei APIG APP signature — SDK-HMAC-SHA256 (X-Sdk-Date + Authorization).
The signing algorithm below is implemented to match the official
``huaweicloudsdkcore.signer`` implementation (verified against the live API).

Request:  POST https://expressqueryv2.apistore.huaweicloud.com/express/query-v2
Query params: number (tracking number), expressCode (UPPERCASE courier code),
              mobile (receiver phone; some couriers like ZTO need the FULL number),
              sort (optional, "1").
Response: {"data": {...}, "msg": "...", "success": bool, "code": int, "taskNo": "..."}
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import urllib.parse
from typing import Any, Optional

import httpx

from express.models import CompanyHint, TrackingEvent, TrackResult
from express.providers.base import ProviderError, register
from express.providers._common import infer_status_from_events
from express.providers._guess import _guess_companies as _local_guess
from express.status import extract_location, to_en_status
from express.validation import normalize_phone_tail

API_HOST = "expressqueryv2.apistore.huaweicloud.com"
API_PATH = "/express/query-v2"
API_URL = f"https://{API_HOST}{API_PATH}"

# Huawei's APIG sdk uses this constant for an empty request body.
_EMPTY_HASH = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
_ALGO = "SDK-HMAC-SHA256"
_BASIC_DATE_FORMAT = "%Y%m%dT%H%M%SZ"

# Internal lowercase courier code -> Huawei uppercase code.
_TO_HW: dict[str, str] = {
    "sf": "SF",
    "kd": "KD",
    "kuayue": "KD",
    "ky": "KD",
    "shunfeng": "SF",
    "zto": "ZTO",
    "zhongtong": "ZTO",
    "yto": "YTO",
    "yuantong": "YTO",
    "yt": "YTO",
    "yunda": "YD",
    "yd": "YD",
    "sto": "STO",
    "shentong": "STO",
    "jd": "JD",
    "ems": "EMS",
    "jt": "JT",
    "jtexpress": "JT",
    "jitu": "JT",
}

# Huawei uppercase code -> internal lowercase code (kept consistent with the rest
# of the app, whose stored company codes are lowercase like "zto" / "jt").
_FROM_HW: dict[str, str] = {
    "SF": "sf",
    "KD": "kd",
    "ZTO": "zto",
    "YTO": "yto",
    "YD": "yunda",
    "STO": "sto",
    "JD": "jd",
    "EMS": "ems",
    "JT": "jt",
}

_STATUS_MAP = {
    "ACCEPT": "Picked Up",
    "COLLECT": "Picked Up",
    "TRANSPORT": "In Transit",
    "ON_THE_WAY": "In Transit",
    "DELIVERING": "Out for Delivery",
    "SIGN": "Delivered",
    "FAILED": "Exception",
    "RETURN": "Returned",
}


def _to_hw_code(company: Optional[str]) -> str:
    c = (company or "").strip().lower()
    return _TO_HW.get(c, c.upper())


# Couriers for which Huawei Cloud requires the FULL receiver phone; for the
# others only the last-4 is enough. The provider picks automatically.
_FULL_PHONE_COURIERS = {"ZTO", "SF", "KD"}


def _needs_full_phone(courier_code: Optional[str]) -> bool:
    return _to_hw_code(courier_code) in _FULL_PHONE_COURIERS


def _from_hw_code(code: Optional[str]) -> str:
    return _FROM_HW.get((code or "").upper(), (code or "").lower())


def _url_encode(value: Any) -> str:
    # Huawei's signer only keeps '~' unencoded.
    return urllib.parse.quote(str(value), safe="~")


class HuaweiSigner:
    """Minimal reimplementation of Huawei APIG SDK-HMAC-SHA256 request signing."""

    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret

    def _canonical_uri(self, path: str) -> str:
        parts = [_url_encode(p) for p in urllib.parse.unquote(path).split("/")]
        uri = "/".join(parts)
        if uri[-1] != "/":
            uri += "/"
        return uri

    def _canonical_query(self, params: dict[str, Any]) -> str:
        items = sorted(params.items())
        return "&".join(
            f"{_url_encode(k)}={_url_encode(v)}" for k, v in items
        )

    def _canonical_headers(self, host: str, x_sdk_date: str) -> str:
        return f"host:{host}\nx-sdk-date:{x_sdk_date}\n"

    def _canonical_request(
        self, method: str, path: str, params: dict[str, Any], body: str, host: str
    ) -> str:
        hashed_payload = (
            hashlib.sha256(body.encode()).hexdigest() if body else _EMPTY_HASH
        )
        return "\n".join(
            [
                method.upper(),
                self._canonical_uri(path),
                self._canonical_query(params),
                self._canonical_headers(host, self.x_sdk_date),
                "host;x-sdk-date",
                hashed_payload,
            ]
        )

    def sign(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        body: str = "",
        host: str = API_HOST,
    ) -> tuple[str, str]:
        """Return (x-sdk-date, Authorization) for the given request."""
        x_sdk_date = datetime.datetime.now(datetime.timezone.utc).strftime(
            _BASIC_DATE_FORMAT
        )
        self.x_sdk_date = x_sdk_date
        canonical = self._canonical_request(method, path, params, body, host)
        string_to_sign = "%s\n%s\n%s" % (
            _ALGO,
            x_sdk_date,
            hashlib.sha256(canonical.encode()).hexdigest(),
        )
        signature = hmac.new(
            self.app_secret.encode(), string_to_sign.encode(), hashlib.sha256
        ).hexdigest()
        auth = "SDK-HMAC-SHA256 Access=%s, SignedHeaders=host;x-sdk-date, Signature=%s" % (
            self.app_key,
            signature,
        )
        return x_sdk_date, auth


@register("huawei_jm")
class HuaweiProvider:
    """Huawei Cloud marketplace express API (paid, per-call)."""

    name = "huawei_jm"

    def __init__(self, app_key: str = "", app_secret: str = "", timeout: float = 20.0):
        self.app_key = app_key.strip()
        self.app_secret = app_secret.strip()
        self.timeout = timeout
        self._signer = HuaweiSigner(self.app_key, self.app_secret)

    def detect_company(self, tracking_number: str) -> list[CompanyHint]:
        hints = _local_guess(tracking_number)
        out: list[CompanyHint] = []
        for h in hints:
            code = _to_hw_code(h.code)
            if code and not any(x.code == code for x in out):
                out.append(CompanyHint(code=code, name=h.name or code))
        return out

    def _headers(self, params: dict[str, Any], body: str = "") -> dict[str, str]:
        x_date, auth = self._signer.sign("POST", API_PATH, params, body)
        return {
            "Host": API_HOST,
            "X-Sdk-Date": x_date,
            "Authorization": auth,
            "Content-Type": "application/json",
            "User-Agent": "express-tracker/0.2",
        }

    def _raise_error(
        self,
        payload: dict[str, Any],
        tracking_number: str,
        company_code: Optional[str],
        phone: Optional[str],
    ) -> None:
        code = payload.get("code")
        msg = str(payload.get("msg") or "")
        if code == 411:
            raise ProviderError(
                f"HuaweiCloud: {msg} — unsupported courier code '{company_code}'."
                " Add its mapping in providers/huawei_jm.py (_TO_HW)."
            )
        if code == 412:
            raise ProviderError(
                f"HuaweiCloud: {msg} — tracking number {tracking_number} doesn't "
                f"match courier {company_code} (check the C code / number)."
            )
        if any(k in msg for k in ("手机", "mobile", "尾号", "phone")):
            tail = normalize_phone_tail(phone) or "????"
            raise ProviderError(
                f"HuaweiCloud: {msg} (got ***{tail}). SF/KD/ZTO need the receiver's "
                "OR sender's phone (full or last-4) matching the waybill. "
                "Update: MODIFY:NUMBER/P<full-phone>"
            )
        raise ProviderError(f"HuaweiCloud error {code}: {msg}")

    def track(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        company_code = _to_hw_code(company)
        # ZTO / SF need the FULL receiver phone; the rest accept last-4.
        if _needs_full_phone(company_code):
            mobile = (phone or "").strip()
        else:
            mobile = normalize_phone_tail(phone) or ""

        params: dict[str, str] = {
            "number": tracking_number,
            "expressCode": company_code,
            "mobile": mobile,
            "sort": "1",
        }

        try:
            resp = httpx.post(
                API_URL,
                params=params,
                headers=self._headers(params),
                timeout=self.timeout,
            )
            try:
                payload = resp.json()
            except ValueError:
                payload = None
        except httpx.HTTPError as exc:
            raise ProviderError(f"HuaweiCloud request failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderError(
                f"Invalid HuaweiCloud response: {(resp.text if resp else '')[:200]}"
            )

        if not payload.get("success"):
            self._raise_error(payload, tracking_number, company_code, phone)

        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("number"):
            # success but no result (e.g. code 701 "未查询到快递物流数据")
            return TrackResult(
                tracking_number=tracking_number,
                company_code=_from_hw_code(company_code) or company_code or "",
                company_name=data.get("expressCompanyName", "")
                if isinstance(data, dict)
                else "",
                status="Unknown",
                status_code=str(payload.get("code", "701")),
                current=None,
                events=[],
                raw=payload,
            )

        resolved_code = _from_hw_code(str(data.get("expressCode") or company_code))
        company_name = str(data.get("expressCompanyName") or resolved_code)
        status_desc = str(data.get("logisticsStatusDesc") or "")
        status_key = str(data.get("logisticsStatus") or "")

        raw_traces = data.get("logisticsTraceDetails") or []
        events: list[TrackingEvent] = []
        if isinstance(raw_traces, list):
            for item in raw_traces:
                if not isinstance(item, dict):
                    continue
                ts = int(item.get("time") or 0)
                when = (
                    datetime.datetime.fromtimestamp(ts / 1000)
                    if ts > 0
                    else datetime.datetime.now()
                )
                description = str(item.get("desc") or "").strip()
                area = str(item.get("areaName") or "").strip()
                events.append(
                    TrackingEvent(
                        time=when,
                        description=description,
                        location=area or extract_location(description),
                        status=_STATUS_MAP.get(
                            str(item.get("logisticsStatus") or ""), ""
                        ),
                    )
                )

        events.sort(key=lambda e: e.time, reverse=True)
        status_text = infer_status_from_events(events, status_desc or status_key)
        status_text = to_en_status(status_text)
        current = events[0] if events else None

        return TrackResult(
            tracking_number=str(data.get("number") or tracking_number),
            company_code=resolved_code or company_code or "",
            company_name=company_name,
            status=status_text,
            status_code=status_key,
            current=current,
            events=events,
            raw=payload,
        )
