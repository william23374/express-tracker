from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from express.models import CompanyHint, TrackingEvent, TrackResult
from express.providers.base import register


@register("mock")
class MockProvider:
    """Offline demo provider — not real tracking data."""

    name = "mock"

    def detect_company(self, tracking_number: str) -> list[CompanyHint]:
        digit = sum(ord(c) for c in tracking_number) % 3
        options = [
            CompanyHint(code="yuantong", name="圆通速递"),
            CompanyHint(code="zhongtong", name="中通快递"),
            CompanyHint(code="shunfeng", name="顺丰速运"),
        ]
        # Rotate so different numbers get different top hits
        return options[digit:] + options[:digit]

    def track(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        hints = self.detect_company(tracking_number)
        company_code = (company or hints[0].code).lower()
        company_name = next(
            (h.name for h in hints if h.code == company_code), company_code
        )
        now = datetime.now().replace(microsecond=0)
        events = [
            TrackingEvent(
                time=now,
                description="[MOCK] Arrived at Pudong, Shanghai — out for delivery",
                location="Shanghai Pudong",
                status="Out for Delivery",
            ),
            TrackingEvent(
                time=now - timedelta(hours=6),
                description="[MOCK] Left Shanghai hub, heading to Pudong",
                location="Shanghai Hub",
                status="In Transit",
            ),
            TrackingEvent(
                time=now - timedelta(days=1),
                description="[MOCK] Package picked up",
                location="Origin facility",
                status="Picked Up",
            ),
        ]
        return TrackResult(
            tracking_number=tracking_number,
            company_code=company_code,
            company_name=company_name,
            status="Out for Delivery",
            status_code="5",
            current=events[0],
            events=events,
            raw={"mock": True, "phone": phone},
        )
