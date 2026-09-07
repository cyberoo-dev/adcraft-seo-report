#!/usr/bin/env bash
# Launcher for the Adcraft SEO report scripts. Uses the claude-seo plugin's isolated
# Python runtime (bs4, lxml, requests, playwright + Chromium already installed).
# Usage: run.sh <script.py> [args...]
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$HOME/Library/Application Support/claude-seo"
VENV_PY="$DATA_DIR/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "claude-seo runtime not found at $VENV_PY. Run '/seo setup' in Claude Code first." >&2
  exit 1
fi
export PLAYWRIGHT_BROWSERS_PATH="$DATA_DIR/ms-playwright"
export no_proxy="*"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export CLAUDE_SEO_PYTHON="${CLAUDE_SEO_PYTHON:-$VENV_PY}"
# Keep both Macs on the latest version: quiet fast-forward pull at most once a day (10s cap).
STAMP="$SKILL_DIR/.last-pull"
if [[ -d "$SKILL_DIR/.git" ]] && [[ -z "${SEO_REPORT_NO_PULL:-}" ]] && { [[ ! -f "$STAMP" ]] || [[ $(( $(date +%s) - $(stat -f %m "$STAMP") )) -gt 86400 ]]; }; then
  ( cd "$SKILL_DIR" && GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=8 git pull --ff-only -q >/dev/null 2>&1 & ); touch "$STAMP"
fi
script="$1"; shift
exec "$VENV_PY" "$SKILL_DIR/scripts/$script" "$@"
