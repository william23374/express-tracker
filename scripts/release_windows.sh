#!/usr/bin/env bash
# ============================================================
# release_windows.sh - One-click build & publish of the Windows EXE
#
# Usage:
#   ./scripts/release_windows.sh                  # use a default commit message
#   ./scripts/release_windows.sh "feat: xxx"      # pass a custom commit message
#
# Flow: commit + push -> trigger GitHub Actions "Build Windows EXE"
#       -> wait for completion -> download Express.exe into dist/
#
# Deps: git, curl, python3 (JSON parsing) + a GitHub token (see TOKEN SOURCE)
#
# TOKEN SOURCE (never printed in the terminal):
#   - env vars $GH_TOKEN / $GITHUB_TOKEN
#   - <script-dir>/.gitsh/config.toml   (kept locally only, excluded by .gitignore)
#   - ${XDG_CONFIG_HOME:-~/.config}/gitsh/config.toml
#
# Runs on macOS / Linux with plain Bash; on Windows use WSL or Git Bash.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
GITSH_SCRIPT="${SCRIPT_DIR}/gitsh.sh"

WORKFLOW_REL=".github/workflows/build-windows.yml"
ARTIFACT_NAME="Express-windows-exe"
OUT_DIR="${ROOT_DIR}/dist"
ZIP_PATH="${OUT_DIR}/express-windows-exe.zip"
POLL_TIMEOUT=60          # max number of polling attempts
POLL_INTERVAL=15         # interval between polls (seconds)

GH_API="https://api.github.com"
CONFIG_HINT="GH_TOKEN env, ${SCRIPT_DIR}/.gitsh/config.toml, or ~/.config/gitsh/config.toml"
REPO=""
BRANCH=""
RUN_ID=""

# ---------- Color output ----------
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }

# ---------- Generic helpers ----------
run() {
  if "$@"; then
    return 0
  else
    local exit_code=$?
    error "Command failed (exit ${exit_code}): $*"
    return "${exit_code}"
  fi
}

cmd_exists() { command -v "$1" >/dev/null 2>&1; }

current_branch() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null
}

has_uncommitted_changes() {
  [ -n "$(git status --porcelain 2>/dev/null)" ]
}

# Idempotent: local tree is clean AND HEAD is already on origin/main
is_clean_and_synced() {
  has_uncommitted_changes && return 1
  [ "$(git rev-parse HEAD 2>/dev/null)" = "$(git rev-parse origin/main 2>/dev/null || echo none)" ]
}

json_get() {
  local key="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('${key}') or '')"
  elif command -v jq >/dev/null 2>&1; then
    jq -r --arg k "${key}" '.[$k] // empty'
  else
    sed -n "s/.*\"${key}\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" | head -1
  fi
}

github_api() {
  local method="$1" path="$2" body="${3:-}"
  local url="${GH_API}${path}"
  local -a curl_args

  [ -n "${GITHUB_TOKEN:-}" ] || die "GH_TOKEN (or GITHUB_TOKEN) not set. Configure via: ${CONFIG_HINT}"

  curl_args=(-sS -X "${method}" "${url}"
    -H "Authorization: Bearer ${GITHUB_TOKEN}"
    -H "Accept: application/vnd.github+json"
    -H "X-GitHub-Api-Version: 2022-11-28")
  if [ -n "${body}" ]; then
    curl_args+=(-H "Content-Type: application/json" -d "${body}")
  fi
  curl "${curl_args[@]}"
}

github_api_status() {
  local method="$1" path="$2" body="${3:-}"
  local url="${GH_API}${path}"
  local -a curl_args

  [ -n "${GITHUB_TOKEN:-}" ] || die "GH_TOKEN (or GITHUB_TOKEN) not set. Configure via: ${CONFIG_HINT}"

  curl_args=(-sS -o /dev/null -w '%{http_code}' -X "${method}" "${url}"
    -H "Authorization: Bearer ${GITHUB_TOKEN}"
    -H "Accept: application/vnd.github+json"
    -H "X-GitHub-Api-Version: 2022-11-28")
  if [ -n "${body}" ]; then
    curl_args+=(-H "Content-Type: application/json" -d "${body}")
  fi
  curl "${curl_args[@]}"
}

require_deps() {
  for c in git curl python3; do
    cmd_exists "$c" || die "Missing dependency: ${c} (install it first)"
  done
  [ -f "${GITSH_SCRIPT}" ] || die "Push script not found: ${GITSH_SCRIPT}"
  [ -f "${ROOT_DIR}/${WORKFLOW_REL}" ] || die "Workflow file not found: ${WORKFLOW_REL}"
}

# ---------- Token resolution (never prints the token) ----------
# Reads a TOML config and writes token / user into GH_TOKEN / GITHUB_USER (in-memory only).
read_config() {
  local file="$1" key val
  [ -f "${file}" ] || return 1
  while IFS='=' read -r key val; do
    key="$(printf '%s' "${key}" | xargs)"
    val="$(printf '%s' "${val}" | sed -E 's/^[[:space:]]*["'"'"']//; s/["'"'"'][[:space:]]*$//; s/[[:space:]]*$//')"
    case "${key}" in
      token|gh_token|github_token) GH_TOKEN="${val}" ;;
      user|github_user)            GITHUB_USER="${val}" ;;
    esac
  done < "${file}"
  [ -n "${GH_TOKEN:-}" ]
}

