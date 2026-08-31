#!/usr/bin/env bash
# Alias: build desktop app with PyInstaller (same as build_installer.sh)
exec "$(cd "$(dirname "$0")" && pwd)/build_installer.sh" "$@"
