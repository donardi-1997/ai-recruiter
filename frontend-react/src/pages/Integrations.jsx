// eslint-disable-next-line no-unused-vars
import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import api from "../api/client";
import "./Integrations.css";

function Integrations() {
  const [searchParams] = useSearchParams();
  const oauthOutcome = searchParams.get("gmail");
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [activeSmokeNeedsHuman, setActiveSmokeNeedsHuman] = useState(false);
  const [message, setMessage] = useState(() =>
    oauthOutcome === "connected" ? "Gmail corporativo conectado correctamente." : "",
  );
  const [error, setError] = useState(() => {
    if (oauthOutcome === "denied") return "La autorización de Gmail fue cancelada.";
    if (oauthOutcome === "error") return "No fue posible completar la autorización de Gmail.";
    return "";
  });

  async function loadStatus() {
    try {
      setError("");
      const { data } = await api.get("/integrations/gmail/status");
      setStatus(data);
    } catch (requestError) {
      const detail = requestError?.response?.data?.detail;
      setError(detail || "No fue posible consultar el estado de Gmail.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;

    api.get("/integrations/gmail/status")
      .then(async ({ data }) => {
        if (!active) return;
        setStatus(data);

        if (data?.connected) {
          try {
            const { data: smokeTask } = await api.get(
              "/integrations/gmail/active-archived-test",
            );
            if (active) {
              setActiveSmokeNeedsHuman(
                ["NEEDS_HUMAN", "RETRY", "FAILED"].includes(smokeTask?.status),
              );
            }
          } catch {
            if (active) setActiveSmokeNeedsHuman(false);
          }
        } else {
          setActiveSmokeNeedsHuman(false);
        }
      })
      .catch((requestError) => {
        if (!active) return;
        const detail = requestError?.response?.data?.detail;
        setError(detail || "No fue posible consultar el estado de Gmail.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!oauthOutcome || typeof window === "undefined") return;
    const url = new URL(window.location.href);
    url.searchParams.delete("gmail");
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }, [oauthOutcome]);

  async function connectGmail() {
    setBusy("connect");
    setError("");
    setMessage("");
    try {
      const { data } = await api.get("/integrations/gmail/oauth/start");
      if (!data?.authorization_url) {
        throw new Error("Missing authorization URL");
      }
      window.open(data.authorization_url, "_self");
    } catch (requestError) {
      const detail = requestError?.response?.data?.detail;
      setError(detail || "No fue posible iniciar la conexión con Google.");
      setBusy("");
    }
  }

  async function syncGmail() {
    setBusy("sync");
    setError("");
    setMessage("");
    try {
      const { data } = await api.post("/integrations/gmail/sync");
      const created = Number(data?.created || 0);
      const existing = Number(data?.existing || 0);
      const discovered = Number(data?.discovered || 0);
      setMessage(
        `${created} candidatos nuevos · ${existing} existentes · ${discovered} mensajes revisados`,
      );
    } catch (requestError) {
      const detail = requestError?.response?.data?.detail;
      setError(detail || "No fue posible sincronizar Gmail.");
    } finally {
      setBusy("");
    }
  }

  async function reactivateOneArchived() {
    setBusy("reactivate");
    setError("");
    setMessage("");
    try {
      const { data } = await api.post("/integrations/gmail/reactivate-one-archived");
      if (data?.task_id) {
        const candidate = data?.candidate_name || "Candidato";
        const role = data?.job_title ? ` · ${data.job_title}` : "";
        const errorCode = data?.last_error_code ? ` · ${data.last_error_code}` : "";
        const retryable = ["NEEDS_HUMAN", "RETRY", "FAILED"].includes(data?.status);
        setActiveSmokeNeedsHuman(retryable);
        setMessage(
          data?.reactivated
            ? `Prueba preparada: ${candidate}${role}. Abre el Resume Agent para procesar solo esta tarea.`
            : retryable
              ? `La tarea activa puede reintentarse: ${candidate}${role}${errorCode}.`
              : `Ya existe una tarea activa: ${candidate}${role}${errorCode}.`,
        );
      } else {
        setActiveSmokeNeedsHuman(false);
        setMessage("No hay tareas históricas archivadas disponibles para prueba.");
      }
    } catch (requestError) {
      const detail = requestError?.response?.data?.detail;
      setError(detail || "No fue posible preparar una tarea de prueba.");
    } finally {
      setBusy("");
    }
  }

  async function retryActiveArchivedTest() {
    setBusy("retry-test");
    setError("");
    setMessage("");
    try {
      const { data } = await api.post("/integrations/gmail/retry-active-archived-test");
      if (data?.retried) {
        setActiveSmokeNeedsHuman(false);
        const candidate = data?.candidate_name || "Candidato";
        const role = data?.job_title ? ` · ${data.job_title}` : "";
        setMessage(
          `Prueba reactivada: ${candidate}${role}. El Resume Agent intentará esta misma tarea otra vez.`,
        );
      } else {
        setActiveSmokeNeedsHuman(false);
        setMessage("No hay una tarea de prueba fallida o pendiente de reintento.");
      }
    } catch (requestError) {
      const detail = requestError?.response?.data?.detail;
      setError(detail || "No fue posible reintentar la tarea de prueba.");
    } finally {
      setBusy("");
    }
  }

  async function disconnectGmail() {
    setBusy("disconnect");
    setError("");
    setMessage("");
    try {
      await api.delete("/integrations/gmail");
      setMessage("Cuenta Gmail desconectada.");
      await loadStatus();
    } catch (requestError) {
      const detail = requestError?.response?.data?.detail;
      setError(detail || "No fue posible desconectar Gmail.");
    } finally {
      setBusy("");
    }
  }

  const connected = Boolean(status?.connected);
  const oauthConfigured = Boolean(status?.oauth_configured);
  const manageable = status?.manageable !== false;

  return (
    <section className="integrations-page">
      <header className="integrations-hero">
        <div>
          <span className="integrations-eyebrow">Fuentes de candidatos</span>
          <h1>Integraciones</h1>
          <p>
            Conecta el buzón corporativo que recibe postulaciones para importar CVs al
            flujo de evaluación de ASIATI.
          </p>
        </div>
        <div className="integrations-hero-badge">1 cuenta corporativa</div>
      </header>

      {error && <div className="integration-alert is-error" role="alert">{error}</div>}
      {message && <div className="integration-alert is-success" role="status">{message}</div>}

      <article className="integration-card">
        <div className="integration-card-header">
          <div className="integration-provider-mark" aria-hidden="true">M</div>
          <div className="integration-provider-copy">
            <div className="integration-title-row">
              <h2>Gmail corporativo</h2>
              {!loading && (
                <span className={`integration-status ${connected ? "is-connected" : ""}`}>
                  <span aria-hidden="true" />
                  {connected ? "Conectado" : "Sin conexión"}
                </span>
              )}
            </div>
            <p>
              Lee únicamente los correos permitidos por el filtro de ingestión y procesa
              sus adjuntos PDF/DOCX como candidatos.
            </p>
          </div>
        </div>

        {loading ? (
          <div className="integration-loading">Consultando configuración…</div>
        ) : (
          <div className="integration-body">
            {connected ? (
              <div className="integration-account">
                <span className="integration-account-label">Cuenta conectada</span>
                <strong>{status.connected_email || "Cuenta corporativa conectada"}</strong>
                <span>
                  Proveedor de ingestión: {status.provider || "INDEED"}
                </span>
              </div>
            ) : oauthConfigured ? (
              <div className="integration-account">
                <span className="integration-account-label">Estado</span>
                <strong>Gmail listo para conectar</strong>
                <span>Autoriza una sola cuenta corporativa de Google Workspace.</span>
              </div>
            ) : (
              <div className="integration-account is-warning">
                <span className="integration-account-label">Configuración requerida</span>
                <strong>Credenciales de Google pendientes</strong>
                <span>
                  El callback HTTPS ya está preparado. Falta cargar el client ID y el client
                  secret del cliente OAuth Web de Google Cloud.
                </span>
              </div>
            )}

            {status?.redirect_uri && (
              <div className="integration-callback">
                <span>Callback OAuth</span>
                <code>{status.redirect_uri}</code>
              </div>
            )}

            {!manageable && (
              <div className="integration-alert is-warning">
                Esta conexión corporativa está administrada por otro usuario autorizado.
                Puedes consultar su estado, pero no modificarla ni ejecutar sincronizaciones manuales.
              </div>
            )}

            {!status?.safe_filter && (
              <div className="integration-alert is-warning">
                La sincronización permanecerá bloqueada hasta configurar un remitente
                permitido o una consulta Gmail con <code>from:</code>.
              </div>
            )}

            {!status?.enabled && connected && (
              <div className="integration-alert is-warning">
                La cuenta está conectada, pero la ingestión automática está deshabilitada.
              </div>
            )}

            {manageable && (
              <div className="integration-actions">
              {!connected ? (
                <button
                  type="button"
                  className="integration-primary"
                  onClick={connectGmail}
                  disabled={!oauthConfigured || Boolean(busy)}
                >
                  {busy === "connect" ? "Abriendo Google…" : "Conectar Gmail"}
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    className="integration-primary"
                    onClick={syncGmail}
                    disabled={Boolean(busy) || !status.enabled || !status.safe_filter}
                  >
                    {busy === "sync" ? "Sincronizando…" : "Sincronizar ahora"}
                  </button>
                  <button
                    type="button"
                    className="integration-secondary"
                    onClick={reactivateOneArchived}
                    disabled={Boolean(busy)}
                  >
                    {busy === "reactivate" ? "Preparando prueba…" : "Probar 1 candidato archivado"}
                  </button>
                  {activeSmokeNeedsHuman && (
                    <button
                      type="button"
                      className="integration-secondary"
                      onClick={retryActiveArchivedTest}
                      disabled={Boolean(busy)}
                    >
                      {busy === "retry-test" ? "Reintentando…" : "Reintentar prueba"}
                    </button>
                  )}
                  <button
                    type="button"
                    className="integration-secondary"
                    onClick={disconnectGmail}
                    disabled={Boolean(busy)}
                  >
                    {busy === "disconnect" ? "Desconectando…" : "Desconectar"}
                  </button>
                </>
              )}
              </div>
            )}
          </div>
        )}
      </article>
    </section>
  );
}

export default Integrations;
