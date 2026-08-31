"""Fallback provider — tries a chain of providers in order.

Switches to the next provider when one fails (quota exhausted, network
error, wrong company, no data). Phone-related failures are also retried
on other providers, but surfaced if every provider fails, so the user
still gets the phone last-4 hint.
"""

from __future__ import annotations

from typing import Optional

from express.models import CompanyHint, TrackResult
from express.providers.base import ProviderError, TrackingProvider, register
from express.validation import is_phone_related_error

# Hard validation errors — retrying other providers cannot help
_STOP_MARKERS = (
    "Invalid tracking",
    "is empty",
    "Unknown provider",
    "not a tracking number",
)


@register("fallback")
class FallbackProvider:
    """Try `providers` in order; the first success wins."""

    name = "fallback"

    def __init__(self, providers: Optional[list[TrackingProvider]] = None):
        self.providers = [
            p for p in (providers or []) if getattr(p, "name", "") != "mock"
        ]

    def detect_company(self, tracking_number: str) -> list[CompanyHint]:
        hints: list[CompanyHint] = []
        for prov in self.providers:
            try:
                for h in prov.detect_company(tracking_number):
                    if h.code and not any(x.code == h.code for x in hints):
                        hints.append(h)
            except ProviderError:
                continue
        return hints

    def track(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        tried: list[str] = []
        last_error: Optional[ProviderError] = None
        phone_error: Optional[str] = None

        for prov in self.providers:
            name = getattr(prov, "name", "?")
            try:
                result = prov.track(
                    tracking_number, company=company, phone=phone
                )
            except ProviderError as exc:
                msg = str(exc)
                tried.append(name)
                last_error = exc
                if is_phone_related_error(msg):
                    phone_error = f"{name}: {msg}"
                if any(k in msg for k in _STOP_MARKERS):
                    raise
                continue
            # Record which provider answered so display can show it
            result.raw["via"] = name
            return result

        if phone_error:
            raise ProviderError(phone_error)
        if last_error is not None:
            raise ProviderError(
                f"All providers failed ({', '.join(tried)}). "
                f"Last error: {last_error}"
            )
        raise ProviderError("No providers configured in fallback chain")
