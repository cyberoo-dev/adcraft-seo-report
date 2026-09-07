# Windows launcher for the Adcraft SEO report scripts.
# Usage: powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.claude\skills\seo-report\run.ps1" <script.py> [args...]
#   or:  "$env:USERPROFILE\.claude\skills\seo-report\run.cmd" <script.py> [args...]
# Uses the claude-seo plugin's isolated Python runtime (bs4, lxml, requests, playwright + Chromium).
$ErrorActionPreference = "Stop"
$SkillDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir  = Join-Path $env:LOCALAPPDATA "claude-seo"
$VenvPy   = Join-Path $DataDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
  Write-Error "claude-seo runtime not found at $VenvPy. Run '/seo setup' in Claude Code first (or install.ps1)."
  exit 1
}
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $DataDir "ms-playwright"
$env:no_proxy = "*"
if (-not $env:CLAUDE_SEO_PYTHON) { $env:CLAUDE_SEO_PYTHON = $VenvPy }

# Keep both computers on the latest version: quiet fast-forward pull at most once a day.
$Stamp = Join-Path $SkillDir ".last-pull"
if ((Test-Path (Join-Path $SkillDir ".git")) -and -not $env:SEO_REPORT_NO_PULL) {
  $stale = (-not (Test-Path $Stamp)) -or ((Get-Date) - (Get-Item $Stamp).LastWriteTime).TotalHours -gt 24
  if ($stale -and (Get-Command git -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath "git" -ArgumentList @("-C", "`"$SkillDir`"", "pull", "--ff-only", "-q") -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
    New-Item -ItemType File -Path $Stamp -Force | Out-Null
  }
}

if ($args.Count -lt 1) { Write-Error "Usage: run.ps1 <script.py> [args...]"; exit 1 }
$Script = Join-Path (Join-Path $SkillDir "scripts") $args[0]
$Rest = @()
if ($args.Count -gt 1) { $Rest = $args[1..($args.Count - 1)] }
& $VenvPy $Script @Rest
exit $LASTEXITCODE
