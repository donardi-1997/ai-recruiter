$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 'Python 3.12+ es requerido')"
python -m venv .agent-venv
& .\.agent-venv\Scripts\python.exe -m pip install --upgrade pip
& .\.agent-venv\Scripts\pip.exe install -r .\tools\indeed_resume_agent\requirements.txt
& .\.agent-venv\Scripts\python.exe -m tools.indeed_resume_agent.setup_token

Write-Host "ASIATI Resume Agent instalado para este usuario de Windows."
Write-Host "Ejecute .\tools\indeed_resume_agent\run.ps1"
