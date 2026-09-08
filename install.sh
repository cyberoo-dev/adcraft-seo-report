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

# 2. Claude Code binary (optional: CLI or VS Code extension). The desktop app has none; that's fine.
CLAUDE_BIN="$(command -v claude || true)"
if [[ -z "$CLAUDE_BIN" ]]; then
  CLAUDE_BIN="$(ls -t "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | head -1 || true)"
fi
[[ -n "$CLAUDE_BIN" ]] && say "Claude CLI found at $CLAUDE_BIN" || say "No Claude CLI found (desktop app only); installing the engine from source instead"

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

# 5. claude-seo engine + isolated runtime + Chromium
DATA_DIR="$HOME/Library/Application Support/claude-seo"
ENGINE_DIR="$DATA_DIR/src"
mkdir -p "$DATA_DIR"
if [[ -n "$CLAUDE_BIN" ]]; then
  say "Installing / refreshing the claude-seo plugin via the CLI"
  "$CLAUDE_BIN" plugin marketplace add AgriciDaniel/claude-seo >/dev/null 2>&1 || true
  "$CLAUDE_BIN" plugin install claude-seo@agricidaniel-claude-seo >/dev/null 2>&1 || "$CLAUDE_BIN" plugin update claude-seo@agricidaniel-claude-seo >/dev/null 2>&1 || true
fi
RUNTIME="$(ls -d "$HOME"/.claude/plugins/cache/agricidaniel-claude-seo/claude-seo/*/scripts/runtime.py 2>/dev/null | sort -V | tail -1 || true)"
if [[ -z "$RUNTIME" ]]; then
  if [[ -d "$ENGINE_DIR/.git" ]]; then say "Updating claude-seo engine in $ENGINE_DIR"; git -C "$ENGINE_DIR" pull --ff-only -q
  else say "Cloning claude-seo engine into $ENGINE_DIR"; git clone -q --depth 1 https://github.com/AgriciDaniel/claude-seo.git "$ENGINE_DIR"; fi
  RUNTIME="$ENGINE_DIR/scripts/runtime.py"
  "$PY" - "$SETTINGS" "$ENGINE_DIR" "$DATA_DIR" <<'EOF2'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]); d = json.loads(p.read_text()) if p.exists() else {}
d.setdefault("env", {}).update({"CLAUDE_SEO_ROOT": sys.argv[2], "CLAUDE_SEO_DATA_DIR": sys.argv[3]})
p.write_text(json.dumps(d, indent=2) + "\n")
EOF2
fi
say "Setting up the claude-seo Python runtime and Chromium (first time takes a few minutes)"
CLAUDE_SEO_PYTHON="$PY" CLAUDE_SEO_DATA_DIR="$DATA_DIR" "$PY" "$RUNTIME" setup >/dev/null
CLAUDE_SEO_PYTHON="$PY" CLAUDE_SEO_DATA_DIR="$DATA_DIR" "$PY" "$RUNTIME" doctor --json | grep -q '"ready": true' && say "Runtime ready" || { echo "Runtime not ready; re-run this installer or run '/seo setup' inside Claude Code." >&2; }

# 6. Keys file
mkdir -p "$CONF_DIR"; chmod 700 "$CONF_DIR"
if [[ ! -f "$CONF_DIR/keys.env" ]]; then
  cp "$SKILL_DIR/keys.env.example" "$CONF_DIR/keys.env"
  chmod 600 "$CONF_DIR/keys.env"
  say "Created $CONF_DIR/keys.env. Paste your API keys into it (copy the file from your other Mac)."
else
  say "Keys file already present at $CONF_DIR/keys.env"
fi

# 7. Reports workspace: project-level skill link + CLAUDE.md so the skill works even if user skills are not listed
WORK="$HOME/adcraft-seo-reports"
mkdir -p "$WORK/.claude/skills"
[[ -e "$WORK/.claude/skills/seo-report" ]] || ln -s "$SKILL_DIR" "$WORK/.claude/skills/seo-report"
cp "$SKILL_DIR/project-template/CLAUDE.md" "$WORK/CLAUDE.md"
say "Reports workspace ready at $WORK"

say "Done. Open $WORK in Claude Code, start a new session and run:  /seo-report <url>"
