$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

$Python = Join-Path $RepoRoot ".agent-venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "No se encontro .agent-venv. Ejecute primero tools\indeed_resume_agent\install.ps1"
}

& $Python -m tools.indeed_resume_agent.main
