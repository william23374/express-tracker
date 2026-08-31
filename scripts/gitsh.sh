#!/usr/bin/env bash
# ============================================================
# git.sh - Universal Git automation script
#
# Usage:
#   git.sh push [commit-message]
#   git.sh push <repo-name-or-url> <commit-message>
#   git.sh init . | git.sh init <name> [remote-url]
#   git.sh clone <repo-url> [folder]
#   git.sh list [--owner] [--private|--public] [--limit N]
#
# Config (TOML; env wins; else earlier file wins per key):
#   <script-dir>/.gitsh/config.toml
#   ${XDG_CONFIG_HOME:-~/.config}/gitsh/config.toml
# Keys: gh_token | GH_TOKEN | GITHUB_TOKEN, optional github_user | GITHUB_USER
#   also [github] token / user
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
GITSH_CONFIG_HINT="GH_TOKEN env, ${SCRIPT_DIR}/.gitsh/config.toml, or ~/.config/gitsh/config.toml"

# ---------- Color output ----------
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

# ---------- Config (TOML subset) ----------
# Supports: comments, [section], key = "value" | 'value' | bare
apply_config_key() {
  local section="$1" key="$2" value="$3"
  local norm="${key}"

  case "${section}" in
    github)
      case "${key}" in
        token|gh_token|github_token|GH_TOKEN|GITHUB_TOKEN) norm="GH_TOKEN" ;;
        user|gh_user|github_user|GITHUB_USER|GH_USER)       norm="GITHUB_USER" ;;
      esac
      ;;
    ''|*)
      case "${key}" in
        gh_token|GH_TOKEN|GITHUB_TOKEN|github_token) norm="GH_TOKEN" ;;
        github_user|GITHUB_USER|gh_user|GH_USER)     norm="GITHUB_USER" ;;
      esac
      ;;
  esac

  case "${norm}" in
    GH_TOKEN)
      [ -z "${GITHUB_TOKEN:-}" ] && export GITHUB_TOKEN="${value}"
      ;;
    GITHUB_USER)
      [ -z "${GITHUB_USER:-}" ] && export GITHUB_USER="${value}"
      ;;
  esac
}

load_config_file() {
  local file="$1" line key value section=""
  [ -f "${file}" ] || return 0

  while IFS= read -r line || [ -n "${line}" ]; do
    # strip CR and leading/trailing whitespace
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"

    case "${line}" in
      ''|\#*) continue ;;
      \[*\])
        section="${line#\[}"
        section="${section%\]}"
        section="${section#"${section%%[![:space:]]*}"}"
        section="${section%"${section##*[![:space:]]}"}"
        continue
        ;;
      *=*)
        key="${line%%=*}"
        value="${line#*=}"
        key="${key%"${key##*[![:space:]]}"}"
        key="${key#"${key%%[![:space:]]*}"}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        # strip inline comment for unquoted values: key = bare # comment
        case "${value}" in
          \"*)
            value="${value#\"}"
            value="${value%%\"*}"
            ;;
          \'*)
            value="${value#\'}"
            value="${value%%\'*}"
            ;;
          *)
            value="${value%%\#*}"
            value="${value%"${value##*[![:space:]]}"}"
            ;;
        esac
        apply_config_key "${section}" "${key}" "${value}"
        ;;
    esac
  done < "${file}"
}

load_config() {
  # GitHub CLI uses GH_TOKEN; Actions/CI use GITHUB_TOKEN — normalize to one.
  [ -z "${GITHUB_TOKEN:-}" ] && [ -n "${GH_TOKEN:-}" ] && export GITHUB_TOKEN="${GH_TOKEN}"

  if [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_USER:-}" ]; then
    return 0
  fi

  # Config lives under <script-dir>/.gitsh/, not the caller's cwd.
  load_config_file "${SCRIPT_DIR}/.gitsh/config.toml"
  load_config_file "${SCRIPT_DIR}/.gitsh/config"
  load_config_file "${XDG_CONFIG_HOME}/gitsh/config.toml"
  load_config_file "${XDG_CONFIG_HOME}/gitsh/config"

  [ -z "${GITHUB_TOKEN:-}" ] && [ -n "${GH_TOKEN:-}" ] && export GITHUB_TOKEN="${GH_TOKEN}"
}

git_authed() {
  # HTTPS GitHub auth via URL rewrite; token never written to remote.origin.url.
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    git \
      -c "url.https://x-access-token:${GITHUB_TOKEN}@github.com/.insteadOf=https://github.com/" \
      -c "url.https://x-access-token:${GITHUB_TOKEN}@github.com/.insteadOf=https://www.github.com/" \
      "$@"
  else
    git "$@"
  fi
}

# ---------- Helpers ----------
run() {
  if "$@"; then
    return 0
  else
    local exit_code=$?
    error "Command failed (exit ${exit_code}): $*"
    return "${exit_code}"
  fi
}

