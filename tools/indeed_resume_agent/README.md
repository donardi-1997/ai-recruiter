# ASIATI Resume Agent

Cliente Windows local para descargar de forma controlada los CV enlazados desde correos de Indeed y entregarlos al AI Recruiter. Conserva el formato original compatible (**PDF o DOCX**) en lugar de forzar conversiones locales. El agente usa **Browser Use 0.13.10 + CDP** sobre una única sesión visible de **Google Chrome**, un perfil de navegador exclusivo y una credencial de máquina almacenada en **Windows Credential Manager**. La navegación crítica es determinística y no usa un LLM.

## Requisitos

- Windows 10/11.
- Google Chrome instalado.
- Python 3.12+ solo para instalación/desarrollo desde el repositorio.
- Acceso HTTPS a `https://dzcwl3yhv133t.cloudfront.net`.
- Token de máquina emitido por el administrador. No lo guarde en archivos, capturas, tickets o chat.

El agente no solicita ni almacena la contraseña de Indeed. Login, MFA y CAPTCHA se resuelven manualmente en la ventana visible de Chrome. Chrome es el navegador predeterminado; para pruebas de compatibilidad puede seleccionarse Edge con `ASIATI_RESUME_AGENT_BROWSER=edge`.

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

## Prueba final: sincronizar todo

El botón **Sincronizar todo** ejecuta la revisión integral del tenant asociado a la credencial del agente:

1. Recorre el histórico de Gmail/Indeed por páginas hasta agotar el bootstrap y ejecuta una pasada incremental final.
2. Revisa todas las vacantes locales del tenant y todos los candidatos vinculados a Indeed.
3. Conserva los CV ya completados y no duplica ingestas del proveedor que siguen activas.
4. Cuando una descarga automática de Indeed falló o no existe, crea una tarea local de búsqueda determinística por **candidato + vacante** en Gestionar candidatos.
5. Procesa la cola de CV de uno en uno con la sesión visible de Chrome.
6. Si Indeed solicita login, MFA o CAPTCHA, el agente se detiene en **Needs attention**; la intervención sigue siendo manual.
7. La prueba solo muestra **Prueba final completada** cuando la cola local queda en cero y no existen tareas `FAILED`, `NEEDS_HUMAN` ni CVs aún pendientes en el pipeline automático de Indeed.

La operación es idempotente: volver a ejecutar **Sincronizar todo** no debe duplicar candidatos, asignaciones ni tareas ya cubiertas.

## Primer uso

1. Verifique que Google Chrome esté instalado.
2. Inicie ASIATI Resume Agent.
3. Pulse **Open Indeed (Google Chrome)**. Este botón abre Chrome normal, no Playwright.
4. Inicie sesión manualmente en Indeed dentro de esa ventana si hace falta. Si usa Google, hágalo únicamente aquí.
5. Complete MFA/CAPTCHA manualmente cuando Indeed lo solicite.
6. Mantenga abierta esa ventana de Chrome: es la misma sesión administrada por Browser Use que utilizará **Resume** y **Diagnostic mode**. No la cierre manualmente mientras el agente esté abierto.
7. Mantenga el perfil dedicado en `%LOCALAPPDATA%\ASIATI\ResumeAgent\browser-profile-chrome`.
8. Active y pruebe **una sola aplicación real** antes de procesar un lote.

El agente trabaja con una sola tarea a la vez. Si se cierra el PC o el proceso, el backend recupera una tarea cuando vence su lease; no borre tareas completadas.

## Controles

- **Pause**: evita reclamar la siguiente tarea; no interrumpe una descarga determinística ya iniciada.
- **Resume**: reanuda la cola y, si había una tarea en `NEEDS_HUMAN`, solicita al backend volverla a `WAITING_DOWNLOAD`.
- **Open Indeed (Google Chrome)**: abre Indeed en la misma sesión persistente administrada por Browser Use que después ejecutará el flujo determinístico.
- **Diagnostic mode**: reutiliza esa sesión Browser Use/CDP para capturar metadatos sanitizados de navegación y red. Login, Google OAuth, MFA y CAPTCHA siguen siendo acciones manuales.
- **Guardar diagnóstico**: guarda el JSON y la captura local en `%LOCALAPPDATA%\\ASIATI\\ResumeAgent\\diagnostics`.

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

Se usa PyInstaller `--onedir` y se empaquetan Browser Use, `cdp-use` y sus dependencias. El runtime abre el **Google Chrome instalado** mediante el mismo patrón Browser Use usado por el bot de Computrabajo; no usa Browser Use Agent ni consume tokens de IA. **No** es necesario instalar un Chromium separado en el PC de producción.

En GitHub, los pull requests ejecutan un único workflow de validación (`CI — Tests & Build`). El artefacto Windows se genera una sola vez después de cambios validados que llegan a `main`, o manualmente mediante `workflow_dispatch`.

## Eliminar la credencial local

Desde el repositorio y el entorno instalado:

```powershell
.\.agent-venv\Scripts\python.exe -c "from tools.indeed_resume_agent.credential_store import delete_agent_token; delete_agent_token(); print('Credencial eliminada')"
```

Eliminar la credencial no borra el perfil de Chrome ni los estados durables del backend.

## Corte a producción

1. Verificar `/api/agents/indeed-resume/stats` con el token del PC autorizado.
2. Habilitar Gmail con filtro `from:indeedemail.com`.
3. Sincronizar una sola aplicación real.
4. Confirmar `WAITING_DOWNLOAD -> CLAIMED -> COMPLETED` y el handoff a Candidate Ingestion Core.
5. Procesar un lote controlado de 5–10 aplicaciones.
6. Solo después liberar el backlog mayor.

Para pasar de un PC de pruebas al PC de Katherine se genera un token nuevo y se reemplaza su SHA-256 en AWS. El token anterior queda invalidado.
