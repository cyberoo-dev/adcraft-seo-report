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
script="$1"; shift
exec "$VENV_PY" "$SKILL_DIR/scripts/$script" "$@"
