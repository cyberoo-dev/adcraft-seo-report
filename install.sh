#!/usr/bin/env bash
# One-shot installer / updater for the Adcraft SEO report skill on a Mac.
#   curl -fsSL https://raw.githubusercontent.com/cyberoo-dev/adcraft-seo-report/main/install.sh | bash
# or, from a clone:  ./install.sh
# Safe to re-run: every step is idempotent.
set -euo pipefail

REPO="https://github.com/cyberoo-dev/adcraft-seo-report.git"
SKILL_DIR="$HOME/.claude/skills/seo-report"
CONF_DIR="$HOME/.config/adcraft-seo"
SETTINGS="$HOME/.claude/settings.json"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# 1. Skill files (git clone or pull)
if [[ -d "$SKILL_DIR/.git" ]]; then
  say "Updating skill in $SKILL_DIR"
  git -C "$SKILL_DIR" pull --ff-only -q || git -C "$SKILL_DIR" pull --rebase -q
else
  if [[ -d "$SKILL_DIR" ]]; then
    say "Backing up existing non-git skill dir to ${SKILL_DIR}.bak"
    mv "$SKILL_DIR" "${SKILL_DIR}.bak"
  fi
  say "Cloning skill into $SKILL_DIR"
  mkdir -p "$HOME/.claude/skills"
  git clone -q "$REPO" "$SKILL_DIR"
fi
chmod +x "$SKILL_DIR/run.sh" "$SKILL_DIR/install.sh"

# 2. Claude Code binary (CLI, VS Code extension, or desktop app)
CLAUDE_BIN="$(command -v claude || true)"
if [[ -z "$CLAUDE_BIN" ]]; then
  CLAUDE_BIN="$(ls -t "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | head -1 || true)"
fi
if [[ -z "$CLAUDE_BIN" ]]; then
  echo "Claude Code binary not found. Install Claude Code, then re-run this script." >&2
  exit 1
fi
say "Using Claude Code at $CLAUDE_BIN ($("$CLAUDE_BIN" --version 2>/dev/null | head -1))"

# 3. Python 3.10+ (via uv if the system Python is too old)
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$(command -v "$cand")"; break
  fi
done
if [[ -z "$PY" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv (Python manager)"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
    export PATH="$HOME/.local/bin:$PATH"
  fi
  say "Installing Python 3.12 with uv"
  uv python install 3.12 >/dev/null
  PY="$(uv python find 3.12)"
fi
say "Python for claude-seo: $PY"

# 4. Persist CLAUDE_SEO_PYTHON in Claude Code settings env
mkdir -p "$HOME/.claude"
"$PY" - "$SETTINGS" "$PY" <<'EOF'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); py = sys.argv[2]
d = json.loads(p.read_text()) if p.exists() else {}
d.setdefault("env", {})["CLAUDE_SEO_PYTHON"] = py
p.write_text(json.dumps(d, indent=2) + "\n")
EOF

# 5. claude-seo plugin (engine) and its isolated runtime + Chromium
say "Installing / refreshing the claude-seo plugin"
"$CLAUDE_BIN" plugin marketplace add AgriciDaniel/claude-seo >/dev/null 2>&1 || true
"$CLAUDE_BIN" plugin install claude-seo@agricidaniel-claude-seo >/dev/null 2>&1 || "$CLAUDE_BIN" plugin update claude-seo@agricidaniel-claude-seo >/dev/null 2>&1 || true
PLUGIN_BIN="$(ls -d "$HOME"/.claude/plugins/cache/agricidaniel-claude-seo/claude-seo/*/bin/claude-seo 2>/dev/null | sort -V | tail -1 || true)"
if [[ -z "$PLUGIN_BIN" ]]; then
  echo "claude-seo plugin did not install. Open Claude Code and run: /plugin install claude-seo@agricidaniel-claude-seo" >&2
  exit 1
fi
say "Setting up the claude-seo Python runtime and Chromium (first time takes a few minutes)"
CLAUDE_SEO_PYTHON="$PY" "$PLUGIN_BIN" setup >/dev/null
CLAUDE_SEO_PYTHON="$PY" "$PLUGIN_BIN" doctor --json | grep -q '"ready": true' && say "Runtime ready" || { echo "Runtime not ready, run '/seo setup' inside Claude Code." >&2; }

# 6. Keys file
mkdir -p "$CONF_DIR"; chmod 700 "$CONF_DIR"
if [[ ! -f "$CONF_DIR/keys.env" ]]; then
  cp "$SKILL_DIR/keys.env.example" "$CONF_DIR/keys.env"
  chmod 600 "$CONF_DIR/keys.env"
  say "Created $CONF_DIR/keys.env. Paste your API keys into it (copy the file from your other Mac)."
else
  say "Keys file already present at $CONF_DIR/keys.env"
fi

say "Done. In Claude Code run:  /seo-report <url>   (open a new session so the skill loads)"
