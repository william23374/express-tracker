from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from express.config import DB_PATH, ensure_config_dir
from express.models import Shipment, TrackingEvent


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _event_to_dict(ev: TrackingEvent) -> dict:
    return {
        "time": ev.time.isoformat(),
        "description": ev.description,
        "location": ev.location,
        "status": ev.status,
    }


def _event_from_dict(d: dict) -> TrackingEvent:
    parsed = _parse_dt(str(d.get("time") or ""))
    if parsed is None:
        parsed = datetime.now()
    return TrackingEvent(
        time=parsed,
        description=str(d.get("description") or ""),
        location=str(d.get("location") or ""),
        status=str(d.get("status") or ""),
    )


def _events_to_json(events: list[TrackingEvent]) -> str:
    return json.dumps([_event_to_dict(e) for e in events], ensure_ascii=False)


def _events_from_json(text: Optional[str]) -> list[TrackingEvent]:
    if not text:
        return []
    try:
        raw = json.loads(text)
    except (ValueError, TypeError):
        return []
    out: list[TrackingEvent] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(_event_from_dict(item))
    return out


def merge_events(
    existing: list[TrackingEvent], fresh: list[TrackingEvent]
) -> list[TrackingEvent]:
    """Merge two event lists, deduplicate by (time, description), newest first."""
    seen: set[tuple[datetime, str]] = set()
    merged: list[TrackingEvent] = []
    for ev in list(existing) + list(fresh):
        key = (ev.time, ev.description)
        if key in seen:
            continue
        seen.add(key)
        merged.append(ev)
    merged.sort(key=lambda e: e.time, reverse=True)
    return merged


class SQLiteStore:
    def __init__(self, path: Path | None = None):
        ensure_config_dir()
        self.path = path or DB_PATH
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shipments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tracking_number TEXT NOT NULL UNIQUE,
                    company_code TEXT NOT NULL DEFAULT '',
                    company_name TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    last_status TEXT NOT NULL DEFAULT '',
                    last_location TEXT NOT NULL DEFAULT '',
                    last_event_time TEXT,
                    events TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # Migrate older DBs that predate the events history column.
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(shipments)")]
            if "events" not in cols:
                conn.execute(
                    "ALTER TABLE shipments ADD COLUMN events TEXT NOT NULL DEFAULT '[]'"
                )
            conn.commit()

    def _row_to_shipment(self, row: sqlite3.Row) -> Shipment:
        return Shipment(
            id=row["id"],
            tracking_number=row["tracking_number"],
            company_code=row["company_code"] or "",
            company_name=row["company_name"] or "",
            note=row["note"] or "",
            phone=row["phone"] or "",
            last_status=row["last_status"] or "",
            last_location=row["last_location"] or "",
            last_event_time=_parse_dt(row["last_event_time"]),
            events=_events_from_json(row["events"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
        )

    def add(
        self,
        tracking_number: str,
        company_code: str = "",
        company_name: str = "",
        note: str = "",
        phone: str = "",
    ) -> Shipment:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO shipments (
                        tracking_number, company_code, company_name,
                        note, phone, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tracking_number.strip(),
                        company_code,
                        company_name,
                        note,
                        phone,
                        now,
                        now,
                    ),
                )
                conn.commit()
                row_id = cur.lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Tracking number already saved: {tracking_number}") from exc
        shipment = self.get_by_id(row_id)
        assert shipment is not None
        return shipment

    def list(self) -> list[Shipment]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shipments ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [self._row_to_shipment(r) for r in rows]

    def get_by_id(self, shipment_id: int) -> Optional[Shipment]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM shipments WHERE id = ?", (shipment_id,)
            ).fetchone()
        return self._row_to_shipment(row) if row else None

    def get_by_number(self, tracking_number: str) -> Optional[Shipment]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM shipments WHERE tracking_number = ?",
                (tracking_number.strip(),),
            ).fetchone()
        return self._row_to_shipment(row) if row else None

    def resolve(self, ref: str) -> Optional[Shipment]:
        ref = ref.strip()
        if ref.isdigit():
            found = self.get_by_id(int(ref))
            if found:
                return found
        return self.get_by_number(ref)

    def delete(self, ref: str) -> bool:
        shipment = self.resolve(ref)
        if not shipment:
            return False
        with self._connect() as conn:
            conn.execute("DELETE FROM shipments WHERE id = ?", (shipment.id,))
            conn.commit()
        return True

    def update_fields(
        self,
        shipment_id: int,
        *,
        tracking_number: Optional[str] = None,
        company_code: Optional[str] = None,
        company_name: Optional[str] = None,
        note: Optional[str] = None,
        phone: Optional[str] = None,
        clear_phone: bool = False,
        clear_note: bool = False,
    ) -> Optional[Shipment]:
        """Update saved shipment fields (phone / company / note / tracking number)."""
        shipment = self.get_by_id(shipment_id)
        if not shipment:
            return None

        fields: dict[str, str] = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if tracking_number is not None:
            fields["tracking_number"] = tracking_number.strip()
        if company_code is not None:
            fields["company_code"] = company_code
        if company_name is not None:
            fields["company_name"] = company_name
        if note is not None:
            fields["note"] = note
        if clear_note:
            fields["note"] = ""
        if phone is not None:
            fields["phone"] = phone
        if clear_phone:
            fields["phone"] = ""

        assignments = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [shipment_id]
        with self._connect() as conn:
            try:
                conn.execute(
                    f"UPDATE shipments SET {assignments} WHERE id = ?",
                    values,
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"Tracking number already saved: {tracking_number}"
                ) from exc
        return self.get_by_id(shipment_id)

    def update_meta(
        self,
        shipment_id: int,
        *,
        company_code: Optional[str] = None,
        company_name: Optional[str] = None,
        note: Optional[str] = None,
        phone: Optional[str] = None,
        last_status: Optional[str] = None,
        last_location: Optional[str] = None,
        last_event_time: Optional[datetime] = None,
    ) -> Optional[Shipment]:
        shipment = self.get_by_id(shipment_id)
        if not shipment:
            return None

        fields: dict[str, str] = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if company_code is not None:
            fields["company_code"] = company_code
        if company_name is not None:
            fields["company_name"] = company_name
        if note is not None:
            fields["note"] = note
        if phone is not None:
            fields["phone"] = phone
        if last_status is not None:
            fields["last_status"] = last_status
        if last_location is not None:
            fields["last_location"] = last_location
        if last_event_time is not None:
            fields["last_event_time"] = last_event_time.isoformat(timespec="seconds")

        assignments = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [shipment_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE shipments SET {assignments} WHERE id = ?",
                values,
            )
            conn.commit()
        return self.get_by_id(shipment_id)

    def get_events(self, shipment_id: int) -> list[TrackingEvent]:
        shipment = self.get_by_id(shipment_id)
        return shipment.events if shipment else []

    def save_events(self, shipment_id: int, events: list[TrackingEvent]) -> None:
        payload = _events_to_json(events)
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE shipments SET events = ?, updated_at = ? WHERE id = ?",
                (payload, now, shipment_id),
            )
            conn.commit()
