#!/usr/bin/env bash
set -euo pipefail
PREFIX="${HOME}/.local"
rm -f "${PREFIX}/bin/express" "${PREFIX}/bin/el"
rm -rf "${PREFIX}/share/express" "${PREFIX}/share/el"
rm -rf "${HOME}/Applications/Express.app" "${HOME}/Applications/El.app"
echo "Uninstalled express CLI wrappers and apps."
echo "User data kept in ~/.express/ (and legacy ~/.el/ if present)."
