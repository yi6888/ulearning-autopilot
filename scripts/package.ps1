# Build dist/ulearning-autopilot-vX.zip  (excludes login state and logs)
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\package.ps1
param([string]$Version = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Version) {
    $m = Select-String -Path "pyproject.toml" -Pattern '^version = "(.+)"'
    $Version = $m.Matches[0].Groups[1].Value
}

$dist  = Join-Path $root "dist"
$stage = Join-Path $env:TEMP ("ulearning-autopilot-" + $Version)
$zip   = Join-Path $dist ("ulearning-autopilot-v" + $Version + ".zip")

Write-Host "[*] version $Version"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
if (Test-Path $zip)   { Remove-Item $zip -Force }
New-Item -ItemType Directory -Force $dist  | Out-Null
New-Item -ItemType Directory -Force $stage | Out-Null

$include = @(
    "ulearning", "tools", "tests", "docs", "scripts", ".github",
    "README.md", "README.en.md", "SKILL.md", "LICENSE",
    "requirements.txt", "pyproject.toml", ".gitignore"
)
foreach ($item in $include) {
    $src = Join-Path $root $item
    if (-not (Test-Path $src)) { Write-Host "    skip $item"; continue }
    Copy-Item $src (Join-Path $stage $item) -Recurse -Force
}

Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem $stage -Recurse -File | Where-Object { $_.Extension -in ".pyc", ".jsonl" } | Remove-Item -Force

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item $stage -Recurse -Force

$size = [math]::Round((Get-Item $zip).Length / 1KB, 1)
Write-Host "[+] $zip  ($size KB)"

Add-Type -AssemblyName System.IO.Compression.FileSystem
$entries = [IO.Compression.ZipFile]::OpenRead($zip).Entries
$bad = $entries | Where-Object { $_.FullName -match "^(profile|logs|shots)/" }
if ($bad) {
    Write-Host "[!] package contains sensitive dirs:" ($bad.FullName -join ", ")
    exit 1
}
Write-Host "[+] self-check passed: no profile/logs/shots, $($entries.Count) entries"
