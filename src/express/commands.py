"""Command handlers shared by the interactive shell and one-shot CLI."""

from __future__ import annotations

import time

from typing import Optional

from express.config import (
    CONFIG_PATH,
    DB_PATH,
    DEFAULT_PROVIDER_CHAIN,
    load_config,
    write_example_config,
)
from express import __version__
from express.display import console, print_current, print_history, print_list
from express.providers.base import ProviderError, available_providers, load_builtin_providers
from express.service import TrackingService
from express.validation import courier_requires_phone
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def is_mock(svc: TrackingService) -> bool:
    return svc.provider_name == "mock"


def _refresh_all(svc: TrackingService) -> None:
    """Re-fetch status for every saved shipment and store the latest snapshot."""
    rows = svc.list()
    if not rows:
        console.print("[dim]nothing to refresh — no saved shipments[/dim]")
        return
    ok = cached = 0
    failed: list[str] = []
    for idx, s in enumerate(rows):
        try:
            result = svc.get(str(s.id))
            if result.status_code == "cached":
                cached += 1
            else:
                ok += 1
        except ProviderError as exc:
            failed.append(f"{s.tracking_number}: {exc}")
        if idx < len(rows) - 1:
            time.sleep(0.3)  # respect provider rate limits
    parts = [f"[green]{ok} ok[/green]"]
    if cached:
        parts.append(f"[yellow]{cached} cached[/yellow]")
    if failed:
        parts.append(f"[red]{len(failed)} failed[/red]")
    console.print(
        f"[bold]refreshed {len(rows)}[/bold] shipment(s): " + " / ".join(parts)
    )
    for f in failed:
        console.print(f"[dim]  {f}[/dim]")


def cmd_list(svc: TrackingService, refresh: bool = False) -> None:
    if refresh:
        _refresh_all(svc)
    print_list(svc.list(), svc.provider_name)


def cmd_add(
    svc: TrackingService,
    number: str,
    company: Optional[str] = None,
    note: str = "",
    phone: str = "",
) -> None:
    shipment = svc.add(
        tracking_number=number,
        company=company,
        note=note,
        phone=phone,
        track=False,
    )
    company_label = shipment.company_name or shipment.company_code or "?"
    parts = [
        f"[green]saved[/green] #{shipment.id}  {shipment.tracking_number}  "
        f"({company_label})"
    ]
    if shipment.phone:
        parts.append(f"  phone=***{shipment.phone[-4:]}")
    if shipment.note:
        parts.append(f"  note={shipment.note}")
    if shipment.last_status:
        parts.append(f"  status={shipment.last_status}")
    console.print("".join(parts))
    warning = getattr(shipment, "_track_warning", None)
    if warning:
        console.print(f"[yellow]saved, but track failed[/yellow] — {warning}")
    elif not shipment.last_status and courier_requires_phone(shipment.company_code):
        console.print(
            "[yellow]tracking not loaded[/yellow] — ZTO/SF need receiver "
            "(or ecommerce privacy-number) last-4 digits, then run: TRACK:"
            f"{shipment.id}"
        )
    elif not shipment.last_status:
        console.print(
            f"[yellow]saved[/yellow] — tracking not loaded. run: TRACK:{shipment.id}"
        )
    if is_mock(svc) and load_config().default_provider in (
        "auto",
        "fallback",
    ):
        console.print(
            "[yellow]using mock provider[/yellow] — configure ~/.express/config.toml"
        )


def cmd_track(
    svc: TrackingService,
    ref: str,
    company: Optional[str] = None,
    phone: Optional[str] = None,
) -> None:
    """Live-track a shipment and print its latest status.

    For a saved shipment the stored phone/company are reused and the fetched
    events are accumulated into the local history. For an unknown number this
    is a one-off lookup.
    """
    saved = svc.resolve(ref)
    if saved:
        result = svc.get(ref)
    else:
        result = svc.query(ref, company=company, phone=phone)
        # Persist a successful lookup so it shows up in LIST / HIST too.
        if result.status and result.status != "Unknown":
            try:
                svc.record_lookup(ref, company=company, phone=phone, result=result)
            except ProviderError:
                pass
    print_current(result, mock_note=is_mock(svc))
    n = len(result.events)
    if n:
        console.print(
            f"[dim]history: {n} event(s) accumulated[/dim] — "
            f"'HIST:{saved.id if saved else ref}' for the full timeline"
        )
    if result.status_code == "cached":
        console.print("[yellow]showing cached snapshot[/yellow] — API busy; retry later")


