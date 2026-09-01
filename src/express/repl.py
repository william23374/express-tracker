"""Interactive express terminal: prompt `express >`."""

from __future__ import annotations

try:
    import readline as _readline  # noqa: F401  (Unix)
except ImportError:  # Windows: no stdlib readline
    try:
        import pyreadline3 as _readline  # noqa: F401  (Windows arrow-key/history)
    except ImportError:
        _readline = None
from pathlib import Path

from express import __version_full__
from express.commands import dispatch
from express.display import console
from express.providers.base import ProviderError
from express.service import TrackingService

PROMPT = "express > "
HISTORY_FILE = Path.home() / ".express" / "shell_history"


def _load_readline_history() -> None:
    if _readline is None:
        return
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if HISTORY_FILE.is_file():
        try:
            _readline.read_history_file(str(HISTORY_FILE))
        except (OSError, AttributeError):
            pass
    try:
        _readline.set_history_length(1000)
    except AttributeError:
        pass


def _save_readline_history() -> None:
    if _readline is None:
        return
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _readline.write_history_file(str(HISTORY_FILE))
    except (OSError, AttributeError):
        pass


def run_repl() -> None:
    """Start the interactive Express shell."""
    svc = TrackingService()
    _load_readline_history()
    console.print(
        f"[bold]Express[/bold] tracker v{__version_full__}  "
        f"[dim](provider={svc.provider_name})[/dim]"
    )
    console.print("[dim]Type HELP — commands need no prefix. SO to quit.[/dim]")
    console.print()

    try:
        while True:
            try:
                line = input(PROMPT)
            except EOFError:
                console.print()
                break
            except KeyboardInterrupt:
                console.print()
                continue
            try:
                if not dispatch(svc, line):
                    break
            except (ProviderError, ValueError) as exc:
                console.print(f"[red]{exc}[/red]")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]{exc}[/red]")
    finally:
        _save_readline_history()
