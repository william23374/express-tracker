from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CompanyHint:
    code: str
    name: str = ""


@dataclass
class TrackingEvent:
    time: datetime
    description: str
    location: str = ""
    status: str = ""


@dataclass
class TrackResult:
    tracking_number: str
    company_code: str
    company_name: str = ""
    status: str = ""
    status_code: str = ""
    current: Optional[TrackingEvent] = None
    events: list[TrackingEvent] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Shipment:
    id: int
    tracking_number: str
    company_code: str = ""
    company_name: str = ""
    note: str = ""
    phone: str = ""
    last_status: str = ""
    last_location: str = ""
    last_event_time: Optional[datetime] = None
    events: list[TrackingEvent] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