def cmd_status(svc: TrackingService, ref: str) -> None:
    result = svc.get(ref)
    print_current(result, mock_note=is_mock(svc))
    if result.status_code == "cached":
        console.print("[yellow]showing cached snapshot[/yellow] — API busy; retry later")


def cmd_history(svc: TrackingService, ref: str) -> None:
    result = svc.hist(ref)
    print_history(result, mock_note=is_mock(svc))
    if result.status_code == "cached":
        console.print("[yellow]showing cached snapshot[/yellow] — API busy; retry later")


def cmd_query(
    svc: TrackingService,
    number: str,
    company: Optional[str] = None,
    phone: Optional[str] = None,
    history: bool = False,
) -> None:
    # If user passes a saved id/number without -p, reuse stored phone
    saved = svc.resolve(number)
    if saved and not phone and saved.phone:
        phone = saved.phone
    if saved and not company and saved.company_code:
        company = saved.company_code
    result = svc.query(number, company=company, phone=phone)
    if history:
        print_history(result, mock_note=is_mock(svc))
    else:
        print_current(result, mock_note=is_mock(svc))
    if not result.events and saved and courier_requires_phone(saved.company_code):
        console.print(
            "[dim]tip: ZTO/SF may need ecommerce privacy-number last-4; "
            f"try: SAVE:{saved.tracking_number}/C{saved.company_code}/P<last-4>[/dim]"
        )


def cmd_rm(svc: TrackingService, ref: str) -> None:
    if not svc.remove(ref):
        raise ProviderError(f"not found: {ref}")
    console.print(f"[green]removed[/green] {ref}")


def cmd_edit(
    svc: TrackingService,
    ref: str,
    *,
    tracking_number: Optional[str] = None,
    company: Optional[str] = None,
    note: Optional[str] = None,
    phone: Optional[str] = None,
    clear_phone: bool = False,
    clear_note: bool = False,
) -> None:
    shipment = svc.edit(
        ref,
        tracking_number=tracking_number,
        company=company,
        note=note,
        phone=phone,
        clear_phone=clear_phone,
        clear_note=clear_note,
    )
    company_label = shipment.company_name or shipment.company_code or "?"
    phone_label = f"***{shipment.phone[-4:]}" if shipment.phone else "-"
    console.print(
        f"[green]updated[/green] #{shipment.id}  {shipment.tracking_number}  "
        f"({company_label})  phone={phone_label}"
        + (f"  note={shipment.note}" if shipment.note else "")
    )


def cmd_config(*, init: bool = False) -> None:
    load_builtin_providers()
    if init:
        existed = CONFIG_PATH.is_file()
        path = write_example_config()
        if existed:
            console.print(f"[dim]already exists[/dim] {path}")
        else:
            console.print(f"[green]wrote[/green] {path}")
    cfg = load_config()
    console.print(f"config   {CONFIG_PATH}")
    console.print(f"database {DB_PATH}")
    console.print(f"provider {cfg.default_provider}")
    console.print(f"providers available: {', '.join(available_providers())}")
    console.print(
        f"huawei_jm creds: {'yes (AppKey+AppSecret)' if cfg.has_huawei_jm_credentials() else 'no (Huawei Cloud 快递查询【最新版】/聚美)'}"
    )
    console.print(
        f"huawei_kd100 creds: {'yes (AppKey+AppSecret)' if cfg.has_kd100_credentials() else 'no (Huawei Cloud 快递100实时/百递云)'}"
    )
    console.print(
        f"ali_kd100 creds: {'yes (AppCode)' if cfg.has_ali_kd100_credentials() else 'no (Aliyun Cloud Marketplace 快递100实时/百递云)'}"
    )
    chain = cfg.provider_chain or DEFAULT_PROVIDER_CHAIN
    console.print(
        f"fallback chain (auto): {', '.join(chain)}"
        + (" (configured)" if cfg.provider_chain else " (default)")
    )


