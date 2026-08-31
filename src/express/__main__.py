"""CLI entry: `express` opens the interactive shell; `express <cmd>` is one-shot."""

from __future__ import annotations

import sys

from express.commands import dispatch
from express.display import console
from express.providers.base import ProviderError
from express.repl import run_repl
from express.service import TrackingService


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        run_repl()
        return

    # One-shot: express list / express add ...
    line = " ".join(argv)
    svc = TrackingService()
    try:
        keep = dispatch(svc, line)
        if not keep:
            return
    except (ProviderError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