resolve_token() {
  # The environment variable takes precedence
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    [ -n "${GITHUB_USER:-}" ] && export GITHUB_USER
    return 0
  fi
  if [ -n "${GH_TOKEN:-}" ]; then
    export GITHUB_TOKEN="${GH_TOKEN}"
    [ -n "${GITHUB_USER:-}" ] && export GITHUB_USER
    return 0
  fi

  local cfg
  for cfg in \
    "${SCRIPT_DIR}/.gitsh/config.toml" \
    "${XDG_CONFIG_HOME}/gitsh/config.toml"; do
    if read_config "${cfg}" && [ -n "${GH_TOKEN:-}" ]; then
      export GITHUB_TOKEN="${GH_TOKEN}"
      [ -n "${GITHUB_USER:-}" ] && export GITHUB_USER
      return 0
    fi
  done

  die "No GitHub token found. Set the GH_TOKEN env var or configure it in one of:\n  ${SCRIPT_DIR}/.gitsh/config.toml\n  ${XDG_CONFIG_HOME}/gitsh/config.toml"
}

# ---------- Step helpers ----------
# Parse owner/repo from origin
owner_repo() {
  local url
  url="$(git -C "${ROOT_DIR}" remote get-url origin 2>/dev/null)" || die "origin remote not found"
  printf '%s' "${url}" | sed -E \
    -e 's#.*github\.com[:/]##' \
    -e 's#\.git$##'
}

# ---------- Steps ----------
step_push() {
  info "1/4 Commit and push current code ..."
  local msg="${1:-release: build Windows EXE $(date '+%Y-%m-%d_%H:%M:%S')}"

  # Idempotent: skip the git push when there are no local changes and HEAD is already in sync with origin/main
  if is_clean_and_synced; then
    info "Working tree clean and synced with origin/main, skipping push"
    return 0
  fi

  run bash "${GITSH_SCRIPT}" push "${msg}" || die "git push failed, check gitsh.sh output"
  info "Commit and push complete"
}

step_trigger() {
  info "2/4 Trigger GitHub Actions build ..."
  REPO="$(owner_repo)"
  BRANCH="$(current_branch)"
  [ -n "${BRANCH}" ] || BRANCH="main"
  info "Repo: ${REPO}  Branch: ${BRANCH}"

  # Fire and forget; 204 means the workflow was enqueued
  local code
  code="$(github_api_status POST "/repos/${REPO}/actions/workflows/${WORKFLOW_REL##*/}/dispatches" "{\"ref\":\"${BRANCH}\"}")"
  [ "${code}" = "204" ] || die "Failed to trigger workflow HTTP=${code}"
  info "Triggered ${WORKFLOW_REL}"

  # Fetch the latest run ID
  sleep 5
  local runs rid
  runs="$(github_api GET "/repos/${REPO}/actions/runs?per_page=1")"
  rid="$(printf '%s' "${runs}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["workflow_runs"][0]["id"] if d.get("workflow_runs") else "")' 2>/dev/null)"
  [ -n "${rid}" ] || die "Unable to resolve run ID"
  RUN_ID="${rid}"
  info "Run ID: ${RUN_ID}"
}

step_wait() {
  info "3/4 Waiting for build to complete ..."
  local status="" concl="" i s
  for i in $(seq 1 "${POLL_TIMEOUT}"); do
    s="$(github_api GET "/repos/${REPO}/actions/runs/${RUN_ID}" 2>/dev/null || true)"
    status="$(printf '%s' "${s}" | json_get status)"
    concl="$(printf '%s' "${s}" | json_get conclusion)"
    printf '\r  [%02d] status=%s conclusion=%s   ' "${i}" "${status}" "${concl}"
    if [ "${status}" = "completed" ]; then printf '\n'; break; fi
    sleep "${POLL_INTERVAL}"
  done
  printf '\n'
  [ "${status}" = "completed" ] || die "Timed out waiting (status=${status})"
  [ "${concl}" = "success" ] || die "Build did not succeed conclusion=${concl}"
  info "Build succeeded conclusion=${concl}"
}

step_download() {
  info "4/4 Downloading Express.exe ..."
  local arts aid aid_by_name
  arts="$(github_api GET "/repos/${REPO}/actions/runs/${RUN_ID}/artifacts")"
  aid_by_name="$(printf '%s' "${arts}" | python3 -c 'import sys,json;d=json.load(sys.stdin);a=[x for x in d.get("artifacts",[]) if x.get("name")=="'"${ARTIFACT_NAME}"'"];print(a[0]["id"] if a else "")' 2>/dev/null)"
  if [ -n "${aid_by_name}" ]; then
    aid="${aid_by_name}"
  else
    aid="$(printf '%s' "${arts}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["artifacts"][0]["id"] if d.get("artifacts") else "")' 2>/dev/null)"
  fi
  [ -n "${aid}" ] || die "Unable to resolve Artifact ID"

  mkdir -p "${OUT_DIR}"
  rm -f "${ZIP_PATH}"
  curl -sSL -o "${ZIP_PATH}" -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
    "${GH_API}/repos/${REPO}/actions/artifacts/${aid}/zip"
  [ -s "${ZIP_PATH}" ] || die "Downloaded zip is empty"

  python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "${ZIP_PATH}" "${OUT_DIR}"
  rm -f "${ZIP_PATH}"

  [ -f "${OUT_DIR}/Express.exe" ] || die "Express.exe not found after extraction"
  info "Downloaded to: ${OUT_DIR}/Express.exe"
  echo ""
  printf '  %s\n' "$(file "${OUT_DIR}/Express.exe" 2>/dev/null || echo "PE executable")"
  printf '  size: %s bytes\n' "$(wc -c < "${OUT_DIR}/Express.exe" | tr -d ' ')"
}

# ---------- main ----------
main() {
  require_deps
  resolve_token
  step_push "$@"
  step_trigger
  step_wait
  step_download
  info "All done! Windows build is at ${OUT_DIR}/Express.exe"
  echo ""
  warn "Hint: if Windows SmartScreen warns on first run of express.exe, click 'Run anyway'."
}

main "$@"