def cmd_providers(svc: TrackingService) -> None:
    """List real query providers and which one is currently in use."""
    cfg = svc.config
    current = svc.provider_name

    # Real, user-selectable API providers only (drop auto/fallback mode + mock).
    desc = {
        "huawei_jm": "Huawei Cloud API 快递查询【最新版】(聚美/安那其); AppKey+AppSecret",
        "huawei_kd100": "Huawei Cloud API 快递100实时 (百递云); AppKey+AppSecret",
        "ali_kd100": "Aliyun Cloud API 快递100实时 (百递云); AppCode",
    }
    real = [n for n in available_providers() if n not in ("auto", "fallback", "mock")]

    def configured(name: str) -> bool:
        if name == "huawei_jm":
            return cfg.has_huawei_jm_credentials()
        if name == "huawei_kd100":
            return cfg.has_kd100_credentials()
        if name == "ali_kd100":
            return cfg.has_ali_kd100_credentials()
        return True

    def status(name: str) -> str:
        if name == current:
            return " [bold](active)[/bold]"
        if current in ("auto", "fallback"):
            # Auto mode: mark the provider the chain will try first.
            chain = cfg.provider_chain or DEFAULT_PROVIDER_CHAIN
            first = next(
                (n for n in chain if TrackingService._chain_candidate(cfg, n) is not None),
                None,
            )
            if name == first:
                return " [dim](auto)[/dim]"
        return ""

    table = Table(
        title="Providers",
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
    )
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Configured", justify="center")
    table.add_column("Status", justify="center")
    for name in real:
        ok = configured(name)
        mark = "[green]yes[/green]" if ok else "[yellow]no[/yellow]"
        table.add_row(name, desc.get(name, ""), mark, status(name))
    console.print(table)

    if current in ("auto", "fallback"):
        chain = cfg.provider_chain or DEFAULT_PROVIDER_CHAIN
        console.print(f"auto chain: [cyan]{' -> '.join(chain)}[/cyan]")
    elif current == "mock":
        console.print("[yellow]using mock (offline demo)[/yellow]")


def cmd_use_provider(svc: TrackingService, name: str) -> None:
    """Switch the active provider at runtime.

    Raises ProviderError on invalid provider or missing credentials, so the
    REPL / one-shot CLI handles it uniformly (red message + exit 1).
    """
    new_name = svc.switch_provider(name)
    console.print(f"[green]switched provider[/green] -> [bold]{new_name}[/bold]")
    if new_name == "mock":
        console.print(
            "[yellow]warning[/yellow] no usable provider available; using mock data"
        )


def cmd_version() -> None:
    """Show the installed Express version."""
    console.print(f"[bold]Express[/bold] tracker v{__version__}")