is_git_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1
}

ensure_quotepath() {
  git config core.quotepath false
}

has_remote() {
  git remote get-url origin >/dev/null 2>&1
}

current_branch() {
  git rev-parse --abbrev-ref HEAD 2>/dev/null
}

has_commits() {
  git rev-parse HEAD >/dev/null 2>&1
}

has_changes() {
  ! git diff --quiet 2>/dev/null \
    || ! git diff --cached --quiet 2>/dev/null \
    || [ -n "$(git ls-files --others --exclude-standard 2>/dev/null)" ]
}

slugify_repo_name() {
  local name="$1"
  name="$(printf '%s' "${name}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9._-]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
  [ -n "${name}" ] || name="repo"
  printf '%s' "${name}"
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
  local url="https://api.github.com${path}"
  local -a curl_args

  [ -n "${GITHUB_TOKEN:-}" ] || die "GH_TOKEN (or GITHUB_TOKEN) not set. Configure via: ${GITSH_CONFIG_HINT}"

  curl_args=(-sS -X "${method}" "${url}"
    -H "Authorization: Bearer ${GITHUB_TOKEN}"
    -H "Accept: application/vnd.github+json"
    -H "X-GitHub-Api-Version: 2022-11-28")
  if [ -n "${body}" ]; then
    curl_args+=(-H "Content-Type: application/json" -d "${body}")
  fi
  curl "${curl_args[@]}"
}

ensure_github_user() {
  [ -z "${GITHUB_USER:-}" ] || return 0

  local resp login
  resp="$(github_api GET /user)" || die "Failed to call GitHub API /user"
  login="$(printf '%s' "${resp}" | json_get login)"
  if [ -z "${login}" ]; then
    error "Unable to resolve GitHub username. API response:"
    error "${resp}"
    die "Set GITHUB_USER in config (${GITSH_CONFIG_HINT}) or check token scopes (need repo)"
  fi
  export GITHUB_USER="${login}"
  info "Detected GitHub user: ${GITHUB_USER}"
}

ensure_local_repo() {
  if is_git_repo; then
    info "Already a Git repository"
  else
    run git init || die "git init failed"
    info "git init completed"
  fi
  ensure_quotepath
  run git branch -M main || true
  info "Branch: main"
}

ensure_readme() {
  local title="$1"
  if [ ! -f README.md ]; then
    echo "# ${title}" > README.md
    info "Created README.md"
  fi
}

do_commit() {
  local commit_message="$1"
  local default_message="$2"

  if ! has_changes; then
    if has_commits; then
      warn "No local changes; skipping commit"
      return 0
    fi
    ensure_readme "$(basename "$(pwd)")"
  fi

  run git add . || die "git add failed"
  info "Staged all changes"

  [ -n "${commit_message}" ] || commit_message="${default_message}"

  if ! has_commits || ! git diff --cached --quiet 2>/dev/null; then
    run git commit -m "${commit_message}" || die "git commit failed"
    info "Committed: ${commit_message}"
  else
    warn "Nothing staged; skipping commit"
  fi
}

ensure_remote_origin() {
  local arg="${1:-}"
  local remote_url="" repo_name=""

  if has_remote; then
    remote_url="$(git remote get-url origin 2>/dev/null)"
    info "Remote origin: ${remote_url}"
    return 0
  fi

  case "${arg}" in
    https://*|git@*|ssh://*) remote_url="${arg}" ;;
    "") repo_name="$(slugify_repo_name "$(basename "$(pwd)")")" ;;
    *)  repo_name="$(slugify_repo_name "${arg}")" ;;
  esac

  if [ -z "${remote_url}" ]; then
    ensure_github_user
    remote_url="https://github.com/${GITHUB_USER}/${repo_name}.git"
    warn "No remote configured; ensuring GitHub repo: ${GITHUB_USER}/${repo_name}"

    local create_resp html_url message check
    create_resp="$(github_api POST /user/repos "{\"name\":\"${repo_name}\",\"private\":false,\"auto_init\":false}")"
    html_url="$(printf '%s' "${create_resp}" | json_get html_url)"
    message="$(printf '%s' "${create_resp}" | json_get message)"

    if [ -n "${html_url}" ]; then
      info "Created GitHub repository: ${html_url}"
    elif printf '%s' "${message}" | grep -qi "already exists"; then
      warn "Repository already exists on GitHub; reusing it"
    else
      check="$(github_api GET "/repos/${GITHUB_USER}/${repo_name}")"
      html_url="$(printf '%s' "${check}" | json_get html_url)"
      if [ -n "${html_url}" ]; then
        warn "Repository already exists: ${html_url}"
      else
        error "Failed to create or find repository ${GITHUB_USER}/${repo_name}"
        error "${create_resp}"
        die "Check token permissions (repo scope) and repo name"
      fi
    fi
  fi

  run git remote add origin "${remote_url}" || die "Failed to add remote origin"
  info "Added remote origin: ${remote_url}"
}

