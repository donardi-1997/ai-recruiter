// eslint-disable-next-line no-unused-vars
import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import api from "../api/client";
import { useSession } from "../context/SessionContext";
import CandidateImportModal from "../features/candidate-import/CandidateImportModal.jsx";

const PAGE_SIZE = 20;

function Candidates() {
  const { hasPermission } = useSession();
  const canRestrictCandidates = hasPermission("candidates.restrict");
  const [candidates, setCandidates] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState({});
  const [loading, setLoading] = useState(false);
  const [selectedEvaluation, setSelectedEvaluation] = useState(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [searchParams] = useSearchParams();
  const [restrictionTarget, setRestrictionTarget] = useState(null);
  const [restrictionMode, setRestrictionMode] = useState("ban");
  const [restrictionReason, setRestrictionReason] = useState("");
  const [restrictionSaving, setRestrictionSaving] = useState(false);

  const requestedJobId = searchParams.get("job_id") || "";

  const loadData = useCallback(async (targetPage = page) => {
    setLoadError("");
    try {
      const [candidatesResponse, jobsResponse] = await Promise.all([
        api.get(`/candidates?page=${targetPage}&page_size=${PAGE_SIZE}`),
        api.get("/jobs"),
      ]);

      const candidatesData = candidatesResponse.data || {};
      const jobsData = jobsResponse.data;
      const items = Array.isArray(candidatesData.items)
        ? candidatesData.items
        : [];
      const responseTotal = Number(candidatesData.total || 0);
      const responsePages = Number(candidatesData.pages || 0);

      setCandidates(items);
      setTotal(responseTotal);
      setPages(responsePages);
      setJobs(Array.isArray(jobsData) ? jobsData : jobsData.jobs || []);
    } catch {
      setLoadError("No fue posible cargar los candidatos y las vacantes.");
    }
  }, [page]);

  useEffect(() => {
    // The initial request synchronizes this view with the API.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData(page);
  }, [loadData, page]);

  useEffect(() => {
    if (!requestedJobId) return;
    // A job deep link intentionally opens the durable import surface.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setShowCreateModal(true);
  }, [requestedJobId]);

  function openCreateCandidateModal() {
    setShowCreateModal(true);
  }

  function closeCreateCandidateModal() {
    setShowCreateModal(false);
    if (page !== 1) {
      setPage(1);
      return;
    }
    void loadData(1);
  }

  async function evaluate(candidateId) {
    const jobId = selectedJob[candidateId];

    if (!jobId) {
      alert("Seleccione una vacante");
      return;
    }

    try {
      setLoading(true);
      const response = await api.post(
        `/candidates/${candidateId}/evaluate-job`,
        { job_id: jobId },
      );

      setSelectedEvaluation({
        candidateId,
        evaluation: response.data,
      });
    } catch (error) {
      alert(
        error.response?.data?.detail ||
          "No fue posible evaluar el candidato.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function assignCandidate(candidateId) {
    const jobId = selectedJob[candidateId];
    if (!jobId) {
      alert("Seleccione una vacante");
      return;
    }

    try {
      setLoading(true);
      await api.post(`/jobs/${jobId}/candidates`, {
        candidate_ids: [candidateId],
      });
      alert("Candidato asignado a la vacante.");
      await loadData(page);
    } catch (error) {
      alert(
        error.response?.data?.detail ||
          "No fue posible asignar el candidato.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function viewCV(candidate) {
    const viewer = window.open("about:blank", "_blank");
    if (!viewer) {
      alert("El navegador bloqueó la nueva pestaña. Permite ventanas emergentes para ver el CV.");
      return;
    }
    viewer.opener = null;

    try {
      const response = await api.get(
        `/candidates/${candidate.candidate_id}/download`,
      );
      const viewUrl = response.data.download_url;
      if (!viewUrl) throw new Error("No se recibió URL del CV");
      viewer.location.replace(viewUrl);
    } catch (error) {
      viewer.close();
      alert(
        error.response?.data?.detail ||
          "No fue posible abrir el CV",
      );
    }
  }

  function openRestriction(candidate, mode) {
    setRestrictionTarget(candidate);
    setRestrictionMode(mode);
    setRestrictionReason("");
  }

  function closeRestriction() {
    if (restrictionSaving) return;
    setRestrictionTarget(null);
    setRestrictionReason("");
  }

  async function submitRestriction(event) {
    event.preventDefault();
    if (!restrictionTarget || restrictionReason.trim().length < 3) return;

    setRestrictionSaving(true);
    try {
      await api.post(
        `/candidates/${restrictionTarget.candidate_id}/${restrictionMode === "ban" ? "ban" : "unban"}`,
        { reason: restrictionReason.trim() },
      );
      setRestrictionTarget(null);
      setRestrictionReason("");
      await loadData(page);
    } catch (error) {
      window.alert(
        error.response?.data?.detail ||
          "No fue posible actualizar el veto del candidato.",
      );
    } finally {
      setRestrictionSaving(false);
    }
  }

  function getDisplayFilename(candidate) {
    if (candidate.filename) return candidate.filename;
    if (candidate.name) {
      const cleanName = candidate.name
        .trim()
        .replace(/\s+/g, "_")
        .replace(/[^\wáéíóúÁÉÍÓÚñÑ-]/g, "");
      return `${cleanName}_CV.pdf`;
    }
    return "CV.pdf";
  }

  function closeEvaluationModal() {
    setSelectedEvaluation(null);
  }

  function getRecommendationLabel(recommendation) {
    if (recommendation === "STRONG_MATCH") return "Excelente coincidencia";
    if (recommendation === "GOOD_MATCH") return "Buena coincidencia";
    if (recommendation === "PARTIAL_MATCH") return "Coincidencia parcial";
    if (recommendation === "LOW_MATCH") return "Baja coincidencia";
    if (recommendation === "EVALUATION_FAILED") return "Evaluación fallida";
    if (recommendation === "PENDING") return "Pendiente";
    return "Sin clasificación";
  }

  function badgeStyle(recommendation) {
    if (recommendation === "STRONG_MATCH") {
      return { background: "#dcfce7", color: "#166534" };
    }
    if (
      recommendation === "GOOD_MATCH" ||
      recommendation === "PARTIAL_MATCH"
    ) {
      return { background: "#fef3c7", color: "#92400e" };
    }
    if (recommendation === "EVALUATION_FAILED") {
      return {
        background: "#fef2f2",
        color: "#991b1b",
        border: "1px solid #fecaca",
      };
    }
    return { background: "#fee2e2", color: "#991b1b" };
  }

  const selectedEvaluationFailed =
    selectedEvaluation?.evaluation?.status === "FAILED" ||
    selectedEvaluation?.evaluation?.recommendation === "EVALUATION_FAILED";

  const initialImportJobId =
    requestedJobId || (jobs.length === 1 ? jobs[0].job_id : "");

  const visibleStart = total > 0 ? (page - 1) * PAGE_SIZE + 1 : 0;
  const visibleEnd = total > 0 ? Math.min(page * PAGE_SIZE, total) : 0;

  return (
    <div className="page candidate-page">
      <div
        className="page-header"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "20px",
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1>Candidatos</h1>
          <p>Gestión de CVs con Inteligencia Artificial</p>
        </div>

        <button
          type="button"
          className="btn btn-primary candidate-add-button"
          onClick={openCreateCandidateModal}
        >
          Agregar candidato
          <span aria-hidden="true">＋</span>
        </button>
      </div>

      {loadError && (
        <div className="empty-state" role="alert">
          <strong>No se pudo cargar la información</strong>
          <p>{loadError}</p>
          <button type="button" className="btn btn-secondary" onClick={() => void loadData(page)}>
            Reintentar
          </button>
        </div>
      )}

      <div className="section-heading candidate-section-heading">
        <div>
          <h2>Candidatos registrados</h2>
          <p>
            {total}{" "}
            {total === 1
              ? "perfil disponible"
              : "perfiles disponibles"}
          </p>
        </div>
      </div>

      {candidates.length === 0 ? (
        <div className="card">
          <p className="muted">No hay candidatos registrados.</p>
        </div>
      ) : (
        candidates.map((candidate) => (
          <div className="card candidate-card" key={candidate.candidate_id}>
            <div
              className="candidate-header"
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: "20px",
                flexWrap: "wrap",
              }}
            >
              <div>
                <h2>{candidate.name}</h2>
                <p className="muted" style={{ marginTop: "6px", fontSize: "14px" }}>
                  Candidato registrado
                </p>
                {candidate.is_banned && (
                  <div className="candidate-ban-alert" role="alert">
                    <strong>⚠ Candidato vetado</strong>
                    <span>{candidate.banned_reason || "Este perfil fue vetado por un administrador."}</span>
                  </div>
                )}
              </div>

              <div
                className="candidate-actions"
                style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}
              >
                <button
                  className="btn btn-secondary"
                  onClick={() => viewCV(candidate)}
                >
                  📄 Ver CV
                </button>
                {canRestrictCandidates && (
                  <button
                    className={`btn ${candidate.is_banned ? "btn-secondary" : "btn-danger"}`}
                    onClick={() => openRestriction(candidate, candidate.is_banned ? "unban" : "ban")}
                  >
                    {candidate.is_banned ? "Quitar veto" : "Vetar"}
                  </button>
                )}
              </div>
            </div>

            <div
              className="candidate-file"
              style={{
                marginTop: "20px",
                padding: "14px 16px",
                background: "#f8fafc",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              <span
                className="candidate-file-label"
                style={{
                  fontSize: "13px",
                  color: "var(--text-muted)",
                  display: "block",
                  marginBottom: "4px",
                }}
              >
                Archivo
              </span>
              <strong>{getDisplayFilename(candidate)}</strong>
            </div>

            <div className="controls" style={{ marginTop: "20px" }}>
              <select
                className="select"
                value={selectedJob[candidate.candidate_id] || ""}
                onChange={(event) =>
                  setSelectedJob((current) => ({
                    ...current,
                    [candidate.candidate_id]: event.target.value,
                  }))
                }
              >
                <option value="">Seleccione vacante</option>
                {jobs.map((job) => (
                  <option key={job.job_id} value={job.job_id}>
                    {job.title}
                  </option>
                ))}
              </select>

              <button
                className="btn btn-primary"
                onClick={() => assignCandidate(candidate.candidate_id)}
                disabled={loading || candidate.is_banned}
                title={candidate.is_banned ? "Un candidato vetado no puede recibir nuevas asignaciones." : undefined}
              >
                {loading ? "Asignando..." : "Asignar a vacante"}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => evaluate(candidate.candidate_id)}
                disabled={loading || candidate.is_banned}
                title={candidate.is_banned ? "Quita el veto antes de evaluar nuevamente." : undefined}
              >
                Evaluar candidato
              </button>
            </div>
          </div>
        ))
      )}

      {total > 0 && (
        <div
          className="candidate-pagination"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
            flexWrap: "wrap",
            marginTop: "20px",
          }}
        >
          <span className="muted">Mostrando {visibleStart}–{visibleEnd}</span>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1}
            >
              Anterior
            </button>
            <strong>Página {page} de {Math.max(pages, 1)}</strong>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setPage((current) => Math.min(Math.max(pages, 1), current + 1))}
              disabled={page >= Math.max(pages, 1)}
            >
              Siguiente
            </button>
          </div>
        </div>
      )}

      {showCreateModal && (
        <CandidateImportModal
          open
          jobs={jobs}
          initialJobId={initialImportJobId}
          onClose={closeCreateCandidateModal}
        />
      )}

      {restrictionTarget && (
        <div className="modal-overlay" onMouseDown={closeRestriction}>
          <section
            className="modal candidate-restriction-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="candidate-restriction-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <span className="eyebrow">Control administrativo</span>
                <h2 id="candidate-restriction-title">
                  {restrictionMode === "ban" ? "Vetar candidato" : "Quitar veto"}
                </h2>
                <p className="muted">
                  {restrictionTarget.name}
                </p>
              </div>
              <button
                type="button"
                className="btn btn-close"
                onClick={closeRestriction}
                disabled={restrictionSaving}
              >
                ✕
              </button>
            </div>

            {restrictionMode === "ban" && (
              <div className="candidate-ban-warning">
                <strong>Este candidato no será eliminado.</strong>
                <span>
                  El veto conservará su CV, evaluaciones y postulaciones históricas,
                  pero lo excluirá de nuevas asignaciones y recomendaciones.
                </span>
              </div>
            )}

            <form onSubmit={submitRestriction}>
              <div className="form-group">
                <label htmlFor="candidate-restriction-reason">
                  {restrictionMode === "ban" ? "Motivo del veto" : "Motivo para quitar el veto"}
                </label>
                <textarea
                  id="candidate-restriction-reason"
                  rows="4"
                  value={restrictionReason}
                  onChange={(event) => setRestrictionReason(event.target.value)}
                  placeholder="Describe el motivo para dejar trazabilidad."
                  required
                />
              </div>
              <div className="form-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={closeRestriction}
                  disabled={restrictionSaving}
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  className={`btn ${restrictionMode === "ban" ? "btn-danger" : "btn-primary"}`}
                  disabled={restrictionSaving || restrictionReason.trim().length < 3}
                >
                  {restrictionSaving
                    ? "Guardando…"
                    : restrictionMode === "ban"
                      ? "Confirmar veto"
                      : "Quitar veto"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {selectedEvaluation && (
        <div className="modal-overlay" onClick={closeEvaluationModal}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h2>Resultado de evaluación IA</h2>
                <p className="muted" style={{ marginTop: "6px" }}>
                  Evaluación del candidato
                </p>
              </div>
              <button className="btn btn-close" onClick={closeEvaluationModal}>
                ✕
              </button>
            </div>

            {selectedEvaluationFailed ? (
              <div style={{ textAlign: "center", padding: "20px 0" }}>
                <div
                  className="badge"
                  style={{
                    display: "inline-block",
                    padding: "10px 18px",
                    ...badgeStyle("EVALUATION_FAILED"),
                  }}
                >
                  Evaluación fallida
                </div>
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: "20px 0" }}>
                <div className="score">
                  {selectedEvaluation.evaluation.match_score}%
                </div>
                <div
                  className="score-bar"
                  style={{ maxWidth: "400px", margin: "0 auto" }}
                >
                  <div
                    className="score-fill"
                    style={{
                      width: `${selectedEvaluation.evaluation.match_score}%`,
                    }}
                  />
                </div>
                <div
                  className="badge"
                  style={{
                    marginTop: "18px",
                    ...badgeStyle(selectedEvaluation.evaluation.recommendation),
                  }}
                >
                  {getRecommendationLabel(
                    selectedEvaluation.evaluation.recommendation,
                  )}
                </div>
              </div>
            )}

            <div className="result">
              <h3>Resumen</h3>
              <p style={{ marginTop: "10px", lineHeight: "1.6" }}>
                {selectedEvaluation.evaluation.summary}
              </p>
            </div>

            <div className="columns">
              <div>
                <h3 className="section-title">✅ Fortalezas</h3>
                {selectedEvaluation.evaluation.strengths?.length ? (
                  <ul className="list">
                    {selectedEvaluation.evaluation.strengths.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Sin datos</p>
                )}
              </div>

              <div>
                <h3 className="section-title">❌ Gaps</h3>
                {selectedEvaluation.evaluation.gaps?.length ? (
                  <ul className="list">
                    {selectedEvaluation.evaluation.gaps.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Sin datos</p>
                )}
              </div>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                marginTop: "25px",
                gap: "10px",
              }}
            >
              <button className="btn btn-close" onClick={closeEvaluationModal}>
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Candidates;