def print_help() -> None:
    """Show Typer-style command help (previous CLI look)."""
    usage = Text.assemble(
        ("Usage: ", "bold"),
        ("express > ", "cyan"),
        ("COMMAND [ARGS]...", "white"),
    )
    desc = Text(
        "Express tracking shell.\n"
        "Type commands without a prefix at the express > prompt."
    )

    table = Table(
        show_header=True,
        header_style="bold",
        box=None,
        pad_edge=False,
        title="Commands",
        title_style="bold",
        title_justify="left",
    )
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Aliases", style="dim")
    table.add_column("Description")

    rows = [
        (r"LIST \[/R]", "li, ls", "List saved tracking numbers (/R refreshes all)"),
        (r"SAVE:NUMBER\[/C]\[/P]\[/N]", "", "Save a new tracking number (info only, no live query)"),
        (r"TRACK:NUMBER\[/C]\[/P]", "tr", "Live-track a shipment (updates saved history)"),
        (r"QUERY:NUMBER\[/C]\[/P]\[/H]", "", "Live fetch latest status (saved phone reused)"),
        (r"STAT:NUMBER\[/C]", "st", "Show latest status of a saved shipment"),
        (r"HIST:NUMBER\[/C]", "hist", "Show full tracking history"),
        (r"MODIFY:NUMBER\[/C]\[/P]\[/N]\[/T]", "edit, up", "Update company/phone/note/number (empty value clears)"),
        (r"DEL:NUMBER\[/C]", "rm", "Remove a saved shipment"),
        (r"CONF \[/INIT]", "cf", "Show config paths / credentials (/INIT creates example)"),
        ("PROV", "prov", "List providers and which is in use"),
        ("USE:provider", "", "Switch active provider (USE:auto = auto-select)"),
        ("VER", "", "Show version"),
        (r"HELP \[CMD]", "?", "Show this help"),
        ("SO", "quit", "Leave the express shell"),
    ]
    for cmd, aliases, desc_row in rows:
        table.add_row(cmd, aliases, desc_row)

    opts = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    opts.add_column("Option", style="cyan", no_wrap=True)
    opts.add_column("Description")
    opts.add_row("NUMBER", "Tracking number (6~32 digits) — required, first segment")
    opts.add_row("C", "Courier code (sf yto zto jtexpress …); optional")
    opts.add_row("P", "Receiver phone last-4 (SF/ZTO need it); P= empty to clear")
    opts.add_row("N", "Note / label; N= empty to clear")
    opts.add_row("T", "New tracking number (MODIFY)")
    opts.add_row("H", "Show full history (QUERY)")
    opts.add_row("R", "Refresh all saved shipments' latest status (LIST)")
    opts.add_row("/INIT", "Create example ~/.express/config.toml (CONF)")

    console.print()
    console.print(usage)
    console.print()
    console.print(desc)
    console.print()
    console.print(table)
    console.print()
    console.print("[bold]Options[/bold]")
    console.print(opts)
    console.print()
    console.print(
        Panel(
            "Examples:\n"
            "  LIST\n"
            "  SAVE:JT4006721151302\n"
            "  TRACK:7\n"
            "  SAVE:75627325414125/Czto/P13800138000\n"
            "  MODIFY:11/P7609\n"
            "  MODIFY:11/Czto/Nmy-parcel\n"
            "  STAT:7\n"
            "  HIST:7\n"
            "  QUERY:JT4006721151302/Cjtexpress/H",
            title="express >",
            border_style="blue",
            padding=(0, 1),
        )
    )
    console.print()


TAG_FIELDS = {
    "C": "company",
    "P": "phone",
    "N": "note",
    "T": "tracking_number",
}


def parse_eterm_params(param_str: str) -> dict:
    """Parse an ETerm-style 'NUM/Ccode/Pphone/Nnote/Tnew' payload into a params dict.

    The first slash-free segment is the tracking number / id (required).
    Subsequent segments are tagged fields, written as 'Czto', 'P8899',
    'Nmy-parcel' (value follows the tag letter) or as 'C=zto' / 'P=8899'.
    An empty P= / N= value requests clearing that field (clear_phone /
    clear_note); a bare 'H' segment flags history mode for QUERY.
    """
    out: dict[str, str | bool] = {}
    if not param_str:
        return out
    segs = [s.strip() for s in param_str.split("/") if s.strip()]
    if not segs:
        return out
    out["number"] = segs[0]
    for seg in segs[1:]:
        key = seg[0].upper()
        val = seg[1:]
        if val.startswith(("=", ":")):
            val = val[1:]
        if key == "H":
            out["history"] = True
            continue
        field = TAG_FIELDS.get(key)
        if field is None:
            raise ProviderError(
                f"unknown tag in '{seg}' — use C/P/N/T (or H for history)"
            )
        if not val:
            # empty value: clear semantics for P/N; C/T empty is a no-op
            if field in ("phone", "note"):
                out["clear_" + field] = True
            continue
        out[field] = val
    return out


def has_eterm_flag(param_str: str, flag: str) -> bool:
    """Return True if the payload contains a bare flag segment like '/R'."""
    flag = flag.upper()
    return any(seg.strip().upper() == flag for seg in param_str.split("/"))


