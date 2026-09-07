# One-shot installer / updater for the Adcraft SEO report skill on Windows.
#   powershell -ExecutionPolicy Bypass -c "iwr -useb https://raw.githubusercontent.com/cyberoo-dev/adcraft-seo-report/main/install.ps1 | iex"
# or from a clone:  powershell -ExecutionPolicy Bypass -File .\install.ps1
# Safe to re-run: every step is idempotent. No GitHub sign-in is needed as long as the repo is readable.
$ErrorActionPreference = "Stop"
$Repo     = "https://github.com/cyberoo-dev/adcraft-seo-report.git"
$SkillDir = Join-Path $env:USERPROFILE ".claude\skills\seo-report"
$ConfDir  = Join-Path $env:USERPROFILE ".config\adcraft-seo"
$Settings = Join-Path $env:USERPROFILE ".claude\settings.json"
function Say($m) { Write-Host "==> $m" -ForegroundColor Cyan }

# 0. git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Say "Installing Git via winget"
  winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

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

# 2. Claude Code binary
$Claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $Claude) {
  $Claude = Get-ChildItem "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Claude) { Write-Error "Claude Code not found. Install Claude Code (CLI or VS Code extension) and re-run."; exit 1 }
Say "Using Claude Code at $Claude"

# 3. Python 3.10+
$Py = $null
foreach ($cand in @("python3.12", "python3.11", "python3.10", "python", "py")) {
  $cmd = Get-Command $cand -ErrorAction SilentlyContinue
  if ($cmd) {
    $ok = & $cmd.Source -c "import sys; print(1 if sys.version_info >= (3,10) else 0)" 2>$null
    if ($ok -eq "1") { $Py = $cmd.Source; break }
  }
}
if (-not $Py) {
  Say "Installing Python 3.12 via winget"
  winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
  $Py = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Py) { Write-Error "Python 3.10+ not found after install. Install it from python.org and re-run."; exit 1 }
Say "Python for claude-seo: $Py"

# 4. Persist CLAUDE_SEO_PYTHON in Claude Code settings env
New-Item -ItemType Directory -Force -Path (Split-Path $Settings) | Out-Null
$json = if (Test-Path $Settings) { Get-Content $Settings -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
if (-not $json.PSObject.Properties["env"]) { $json | Add-Member -NotePropertyName env -NotePropertyValue ([pscustomobject]@{}) }
$json.env | Add-Member -NotePropertyName CLAUDE_SEO_PYTHON -NotePropertyValue $Py -Force
$json | ConvertTo-Json -Depth 10 | Set-Content $Settings -Encoding UTF8

# 5. claude-seo plugin + runtime
Say "Installing / refreshing the claude-seo plugin"
& $Claude plugin marketplace add AgriciDaniel/claude-seo 2>$null | Out-Null
& $Claude plugin install claude-seo@agricidaniel-claude-seo 2>$null | Out-Null
$PluginBin = Get-ChildItem "$env:USERPROFILE\.claude\plugins\cache\agricidaniel-claude-seo\claude-seo\*\bin\claude-seo" -ErrorAction SilentlyContinue |
             Sort-Object FullName | Select-Object -Last 1 -ExpandProperty FullName
if (-not $PluginBin) { Write-Error "claude-seo plugin did not install. In Claude Code run: /plugin install claude-seo@agricidaniel-claude-seo"; exit 1 }
$RuntimePy = Join-Path (Split-Path (Split-Path $PluginBin)) "scripts\runtime.py"
Say "Setting up the claude-seo Python runtime and Chromium (first time takes a few minutes)"
$env:CLAUDE_SEO_PYTHON = $Py
& $Py $RuntimePy setup | Out-Null
& $Py $RuntimePy doctor --json | Select-String '"ready": true' | Out-Null
if ($?) { Say "Runtime ready" } else { Write-Warning "Runtime not ready, run '/seo setup' inside Claude Code." }

# 6. Keys file (never committed; keep private)
New-Item -ItemType Directory -Force -Path $ConfDir | Out-Null
$Keys = Join-Path $ConfDir "keys.env"
if (-not (Test-Path $Keys)) {
  Copy-Item (Join-Path $SkillDir "keys.env.example") $Keys
  # restrict to the current Windows user only
  icacls $Keys /inheritance:r /grant:r "$env:USERNAME:(R,W)" | Out-Null
  Say "Created $Keys (readable only by $env:USERNAME). Paste your API keys into it."
} else { Say "Keys file already present at $Keys" }

Say "Done. In Claude Code run:  /seo-report <url>   (open a new session so the skill loads)"
