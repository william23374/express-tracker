"""Shared terminal display helpers."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from express.models import TrackResult
from express.status import (
    DELIVERED,
    EXCEPTION,
    IN_TRANSIT,
    OUT_FOR_DELIVERY,
    PICKED_UP,
    RETURNED,
    extract_location,
    to_en_status,
)

console = Console(stderr=False)


def status_style(status: str) -> str:
    s = to_en_status(status).lower()
    if s == DELIVERED.lower():
        return "green"
    if s == OUT_FOR_DELIVERY.lower():
        return "cyan"
    if s in (EXCEPTION.lower(), RETURNED.lower()):
        return "red"
    if s == PICKED_UP.lower():
        return "yellow"
    if s == IN_TRANSIT.lower():
        return "white"
    raw = (status or "").lower()
    if any(k in raw for k in ("签收", "已签", "妥投", "deliver")):
        return "green"
    if any(k in raw for k in ("派件", "派送", "out for")):
        return "cyan"
    if any(k in raw for k in ("疑难", "退", "拒", "异常", "exception")):
        return "red"
    if any(k in raw for k in ("揽收", "收件", "picked")):
        return "yellow"
    return "white"


def print_current(result: TrackResult, *, mock_note: bool = False) -> None:
    status_en = to_en_status(result.status)
    status = Text(status_en, style=status_style(result.status))
    lines = [
        Text.assemble(("Tracking Number    ", "dim"), result.tracking_number),
        Text.assemble(
            ("Courier / Carrier  ", "dim"),
            result.company_name or result.company_code or "-",
        ),
        Text.assemble(("Tracking Status    ", "dim"), status),
    ]
    via = (result.raw or {}).get("via")
    if via:
        lines.append(Text.assemble(("Source             ", "dim"), via))
    if result.current:
        loc = extract_location(result.current.description, result.current.location) or "-"
        lines.append(Text.assemble(("Location           ", "dim"), loc))
        lines.append(
            Text.assemble(
                ("Updated At         ", "dim"),
                result.current.time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        lines.append(
            Text.assemble(("Latest Event       ", "dim"), result.current.description)
        )
    body = Text("\n").join(lines)
    if mock_note:
        body = Text.assemble(body, "\n", ("[mock demo data]", "yellow dim"))
    title = f"{result.company_name or result.company_code or 'Shipment'}"
    console.print(Panel(body, title=title, border_style="blue"))


def print_history(result: TrackResult, *, mock_note: bool = False) -> None:
    print_current(result, mock_note=mock_note)
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Location")
    table.add_column("Event")
    for ev in result.events:
        table.add_row(
            ev.time.strftime("%Y-%m-%d %H:%M"),
            extract_location(ev.description, ev.location) or "-",
            ev.description,
        )
    console.print(table)


def print_list(rows, provider_name: str) -> None:
    if not rows:
        console.print("[dim]no saved shipments — try: SAVE:NUMBER[/dim]")
        return
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Tracking Number")
    table.add_column("Courier")
    table.add_column("Phone")
    table.add_column("Status")
    table.add_column("Note")
    for s in rows:
        raw_status = s.last_status or ""
        if not raw_status and s.last_location:
            # Infer from cached latest event text when status was never filled
            loc = s.last_location
            if any(k in loc for k in ("签收", "代收", "投柜")):
                raw_status = "Delivered"
            elif any(k in loc for k in ("派件", "派送", "快递员")):
                raw_status = "Out for Delivery"
            elif any(k in loc for k in ("揽收", "收件")):
                raw_status = "Picked Up"
            elif any(k in loc for k in ("发往", "到达", "离开", "转运")):
                raw_status = "In Transit"
        status_label = to_en_status(raw_status) if raw_status else "-"
        status = Text(status_label, style=status_style(raw_status))
        phone_label = f"***{s.phone[-4:]}" if s.phone else "-"
        table.add_row(
            str(s.id),
            s.tracking_number,
            s.company_name or s.company_code or "-",
            phone_label,
            status,
            s.note or "",
        )
    console.print(table)
    console.print(f"[dim]provider={provider_name}[/dim]")
