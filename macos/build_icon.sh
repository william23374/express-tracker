#!/usr/bin/env bash
# Build macos/icons/AppIcon.icns from AppIcon-1024.png
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/macos/icons/AppIcon-1024.png"
ICONSET="${ROOT}/macos/icons/AppIcon.iconset"
ICNS="${ROOT}/macos/icons/AppIcon.icns"

if [[ ! -f "${SRC}" ]]; then
  echo "Missing ${SRC}" >&2
  exit 1
fi

rm -rf "${ICONSET}"
mkdir -p "${ICONSET}"

# macOS iconset required sizes
make_icon() {
  local size="$1"
  local name="$2"
  sips -z "${size}" "${size}" "${SRC}" --out "${ICONSET}/${name}" >/dev/null
}

make_icon 16  icon_16x16.png
make_icon 32  icon_16x16@2x.png
make_icon 32  icon_32x32.png
make_icon 64  icon_32x32@2x.png
make_icon 128 icon_128x128.png
make_icon 256 icon_128x128@2x.png
make_icon 256 icon_256x256.png
make_icon 512 icon_256x256@2x.png
make_icon 512 icon_512x512.png
cp "${SRC}" "${ICONSET}/icon_512x512@2x.png"

iconutil -c icns "${ICONSET}" -o "${ICNS}"
rm -rf "${ICONSET}"

echo "Built ${ICNS}"
