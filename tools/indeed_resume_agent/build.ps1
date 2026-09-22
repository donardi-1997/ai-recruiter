$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".agent-venv\Scripts\python.exe"
$PyInstaller = Join-Path $RepoRoot ".agent-venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $Python) -or -not (Test-Path $PyInstaller)) {
    throw "No se encontro el entorno del agente. Ejecute primero tools\indeed_resume_agent\install.ps1"
}

& $PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onedir `
  --paths $RepoRoot `
  --collect-all playwright `
  --collect-submodules browser_use.browser `
  --collect-data browser_use `
  --collect-all cdp_use `
  --collect-all browser_harness `
  --collect-submodules keyring.backends `
  --name "ASIATI Resume Agent" `
  .\tools\indeed_resume_agent\entrypoint.py

Write-Host "Build creado en dist\ASIATI Resume Agent\"