def dispatch(svc: TrackingService, line: str) -> bool:
    """
    Run one ETerm-style command line. Returns False if the shell should exit.
    Raises ProviderError / ValueError on failure.
    """
    line = line.strip()
    if not line:
        return True

    # Split the head command token: stop at the first space or colon.
    i = 0
    while i < len(line) and line[i] not in (" ", ":"):
        i += 1
    cmd = line[:i].upper()
    rest = line[i:].lstrip()
    if rest.startswith(":"):
        rest = rest[1:].strip()

    # --- control / no-arg commands ---
    if cmd in ("SO", "EXIT", "QUIT", "Q"):
        return False
    if cmd in ("HELP", "?"):
        print_help()
        return True
    if cmd in ("LIST", "LI", "LS"):
        cmd_list(svc, refresh=has_eterm_flag(rest, "R"))
        return True
    if cmd in ("VER", "VERSION", "-V", "--VERSION"):
        cmd_version()
        return True
    if cmd in ("PROV", "PROVIDER", "PROVIDERS"):
        cmd_providers(svc)
        return True
    if cmd in ("CONF", "CF", "CONFIG"):
        cmd_config(init="INIT" in rest.upper())
        return True

    # --- payload commands (':'-separated segment list) ---
    if cmd in ("SAVE", "ADD"):
        p = parse_eterm_params(rest)
        if not p.get("number"):
            raise ProviderError(r"usage: SAVE:NUMBER\[/C]\[/P]\[/N]")
        cmd_add(
            svc,
            p["number"],
            company=p.get("company") or None,
            note=p.get("note") or "",
            phone=p.get("phone") or "",
        )
        return True
    if cmd in ("TRACK", "TR"):
        p = parse_eterm_params(rest)
        if not p.get("number"):
            raise ProviderError(r"usage: TRACK:NUMBER\[/C]\[/P]")
        cmd_track(
            svc,
            p["number"],
            company=p.get("company") or None,
            phone=p.get("phone") or None,
        )
        return True
    if cmd == "QUERY":
        p = parse_eterm_params(rest)
        if not p.get("number"):
            raise ProviderError(r"usage: QUERY:NUMBER\[/C]\[/P]\[/H]")
        cmd_query(
            svc,
            p["number"],
            company=p.get("company") or None,
            phone=p.get("phone") or None,
            history=bool(p.get("history")),
        )
        return True
    if cmd in ("STAT", "ST"):
        p = parse_eterm_params(rest)
        if not p.get("number"):
            raise ProviderError(r"usage: STAT:NUMBER\[/C]")
        cmd_status(svc, p["number"])
        return True
    if cmd in ("HIST", "HISTORY"):
        p = parse_eterm_params(rest)
        if not p.get("number"):
            raise ProviderError(r"usage: HIST:NUMBER\[/C]")
        cmd_history(svc, p["number"])
        return True
    if cmd in ("MODIFY", "UPDATE", "EDIT", "UP"):
        p = parse_eterm_params(rest)
        if not p.get("number"):
            raise ProviderError(r"usage: MODIFY:NUMBER\[/C]\[/P]\[/N]\[/T]")
        cmd_edit(
            svc,
            p["number"],
            tracking_number=p.get("tracking_number") or None,
            company=p.get("company") or None,
            note=p.get("note") or None,
            phone=p.get("phone") or None,
            clear_phone=bool(p.get("clear_phone")),
            clear_note=bool(p.get("clear_note")),
        )
        return True
    if cmd in ("DEL", "REMOVE", "RM"):
        p = parse_eterm_params(rest)
        if not p.get("number"):
            raise ProviderError(r"usage: DEL:NUMBER\[/C]")
        cmd_rm(svc, p["number"])
        return True
    if cmd == "USE":
        name = (rest.split()[0] if rest.split() else "").strip()
        if name.lower() == "list":
            cmd_providers(svc)
            return True
        if not name:
            raise ProviderError("usage: USE:provider   (PROV to list)")
        cmd_use_provider(svc, name)
        return True

    raise ProviderError(f"unknown command: {cmd}  (type HELP)")
