#!/usr/bin/env bash
# release_windows.sh — 一键发布 Windows 版
#
# 作用：把当前代码 提交→推送 → 触发 GitHub Actions「Build Windows EXE」→ 等待完成 → 下载 Express.exe 到 dist/
#
# 用法：
#   ./scripts/release_windows.sh                # 用默认提交信息
#   ./scripts/release_windows.sh "feat: xxx"    # 自定义提交信息
#
# 依赖：
#   - git、curl、python3（解析 JSON）
#   - GitHub 访问令牌（见下方 TOKEN 来源）
#
# TOKEN 来源（脚本永远不在终端打印令牌）：
#   - 环境变量 $GH_TOKEN / $GITHUB_TOKEN
#   - <项目>/.gitsh/config.toml   (仅本地保存，已被 .gitignore 排除)
#   - ~/.config/gitsh/config.toml
#
# 本脚本通过 Bash 兼容（macOS / Linux）运行；Windows 上请在 WSL 或 Git Bash 中运行。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
GITSH_SCRIPT="${SCRIPT_DIR}/gitsh.sh"

WORKFLOW_REL=".github/workflows/build-windows.yml"
ARTIFACT_NAME="Express-windows-exe"
OUT_DIR="${ROOT_DIR}/dist"
ZIP_PATH="${OUT_DIR}/express-windows-exe.zip"
POLL_TIMEOUT=60          # 最多轮询次数
POLL_INTERVAL=15         # 每次间隔秒数

REPO=""
BRANCH=""

# ---------------- 输出与工具 ----------------
info() { printf '\033[1;34m[release]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[release]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[release]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[release]\033[0m %s\n' "$*" >&2; }

die() {
  err "$*"
  exit 1
}

cmd_exists() { command -v "$1" >/dev/null 2>&1; }

require_deps() {
  for c in git curl python3; do
    cmd_exists "$c" || die "缺少依赖: $c（请先安装）"
  done
  [ -f "${GITSH_SCRIPT}" ] || die "未找到推送脚本: ${GITSH_SCRIPT}"
  [ -f "${ROOT_DIR}/${WORKFLOW_REL}" ] || die "未找到工作流: ${WORKFLOW_REL}"
}

# ---------------- Token 读取（不打印令牌） ----------------
# 读取一个 TOML 配置，把 token / user 写入 GH_TOKEN / GITHUB_USER（仅内存变量）。
_read_config() {
  local file="$1" key val
  [ -f "$file" ] || return 1
  while IFS='=' read -r key val; do
    key="$(printf '%s' "$key" | xargs)"
    val="$(printf '%s' "$val" | sed -E 's/^[[:space:]]*["'"'"']//; s/["'"'"'][[:space:]]*$//; s/[[:space:]]*$//')"
    case "$key" in
      token|gh_token|github_token) GH_TOKEN="$val" ;;
      user|github_user)            GITHUB_USER="$val" ;;
    esac
  done < "$file"
  [ -n "${GH_TOKEN:-}" ]
}

_resolve_token() {
  # 环境变量优先
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
    if _read_config "${cfg}" && [ -n "${GH_TOKEN:-}" ]; then
      export GITHUB_TOKEN="${GH_TOKEN}"
      [ -n "${GITHUB_USER:-}" ] && export GITHUB_USER
      return 0
    fi
  done

  die "找不到 GitHub 令牌。请设置环境变量 GH_TOKEN，或在以下任一位置配置：\n  ${SCRIPT_DIR}/.gitsh/config.toml\n  ${XDG_CONFIG_HOME}/gitsh/config.toml"
}

# ---------------- GitHub API 封装 ----------------
GH_API="https://api.github.com"

# 解析 origin 得到 owner/repo
_owner_repo2() {
  local url
  url="$(git -C "${ROOT_DIR}" remote get-url origin 2>/dev/null)" || die "未找到 origin 远端"
  printf '%s' "$url" | sed -E \
    -e 's#.*github\.com[:/]##' \
    -e 's#\.git$##'
}

# ---------------- 各步骤 ----------------
step_push() {
  info "1/4 提交并推送当前代码 ..."
  local msg="${1:-release: build Windows EXE $(date '+%Y-%m-%d_%H:%M:%S')}"
  bash "${GITSH_SCRIPT}" push "${msg}" || die "git 推送失败，请检查 gitsh.sh 输出"
  ok "提交并推送完成"
}