remote_branch_exists() {
  local branch_name="$1"
  git_authed ls-remote --heads origin "refs/heads/${branch_name}" 2>/dev/null | grep -q .
}

do_pull_rebase() {
  local branch_name="$1"
  has_remote || return 0
  if ! remote_branch_exists "${branch_name}"; then
    warn "Remote branch origin/${branch_name} does not exist yet; skip pull"
    return 0
  fi
  warn "Pulling with rebase from origin/${branch_name} ..."
  run git_authed pull --rebase origin "${branch_name}" \
    || die "git pull --rebase failed; resolve conflicts and retry"
  info "pull --rebase completed"
}

do_push() {
  local branch_name="$1"
  local set_upstream="${2:-false}"

  warn "Pushing to origin/${branch_name} ..."
  if [ "${set_upstream}" = "true" ] || ! git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
    run git_authed push -u origin "${branch_name}" || die "git push failed"
  else
    run git_authed push origin "${branch_name}" || die "git push failed"
  fi
  info "Pushed successfully: origin/${branch_name}"
}

# ---------- Command: init ----------
cmd_init() {
  local project_name="${1:-.}"
  local remote_url="$2"
  local display_name

  if [ "${project_name}" = "." ]; then
    display_name="$(basename "$(pwd)")"
    info "Initializing current directory: $(pwd)"
  else
    display_name="${project_name}"
    if [ -d "${project_name}" ]; then
      warn "Directory already exists: ${project_name}; continuing inside it"
    else
      run mkdir -p "${project_name}" || die "Failed to create directory: ${project_name}"
      info "Created directory: ${project_name}"
    fi
    cd "${project_name}" || die "Failed to enter directory: ${project_name}"
  fi

  ensure_local_repo
  ensure_readme "${display_name}"
  do_commit "chore: initial commit" "chore: initial commit"

  if [ -n "${remote_url}" ]; then
    if has_remote; then
      local existing_url
      existing_url="$(git remote get-url origin 2>/dev/null)"
      if [ "${existing_url}" = "${remote_url}" ]; then
        warn "Remote origin already exists with the same URL; skipping"
      else
        warn "Remote origin already exists (${existing_url}); updating to ${remote_url}"
        run git remote set-url origin "${remote_url}" || die "Failed to update remote origin"
      fi
    else
      run git remote add origin "${remote_url}" || die "Failed to add remote origin"
      info "Added remote origin: ${remote_url}"
    fi
    do_push main true
  else
    warn "No remote-url provided; local init only"
    warn "Tip: run  git.sh push  to auto-create GitHub repo and push"
  fi

  info "Initialization complete: $(pwd)"
}

# ---------- Command: push ----------
cmd_push() {
  # Usage: git.sh push [commit-message]
  #        git.sh push [repo-name-or-url] [commit-message]
  local arg1="${1:-}" arg2="${2:-}"
  local repo_hint="" commit_message=""

  if [ -n "${arg2}" ]; then
    repo_hint="${arg1}"
    commit_message="${arg2}"
  elif [ -n "${arg1}" ]; then
    case "${arg1}" in
      https://*|git@*|ssh://*) repo_hint="${arg1}" ;;
      *) commit_message="${arg1}" ;;
    esac
  fi

  ensure_local_repo

  local branch_name
  branch_name="$(current_branch)"
  if [ -z "${branch_name}" ] || [ "${branch_name}" = "HEAD" ]; then
    run git branch -M main || die "Failed to set branch main"
    branch_name="main"
  fi
  info "Current branch: ${branch_name}"

  if ! has_commits; then
    do_commit "${commit_message:-chore: initial commit}" "chore: initial commit"
  else
    do_commit "${commit_message}" "update: $(date '+%Y-%m-%d %H:%M:%S')"
  fi

  ensure_remote_origin "${repo_hint}"
  do_pull_rebase "${branch_name}"
  do_push "${branch_name}" true

  if has_remote; then
    info "Done: $(git remote get-url origin) (${branch_name})"
  fi
}

# ---------- Command: list ----------
cmd_list() {
  local visibility="all"
  local affiliation="owner,collaborator,organization_member"
  local limit=100 arg

  while [ $# -gt 0 ]; do
    arg="$1"; shift
    case "${arg}" in
      --all|-a)   affiliation="owner,collaborator,organization_member" ;;
      --owner|-o) affiliation="owner" ;;
      --private|-p) visibility="private" ;;
      --public)   visibility="public" ;;
      --limit|-n)
        limit="${1:-}"
        shift || die "Usage: git.sh list --limit <N>"
        case "${limit}" in ''|*[!0-9]*) die "--limit must be a positive integer" ;; esac
        ;;
      -h|--help)
        cat <<'EOF'
