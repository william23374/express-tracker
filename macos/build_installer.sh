#!/usr/bin/env bash
# Package terminal Express.app:
#   PyInstaller → bundled `express` CLI/REPL
#   .app opens Terminal via `open` .command (no AppleScript Automation)
#   hdiutil → Express-Installer.dmg
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist"
BUILD="${ROOT}/build"
VERSION="1.0.0"
BUILD_NO="$(date +%Y%m%d%H%M)"                    # timestamp build number, e.g. 202608311044
FULL_VERSION="${VERSION}+build${BUILD_NO}"       # e.g. 1.0.0+build202608311044
APP_NAME="Express"
IDENTIFIER="com.local.express.tracker"

# ---------------------------------------------------------------------------
# Optional Developer ID signing + Apple notarization.
# Un-notarized builds on a new Mac need right-click-open (or `xattr -d
# com.apple.quarantine`). Configure the env vars below (e.g. in ~/.zshenv) to
# make the package open directly after drag-to-Applications.
#   # 1) a Developer ID Application certificate (paid Apple Developer account)
#   export DEVELOPER_ID_APP="Developer ID Application: Your Name (TEAMID)"
#   # 2) recommended: one keychain profile, so no secrets live in the script
#   xcrun notarytool store-credentials express-notary \
#     --apple-id "$APPLE_ID" --team-id "$TEAMID" --password "$APP_SPECIFIC_PW"
#   export NOTARY_PROFILE="express-notary"
#   #    ... or fall back to Apple ID + app-specific password + team id:
#   export APPLE_ID="you@example.com" APPLE_ID_PASSWORD="xxxx-xxxx-xxxx-xxxx" TEAM_ID="TEAMID"
# ---------------------------------------------------------------------------
DEVELOPER_ID_APP="${DEVELOPER_ID_APP:-}"   # "Developer ID Application: Name (TEAMID)"
NOTARY_PROFILE="${NOTARY_PROFILE:-}"       # name from `notarytool store-credentials`
APPLE_ID="${APPLE_ID:-}"
APPLE_ID_PASSWORD="${APPLE_ID_PASSWORD:-}" # app-specific password
TEAM_ID="${TEAM_ID:-}"

# Sign a .app bundle: Developer ID + hardened runtime when configured,
# otherwise fall back to ad-hoc (un-notarizable) so the script still works.
sign_app() {
  local bundle="$1"
  xattr -cr "${bundle}" 2>/dev/null || true
  if [[ -n "${DEVELOPER_ID_APP}" ]]; then
    echo "==> Signing with Developer ID + hardened runtime"
    codesign --force --deep --options runtime --timestamp \
      --sign "${DEVELOPER_ID_APP}" "${bundle}"
  else
    echo "==> Signing ad-hoc (set DEVELOPER_ID_APP for notarized builds)"
    codesign --force --deep --sign - "${bundle}"
  fi
}

# Submit a DMG to Apple notarization and staple the ticket (no-op when configured
# for ad-hoc only). Keeps the dmg usable either way.
# The ticket must be stapled to the .app bundle TOO, not just the dmg: a stapled
# ticket does not travel when the user drags the app out of the dmg into
# /Applications, so an offline first launch would fall back to an online check.
notarize() {
  local dmg="$1" app="$2"
  if [[ -z "${DEVELOPER_ID_APP}" ]]; then
    echo "==> skip notarization — no DEVELOPER_ID_APP certificate"
    return 0
  fi
  if ! command -v xcrun >/dev/null 2>&1; then
    echo "==> skip notarization — xcrun missing (install Xcode Command Line Tools)"
    return 0
  fi
  local args=()
  if [[ -n "${NOTARY_PROFILE}" ]]; then
    args=(--keychain-profile "${NOTARY_PROFILE}")
  elif [[ -n "${APPLE_ID}" && -n "${APPLE_ID_PASSWORD}" && -n "${TEAM_ID}" ]]; then
    args=(--apple-id "${APPLE_ID}" --password "${APPLE_ID_PASSWORD}" --team-id "${TEAM_ID}")
  else
    echo "==> skip notarization — set NOTARY_PROFILE or APPLE_ID/APPLE_ID_PASSWORD/TEAM_ID"
    return 0
  fi
  # Stapling requires the artifact to carry a valid code signature.
  codesign --force --timestamp --sign "${DEVELOPER_ID_APP}" "${dmg}" || true
  echo "==> Submitting ${dmg} for notarization (can take a few minutes)…"
  xcrun notarytool submit "${dmg}" "${args[@]}" --wait || {
    echo "==> notarization FAILED — leaving stapled-but-uncertified dmg" >&2
    return 1
  }
  echo "==> Stapling ticket to app bundle and dmg (so offline first-launch works)"
  [[ -n "${app}" && -d "${app}" ]] && xcrun stapler staple "${app}"
  xcrun stapler staple "${dmg}"
  echo "==> Verifying staples"
  [[ -n "${app}" && -d "${app}" ]] && xcrun stapler validate "${app}" 2>/dev/null || true
  xcrun stapler validate "${dmg}" 2>/dev/null || true
}