step_trigger() {
  info "2/4 触发 GitHub Actions 构建 ..."
  REPO="$(_owner_repo2)"
  BRANCH="$(git -C "${ROOT_DIR}" branch --show-current)"
  [ -n "${BRANCH}" ] || BRANCH="main"
  [ -n "${REPO}" ] || die "无法解析 owner/repo"
  info "仓库: ${REPO}  分支: ${BRANCH}"

  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "${GH_API}/repos/${REPO}/actions/workflows/${WORKFLOW_REL##*/}/dispatches" \
    -d "{\"ref\":\"${BRANCH}\"}")"
  [ "${code}" = "204" ] || die "触发工作流失败 HTTP=${code}"
  ok "已触发 ${WORKFLOW_REL}"

  # 取最近一次运行 ID
  sleep 5
  local runs rid
  runs="$(curl -sS -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
    "${GH_API}/repos/${REPO}/actions/runs?per_page=1")"
  rid="$(printf '%s' "${runs}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["workflow_runs"][0]["id"] if d.get("workflow_runs") else "")' 2>/dev/null)"
  [ -n "${rid}" ] || die "未解析到运行 ID"
  RUN_ID="${rid}"
  ok "运行 ID: ${RUN_ID}"
}

step_wait() {
  info "3/4 等待构建完成 ..."
  local status="" concl="" i s
  for i in $(seq 1 "${POLL_TIMEOUT}"); do
    s="$(curl -sS -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
      "${GH_API}/repos/${REPO}/actions/runs/${RUN_ID}" || true)"
    status="$(printf '%s' "${s}" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status","") if sys.stdin.read() else "")' 2>/dev/null || true)"
    concl="$(printf '%s' "${s}" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("conclusion","") if sys.stdin.read() else "")' 2>/dev/null || true)"
    printf '\r  [%02d] status=%s conclusion=%s   ' "${i}" "${status}" "${concl}"
    if [ "${status}" = "completed" ]; then printf '\n'; break; fi
    sleep "${POLL_INTERVAL}"
  done
  printf '\n'
  [ "${status}" = "completed" ] || die "等待超时（status=${status}）"
  [ "${concl}" = "success" ] || die "构建未成功 conclusion=${concl}"
  ok "构建成功 conclusion=${concl}"
}

step_download() {
  info "4/4 下载 Express.exe ..."
  local arts aid aid_by_name
  arts="$(curl -sS -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
    "${GH_API}/repos/${REPO}/actions/runs/${RUN_ID}/artifacts")"
  aid_by_name="$(printf '%s' "${arts}" | python3 -c 'import sys,json;d=json.load(sys.stdin);a=[x for x in d.get("artifacts",[]) if x.get("name")=="'"${ARTIFACT_NAME}"'"];print(a[0]["id"] if a else "")' 2>/dev/null)"
  if [ -n "${aid_by_name}" ]; then
    aid="${aid_by_name}"
  else
    aid="$(printf '%s' "${arts}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["artifacts"][0]["id"] if d.get("artifacts") else "")' 2>/dev/null)"
  fi
  [ -n "${aid}" ] || die "未解析到 Artifact ID"

  mkdir -p "${OUT_DIR}"
  rm -f "${ZIP_PATH}"
  curl -sSL -o "${ZIP_PATH}" -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
    "${GH_API}/repos/${REPO}/actions/artifacts/${aid}/zip"
  [ -s "${ZIP_PATH}" ] || die "下载 zip 为空"

  python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "${ZIP_PATH}" "${OUT_DIR}"
  rm -f "${ZIP_PATH}"

  [ -f "${OUT_DIR}/Express.exe" ] || die "解压后未找到 Express.exe"
  ok "下载完成: ${OUT_DIR}/Express.exe"
  echo ""
  printf '  %s\n' "$(file "${OUT_DIR}/Express.exe" 2>/dev/null || echo "PE executable")"
  printf '  size: %s bytes\n' "$(wc -c < "${OUT_DIR}/Express.exe" | tr -d ' ')"
}

# ---------------- 主流程 ----------------
main() {
  local msg="${1:-}"
  require_deps
  _resolve_token
  step_push "${msg}"
  step_trigger
  step_wait
  step_download
  ok "全部完成！Windows 版位于 ${OUT_DIR}/Express.exe"
  echo ""
  warn "提示：express.exe 在 Windows 上首次运行若遇 SmartScreen 提示，点『仍要运行』即可。"
}

main "$@"
