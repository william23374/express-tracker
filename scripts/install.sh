#!/usr/bin/env bash
# Install express CLI globally (~/.local/bin/express) and optional macOS app.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${HOME}/.local"
SHARE="${PREFIX}/share/express"
BIN_DIR="${PREFIX}/bin"
APP_DEST="${HOME}/Applications/Express.app"

resolve_python() {
  for cand in \
    "${EXPRESS_PYTHON:-}" \
    /opt/homebrew/bin/python3.11 \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3 \
    "$HOME/.local/bin/python3.12" \
    python3.11 \
    python3.12 \
    python3
  do
    [[ -z "$cand" ]] && continue
    if command -v "$cand" >/dev/null 2>&1 || [[ -x "$cand" ]]; then
      local ver
      ver="$("$cand" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
      if [[ -n "$ver" ]]; then
        local major="${ver%%.*}" minor="${ver#*.}"
        if (( major > 3 || (major == 3 && minor >= 10) )); then
          echo "$cand"
          return 0
        fi
      fi
    fi
  done
  return 1
}

PYTHON="$(resolve_python)" || {
  echo "Python 3.10+ required. e.g. brew install python@3.11" >&2
  exit 1
}

echo "==> Python: $PYTHON"
mkdir -p "$SHARE" "$BIN_DIR" "${HOME}/Applications"

if [[ ! -x "$SHARE/venv/bin/python" ]]; then
  echo "==> Creating venv at $SHARE/venv"
  "$PYTHON" -m venv "$SHARE/venv"
fi

echo "==> Installing express-tracker"
"$SHARE/venv/bin/python" -m pip install -U pip -q
"$SHARE/venv/bin/pip" install -e "$ROOT" -q

cat > "${BIN_DIR}/express" <<EOF
#!/bin/bash
exec "${SHARE}/venv/bin/express" "\$@"
EOF
chmod +x "${BIN_DIR}/express"
# Compatibility alias
ln -sf "${BIN_DIR}/express" "${BIN_DIR}/el"

echo ""
echo "Install complete."
echo "  Start shell:  express"
echo "  Prompt:       express >"
echo "  One-shot:     express list"
"${BIN_DIR}/express" config --init >/dev/null 2>&1 || true
"${BIN_DIR}/express" config || true