resolve_python() {
  for cand in \
    "${EXPRESS_PYTHON:-}" \
    /opt/homebrew/bin/python3.11 \
    /opt/homebrew/bin/python3.12 \
    "$HOME/.local/bin/python3.12" \
    /opt/homebrew/bin/python3 \
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

PYTHON="$(resolve_python)" || { echo "Python 3.10+ required." >&2; exit 1; }
echo "==> Python: ${PYTHON}"
BUILD_VENV="${ROOT}/.build-venv"
[[ -x "${BUILD_VENV}/bin/python" ]] || "${PYTHON}" -m venv "${BUILD_VENV}"
PY="${BUILD_VENV}/bin/python"
"${PY}" -m pip install -q -U pip
"${BUILD_VENV}/bin/pip" install -q "pyinstaller>=6.3" -e "${ROOT}"

bash "${ROOT}/macos/build_icon.sh"

# Bake the build number into the app so `ver` reports v1.0.0+build$BUILD_NO.
# The file is gitignored and removed again at the end of the script.
cat > "${ROOT}/src/express/_build.py" <<EOF
BUILD_NO = "${BUILD_NO}"
EOF

echo "==> PyInstaller → express (console REPL)"
rm -rf "${DIST}/express" "${DIST}/${APP_NAME}.app" "${DIST}/El.app" "${BUILD}"
cd "${ROOT}"
"${PY}" -m PyInstaller --noconfirm --clean \
  --distpath "${DIST}" --workpath "${BUILD}" \
  "${ROOT}/macos/El.spec"

BIN_DIR="${DIST}/express"
[[ -x "${BIN_DIR}/express" ]] || { echo "missing ${BIN_DIR}/express" >&2; exit 1; }

echo "==> Assembling ${APP_NAME}.app"
APP="${DIST}/${APP_NAME}.app"
MACOS_DIR="${APP}/Contents/MacOS"
RES="${APP}/Contents/Resources"
rm -rf "${APP}"
mkdir -p "${MACOS_DIR}" "${RES}"
cp -R "${BIN_DIR}" "${RES}/express"

cat > "${MACOS_DIR}/Express" <<'EOF'
#!/bin/bash
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
open "${RES}/express-launch.command"
EOF
chmod +x "${MACOS_DIR}/Express"

cat > "${RES}/express-launch.command" <<'EOF'
#!/bin/bash
RES="$(cd "$(dirname "$0")" && pwd)"
export PATH="$RES/express:$HOME/.local/bin:/usr/local/bin:$PATH"
cd "$HOME" || true
clear
mkdir -p "$HOME/.local/bin"
if [ -x "$RES/express/express" ]; then
  ln -sf "$RES/express/express" "$HOME/.local/bin/express" 2>/dev/null || true
  ln -sf "$HOME/.local/bin/express" "$HOME/.local/bin/el" 2>/dev/null || true
  exec "$RES/express/express"
fi
echo "express binary missing"
exec "${SHELL:-/bin/zsh}"
EOF
chmod +x "${RES}/express-launch.command"

[[ -f "${ROOT}/macos/icons/AppIcon.icns" ]] && cp "${ROOT}/macos/icons/AppIcon.icns" "${RES}/AppIcon.icns"

cat > "${APP}/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>Express</string>
  <key>CFBundleIdentifier</key><string>${IDENTIFIER}</string>
  <key>CFBundleVersion</key><string>${FULL_VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Express</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

sign_app "${APP}"
"${RES}/express/express" config >/dev/null || true

# Portable direct-open desktop app (unzip -> double-click Express.app)
ZIP="${DIST}/Express-macos.zip"
rm -f "${ZIP}"
ditto -c -k --keepParent "${APP}" "${ZIP}"

STAGE="${DIST}/_dmg_stage"
DMG="${DIST}/Express-Installer.dmg"
rm -rf "${STAGE}"; mkdir -p "${STAGE}"
cp -R "${APP}" "${STAGE}/${APP_NAME}.app"
ln -sf /Applications "${STAGE}/Applications"
cat > "${STAGE}/README.txt" <<EOF
Express Tracker ${FULL_VERSION}
==========================
Drag Express.app to Applications, double-click.
Opens Terminal with prompt:  express >

Commands: list | add <no> | status <id> | history <id> | query <no> | rm | help | exit
EOF

rm -f "${DMG}"
hdiutil create -volname "Express ${FULL_VERSION}" -srcfolder "${STAGE}" -ov -format UDZO "${DMG}" >/dev/null
notarize "${DMG}" "${APP}"
rm -rf "${STAGE}" "${BUILD}" "${DIST}/express"
rm -f "${ROOT}/src/express/_build.py"

mkdir -p "${HOME}/Applications"
rm -rf "${HOME}/Applications/${APP_NAME}.app" "${HOME}/Applications/El.app"
cp -R "${APP}" "${HOME}/Applications/${APP_NAME}.app"
ln -sf "${HOME}/Applications/${APP_NAME}.app/Contents/Resources/express/express" "${HOME}/.local/bin/express" 2>/dev/null || true
ln -sf "${HOME}/.local/bin/express" "${HOME}/.local/bin/el" 2>/dev/null || true

echo ""
echo "Ready:"
echo "  version  ${FULL_VERSION}"
echo "  app      ${APP}"
echo "  zip      ${ZIP}"
echo "  dmg      ${DMG}"
echo "  open     ${HOME}/Applications/${APP_NAME}.app"

if [[ -n "${DEVELOPER_ID_APP}" ]]; then
  echo ""
  echo "Gatekeeper: Developer ID signing + notarization ENABLED."
  echo "  recipients can open the dmg / app directly, no right-click or xattr."
else
  echo ""
  echo "Gatekeeper: NOT notarized (no DEVELOPER_ID_APP certificate)."
  echo "  - this Mac locally: opens fine."
  echo "  - distributing to another Mac: recipient uses right-click->Open,"
  echo "    or runs:  xattr -d com.apple.quarantine <path-to-app>"
  echo "  To enable notarization, see the comments at the top of this script."
fi
