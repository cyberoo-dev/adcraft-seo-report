# One-shot installer / updater for the Adcraft SEO report skill on Windows.
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#   iwr -useb https://raw.githubusercontent.com/cyberoo-dev/adcraft-seo-report/main/install.ps1 | iex
# Works with the Claude Code desktop app, the VS Code extension or the CLI. Safe to re-run.
$ErrorActionPreference = "Stop"
$Repo       = "https://github.com/cyberoo-dev/adcraft-seo-report.git"
$EngineRepo = "https://github.com/AgriciDaniel/claude-seo.git"
$SkillDir   = Join-Path $env:USERPROFILE ".claude\skills\seo-report"
$ConfDir    = Join-Path $env:USERPROFILE ".config\adcraft-seo"
$Settings   = Join-Path $env:USERPROFILE ".claude\settings.json"
$DataDir    = Join-Path $env:LOCALAPPDATA "claude-seo"
$EngineDir  = Join-Path $DataDir "src"
function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function RefreshPath { $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") }

# 0. git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Say "Installing Git via winget"
  winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
  RefreshPath
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Error "Git still not found. Install from https://git-scm.com and re-run."; exit 1 }

# 1. Skill files
if (Test-Path (Join-Path $SkillDir ".git")) {
  Say "Updating skill in $SkillDir"
  git -C $SkillDir pull --ff-only -q
} else {
  if (Test-Path $SkillDir) { Rename-Item $SkillDir "$SkillDir.bak" -Force }
  Say "Cloning skill into $SkillDir"
  New-Item -ItemType Directory -Force -Path (Split-Path $SkillDir) | Out-Null
  git clone -q $Repo $SkillDir
}

# 2. Python 3.10+
$Py = $null
foreach ($cand in @("python3.12", "python3.11", "python3.10", "python", "py")) {
  $cmd = Get-Command $cand -ErrorAction SilentlyContinue
  if ($cmd) {
    try { $ok = & $cmd.Source -c "import sys; print(1 if sys.version_info >= (3,10) else 0)" 2>$null } catch { $ok = "0" }
    if ("$ok".Trim() -eq "1") { $Py = $cmd.Source; break }
  }
}
if (-not $Py) {
  Say "Installing Python 3.12 via winget"
  winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
  RefreshPath
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { $Py = $cmd.Source }
}
if (-not $Py) { Write-Error "Python 3.10+ not found after install. Install it from python.org (tick 'Add to PATH') and re-run."; exit 1 }
Say "Python: $Py"

# 3. Engine (claude-seo) source + isolated runtime + Chromium. No Claude binary required.
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
if (Test-Path (Join-Path $EngineDir ".git")) {
  Say "Updating claude-seo engine in $EngineDir"
  git -C $EngineDir pull --ff-only -q
} else {
  Say "Cloning claude-seo engine into $EngineDir"
  git clone -q --depth 1 $EngineRepo $EngineDir
}
$env:CLAUDE_SEO_PYTHON   = $Py
$env:CLAUDE_SEO_DATA_DIR = $DataDir
$Runtime = Join-Path $EngineDir "scripts\runtime.py"
Say "Setting up the Python runtime and Chromium (first time takes a few minutes)"
& $Py $Runtime setup
$doc = & $Py $Runtime doctor --json 2>$null | Out-String
if ($doc -match '"ready":\s*true') { Say "Runtime ready" } else { Write-Warning "Runtime not ready. Output:`n$doc" }

# 4. Persist env for Claude Code (desktop app, VS Code extension and CLI all read this file)
New-Item -ItemType Directory -Force -Path (Split-Path $Settings) | Out-Null
$json = if (Test-Path $Settings) { Get-Content $Settings -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
if (-not $json.PSObject.Properties["env"]) { $json | Add-Member -NotePropertyName env -NotePropertyValue ([pscustomobject]@{}) }
$json.env | Add-Member -NotePropertyName CLAUDE_SEO_PYTHON   -NotePropertyValue $Py        -Force
$json.env | Add-Member -NotePropertyName CLAUDE_SEO_DATA_DIR -NotePropertyValue $DataDir   -Force
$json.env | Add-Member -NotePropertyName CLAUDE_SEO_ROOT     -NotePropertyValue $EngineDir -Force
$json | ConvertTo-Json -Depth 10 | Set-Content $Settings -Encoding UTF8

# 5. Optional: register the plugin with the CLI if one exists (gives /seo commands too)
$Claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if ($Claude) {
  Say "Registering the claude-seo plugin with the Claude CLI"
  & $Claude plugin marketplace add AgriciDaniel/claude-seo 2>$null | Out-Null
  & $Claude plugin install claude-seo@agricidaniel-claude-seo 2>$null | Out-Null
}

# 6. Keys file (never committed; keep private)
New-Item -ItemType Directory -Force -Path $ConfDir | Out-Null
$Keys = Join-Path $ConfDir "keys.env"
if (-not (Test-Path $Keys)) {
  Copy-Item (Join-Path $SkillDir "keys.env.example") $Keys
  icacls $Keys /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null
  Say "Created $Keys (readable only by $env:USERNAME). Add RELAY_URL and RELAY_TOKEN to it."
} else { Say "Keys file already present at $Keys" }

Say "Done. Open a NEW Claude Code session and run:  /seo-report <url>"
