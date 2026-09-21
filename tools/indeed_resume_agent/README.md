# ASIATI Resume Agent

Cliente Windows local para descargar de forma controlada los CV enlazados desde correos de Indeed y entregarlos al AI Recruiter. El agente usa una sesión visible de **Microsoft Edge**, un perfil de navegador exclusivo y una credencial de máquina almacenada en **Windows Credential Manager**.

## Requisitos

- Windows 10/11.
- Microsoft Edge instalado.
- Python 3.12+ solo para instalación/desarrollo desde el repositorio.
- Acceso HTTPS a `https://dzcwl3yhv133t.cloudfront.net`.
- Token de máquina emitido por el administrador. No lo guarde en archivos, capturas, tickets o chat.

El agente no solicita ni almacena la contraseña de Indeed. Login, MFA y CAPTCHA se resuelven manualmente en la ventana visible de Edge.

## Instalación para pruebas desde el repositorio

Abra PowerShell como el mismo usuario de Windows que ejecutará el agente:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\tools\indeed_resume_agent\install.ps1
```

El instalador crea `.agent-venv`, instala únicamente `tools\indeed_resume_agent\requirements.txt` y pide el token mediante un prompt oculto. El token queda en Windows Credential Manager bajo:

```text
Service:  ASIATI Resume Agent
Username: agent-token
```

Para iniciar:

```powershell
.\tools\indeed_resume_agent\run.ps1
```

## Primer uso

1. Verifique que Microsoft Edge esté instalado.
2. Inicie ASIATI Resume Agent.
3. Pulse **Open Indeed**.
4. Inicie sesión manualmente en Indeed dentro de esa ventana si hace falta.
5. Complete MFA/CAPTCHA manualmente cuando Indeed lo solicite.
6. Mantenga el perfil dedicado en `%LOCALAPPDATA%\ASIATI\ResumeAgent\browser-profile`.
7. Active y pruebe **una sola aplicación real** antes de procesar un lote.

El agente trabaja con una sola tarea a la vez. Si se cierra el PC o el proceso, el backend recupera una tarea cuando vence su lease; no borre tareas completadas.

## Controles

- **Pause**: evita reclamar la siguiente tarea; no interrumpe una descarga determinística ya iniciada.
- **Resume**: reanuda la cola y, si había una tarea en `NEEDS_HUMAN`, solicita al backend volverla a `WAITING_DOWNLOAD`.
- **Open Indeed**: abre Indeed usando exclusivamente el perfil persistente del agente.

La interfaz nunca muestra tokens de máquina, lease tokens, URL temporal del CV, cookies ni errores backend sin sanitizar.

## Build Windows

Después de ejecutar `install.ps1`:

```powershell
.\tools\indeed_resume_agent\build.ps1
```

El resultado queda en:

```text
dist\ASIATI Resume Agent\
```

Se usa PyInstaller `--onedir`, se incluye Playwright y se reutiliza el canal `msedge` instalado. **No** es necesario ejecutar `playwright install chromium`.

## Eliminar la credencial local

Desde el repositorio y el entorno instalado:

```powershell
.\.agent-venv\Scripts\python.exe -c "from tools.indeed_resume_agent.credential_store import delete_agent_token; delete_agent_token(); print('Credencial eliminada')"
```

Eliminar la credencial no borra el perfil de Edge ni los estados durables del backend.

## Corte a producción

1. Verificar `/api/agents/indeed-resume/stats` con el token del PC autorizado.
2. Habilitar Gmail con filtro `from:indeedemail.com`.
3. Sincronizar una sola aplicación real.
4. Confirmar `WAITING_DOWNLOAD -> CLAIMED -> COMPLETED` y el handoff a Candidate Ingestion Core.
5. Procesar un lote controlado de 5–10 aplicaciones.
6. Solo después liberar el backlog mayor.

Para pasar de un PC de pruebas al PC de Katherine se genera un token nuevo y se reemplaza su SHA-256 en AWS. El token anterior queda invalidado.