Usage:
  git.sh list [--all|--owner] [--private|--public] [--limit N]

Options:
  --all, -a       Include owned, collaborator, and org repos (default)
  --owner, -o     Only repos you own
  --private, -p   Private repos only
  --public        Public repos only
  --limit, -n N   Max repos to show (default 100, max 100 per page)
EOF
        return 0
        ;;
      *) die "Unknown option: ${arg} (try: git.sh list --help)" ;;
    esac
  done

  [ "${limit}" -gt 100 ] && limit=100

  ensure_github_user

  local path="/user/repos?per_page=${limit}&sort=updated&direction=desc&affiliation=${affiliation}"
  [ "${visibility}" != "all" ] && path="${path}&visibility=${visibility}"

  warn "Fetching repositories for ${GITHUB_USER} ..."
  local resp
  resp="$(github_api GET "${path}")" || die "Failed to call GitHub API /user/repos"

  local err_msg=""
  case "$(printf '%s' "${resp}" | sed -e 's/^[[:space:]]*//' | head -c 1)" in
    '{') err_msg="$(printf '%s' "${resp}" | json_get message)" ;;
  esac
  if [ -n "${err_msg}" ]; then
    error "${resp}"
    die "GitHub API error: ${err_msg}"
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    die "python3 is required to format repository list"
  fi

  printf '%s' "${resp}" | python3 -c '
import sys, json
repos = json.load(sys.stdin)
if not isinstance(repos, list):
    print("Unexpected API response", file=sys.stderr)
    sys.exit(1)
if not repos:
    print("(no repositories)")
    sys.exit(0)
name_w = max(len(r.get("full_name") or "") for r in repos)
name_w = max(name_w, 4)
print("{:<4}  {:<{nw}}  {:<7}  {:<19}  {}".format("#", "NAME", "VIS", "UPDATED", "URL", nw=name_w))
print("-" * (4 + 2 + name_w + 2 + 7 + 2 + 19 + 2 + 40))
for i, r in enumerate(repos, 1):
    name = r.get("full_name") or ""
    vis = "private" if r.get("private") else "public"
    updated = (r.get("updated_at") or "")[:19].replace("T", " ")
    url = r.get("html_url") or ""
    print("{:<4}  {:<{nw}}  {:<7}  {:<19}  {}".format(i, name, vis, updated, url, nw=name_w))
print("\nTotal: {}".format(len(repos)))
'
}

# ---------- Command: clone ----------
cmd_clone() {
  local repo_url="$1"
  local folder_name="$2"

  [ -n "${repo_url}" ] || die "Usage: git.sh clone <repo-url> [folder-name]"

  local target_dir="${folder_name:-$(basename "${repo_url}" .git)}"
  [ ! -d "${target_dir}" ] || die "Target directory already exists: ${target_dir}"

  warn "Cloning ${repo_url} -> ${target_dir} ..."
  run git_authed clone "${repo_url}" "${target_dir}" || die "git clone failed"
  info "Clone completed: ${target_dir}"

  cd "${target_dir}" || die "Failed to enter directory: ${target_dir}"
  ensure_quotepath

  if has_remote; then
    run git remote set-url origin "${repo_url}" || true
  fi

  echo
  info "Directory contents:"
  ls -la
}

# ---------- Help ----------
cmd_help() {
  cat <<'EOF'
Usage:
  git.sh push [commit-message]
      init (if needed) → commit → create GitHub repo (if needed) → pull --rebase → push

  git.sh push <repo-name-or-url> <commit-message>

  git.sh init .
  git.sh init <project-name> [remote-url]

  git.sh clone <repo-url> [folder-name]

  git.sh list [--owner] [--private|--public] [--limit N]

Config (TOML; env wins; else earlier file wins per key):
  <script-dir>/.gitsh/config.toml
  ${XDG_CONFIG_HOME:-~/.config}/gitsh/config.toml

  gh_token = "ghp_xxxxxxxx"
  github_user = "your-username"   # optional

  # or:
  # [github]
  # token = "ghp_xxxxxxxx"
  # user = "your-username"

Examples:
  git.sh push
  git.sh push "feat: add user login"
  git.sh init .
  git.sh clone https://github.com/user/repo.git
  git.sh list --owner --private
EOF
}

# ---------- main ----------
main() {
  load_config

  local command="$1"
  shift || true

  case "${command}" in
    init)          cmd_init "$@" ;;
    push)          cmd_push "$@" ;;
    clone)         cmd_clone "$@" ;;
    list|ls|repos) cmd_list "$@" ;;
    help|-h|--help|"") cmd_help ;;
    *)
      error "Unknown command: ${command}"
      cmd_help
      exit 1
      ;;
  esac
}

main "$@"
