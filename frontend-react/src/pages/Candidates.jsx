// eslint-disable-next-line no-unused-vars
import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import api from "../api/client";
import CandidateImportModal from "../features/candidate-import/CandidateImportModal.jsx";

function Candidates() {
  const [candidates, setCandidates] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState({});
  const [loading, setLoading] = useState(false);
  const [selectedEvaluation, setSelectedEvaluation] = useState(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchParams] = useSearchParams();

  const requestedJobId = searchParams.get("job_id") || "";

  const loadData = useCallback(async () => {
    try {
      const [candidatesResponse, jobsResponse] = await Promise.all([
        api.get("/candidates"),
        api.get("/jobs"),
      ]);

      const candidatesData = candidatesResponse.data;
      const jobsData = jobsResponse.data;

      setCandidates(
        Array.isArray(candidatesData)
          ? candidatesData
          : candidatesData.candidates || [],
      );
      setJobs(Array.isArray(jobsData) ? jobsData : jobsData.jobs || []);
    } catch (error) {
      console.error("ERROR LOADING DATA:", error);
    }
  }, []);

  useEffect(() => {
    // The initial request synchronizes this view with the API.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData();
  }, [loadData]);

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
    void loadData();
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

      console.log("EVALUATION RESPONSE:", response.data);
      setSelectedEvaluation({
        candidateId,
        evaluation: response.data,
      });
    } catch (error) {
      console.error("EVALUATION ERROR:", error.response?.data || error);
      alert("Error evaluando candidato");
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
      await loadData();
    } catch (error) {
      alert(
        error.response?.data?.detail ||
          "No fue posible asignar el candidato.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function downloadCV(candidate) {
    try {
      const response = await api.get(
        `/candidates/${candidate.candidate_id}/download`,
      );
      const downloadUrl = response.data.download_url;
      if (!downloadUrl) throw new Error("No se recibió URL de descarga");
      window.location.assign(downloadUrl);
    } catch (error) {
      console.error("DOWNLOAD ERROR:", error.response?.data || error);
      alert("No fue posible descargar el CV");
    }
  }

  async function deleteCandidate(candidate) {
    const confirmed = window.confirm(
      `¿Seguro que deseas eliminar al candidato "${candidate.name}"?\n\nTambién se eliminarán sus evaluaciones y el CV almacenado.`,
    );
    if (!confirmed) return;

    try {
      await api.delete(`/candidates/${candidate.candidate_id}`);
      setCandidates((current) =>
        current.filter(
          (item) => item.candidate_id !== candidate.candidate_id,
        ),
      );

      if (selectedEvaluation?.candidateId === candidate.candidate_id) {
        setSelectedEvaluation(null);
      }

      setSelectedJob((current) => {
        const updated = { ...current };
        delete updated[candidate.candidate_id];
        return updated;
      });
    } catch (error) {
      console.error("DELETE CANDIDATE ERROR:", error.response?.data || error);
      alert(
        error.response?.data?.detail ||
          "No fue posible eliminar el candidato",
      );
    }
  }

  async function deleteAllCandidates() {
    const confirmed = window.confirm(
      `¿Seguro que deseas eliminar los ${candidates.length} candidatos? Esta acción no se puede deshacer. También se eliminarán sus evaluaciones y CVs.`,
    );
    if (!confirmed) return;

    try {
      setLoading(true);
      const response = await api.delete("/candidates");
      const result = response.data;
      await loadData();
      setSelectedJob({});
      setSelectedEvaluation(null);
      if (result.failed) {
        window.alert(
          `${result.deleted} candidatos eliminados. ${result.failed} no pudieron eliminarse.`,
        );
      }
    } catch (error) {
      console.error("DELETE ALL CANDIDATES ERROR:", error.response?.data || error);
      window.alert(
        error.response?.data?.detail ||
          "No fue posible eliminar los candidatos.",
      );
    } finally {
      setLoading(false);
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

      <div className="section-heading candidate-section-heading">
        <div>
          <h2>Candidatos registrados</h2>
          <p>
            {candidates.length}{" "}
            {candidates.length === 1
              ? "perfil disponible"
              : "perfiles disponibles"}
          </p>
        </div>
        {candidates.length > 0 && (
          <button
            className="btn btn-danger"
            onClick={deleteAllCandidates}
            disabled={loading}
          >
            🗑 Eliminar todos
          </button>
        )}
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
              </div>

              <div
                className="candidate-actions"
                style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}
              >
                <button
                  className="btn btn-secondary"
                  onClick={() => downloadCV(candidate)}
                >
                  📄 Descargar CV
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => deleteCandidate(candidate)}
                >
                  🗑 Eliminar
                </button>
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
                disabled={loading}
              >
                {loading ? "Asignando..." : "Asignar a vacante"}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => evaluate(candidate.candidate_id)}
                disabled={loading}
              >
                Evaluar candidato
              </button>
            </div>
          </div>
        ))
      )}

      {showCreateModal && (
        <CandidateImportModal
          open
          jobs={jobs}
          initialJobId={initialImportJobId}
          onClose={closeCreateCandidateModal}
        />
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
