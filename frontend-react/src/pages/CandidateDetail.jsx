// eslint-disable-next-line no-unused-vars
import React, { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import api from "../api/client";

function recommendationLabel(recommendation) {
  const labels = {
    STRONG_MATCH: "Excelente coincidencia",
    GOOD_MATCH: "Buena coincidencia",
    PARTIAL_MATCH: "Coincidencia parcial",
    LOW_MATCH: "Baja coincidencia",
    EVALUATION_FAILED: "Evaluación fallida",
    PENDING: "Pendiente",
  };
  return labels[recommendation] || "Sin clasificación";
}

function CandidateDetail() {
  const { candidate_id } = useParams();
  const [searchParams] = useSearchParams();
  const jobId = searchParams.get("job_id");
  const [candidate, setCandidate] = useState(null);
  const [evaluations, setEvaluations] = useState([]);
  const [indeedDetails, setIndeedDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [openingResume, setOpeningResume] = useState(false);
  const [resumeError, setResumeError] = useState("");
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setLoadError("");
      setCandidate(null);
      setEvaluations([]);
      setIndeedDetails(null);

      try {
        const candidateResponse = await api.get(`/candidates/${candidate_id}`);
        if (cancelled) return;
        setCandidate(candidateResponse.data);
      } catch {
        if (!cancelled) {
          setLoadError("No fue posible cargar el perfil del candidato.");
          setLoading(false);
        }
        return;
      }

      try {
        const evaluationResponse = await api.get(jobId
          ? `/jobs/${jobId}/candidates/${candidate_id}`
          : `/candidates/${candidate_id}/evaluations`);
        if (!cancelled) {
          setEvaluations(jobId
            ? [evaluationResponse.data]
            : evaluationResponse.data.evaluations || []);
        }
      } catch (error) {
        // A candidate can legitimately exist before its first evaluation.
        if (!cancelled && error?.response?.status !== 404) {
          setLoadError("El perfil cargó, pero no fue posible consultar su evaluación.");
        }
      }

      if (jobId && !cancelled) {
        try {
          const indeedResponse = await api.get(
            `/jobs/${jobId}/candidates/${candidate_id}/integrations/indeed`
          );
          if (!cancelled) setIndeedDetails(indeedResponse.data);
        } catch {
          // Not every candidate comes from Indeed. Keep the core profile usable.
          if (!cancelled) setIndeedDetails(null);
        }
      }

      if (!cancelled) setLoading(false);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [candidate_id, jobId]);

  async function openResume() {
    setOpeningResume(true);
    setResumeError("");
    try {
      const response = await api.get(`/candidates/${candidate_id}/download`);
      const downloadUrl = response.data?.download_url;
      if (!downloadUrl) throw new Error("CV_DOWNLOAD_URL_MISSING");
      window.open(downloadUrl, "_blank", "noopener,noreferrer");
    } catch {
      setResumeError("No fue posible abrir el CV. Intenta nuevamente.");
    } finally {
      setOpeningResume(false);
    }
  }

  if (loading) return <div className="page"><div className="page-loading"><span /> Cargando perfil…</div></div>;
  if (!candidate) {
    return <div className="page"><div className="empty-state"><strong>No fue posible cargar el candidato</strong><p>{loadError || "Intenta nuevamente."}</p><Link to="/candidates" className="btn btn-primary">Volver a candidatos</Link></div></div>;
  }

  const evaluation = evaluations[0];
  const numericScore = Number(evaluation?.match_score);
  const evaluationCompleted = Boolean(
    evaluation
      && evaluation.status !== "FAILED"
      && evaluation.status !== "PENDING"
      && Number.isFinite(numericScore),
  );
  const sourceName = indeedDetails?.source_name || candidate?.metadata?.source_name || candidate?.metadata?.source;
  const resume = indeedDetails?.resume;
  const resumeName = resume?.name || candidate?.filename || candidate?.metadata?.resume_name || "Currículum registrado";
  const isIndeedTest = indeedDetails?.staged_test ?? candidate?.metadata?.indeed_staged_test;
  const canOpenResume = !resume || resume.available;

  return (
    <div className="page candidate-detail-page">
      <Link to="/candidates" className="back-link">← Volver a candidatos</Link>
      <header className="candidate-profile-header">
        <div className="candidate-avatar">{candidate?.name?.slice(0, 2).toUpperCase() || "CV"}</div>
        <div>
          <span className="eyebrow">Perfil de candidato</span>
          <h1>{candidate?.name || "Candidato"}</h1>
          <p>{resumeName}</p>
          {sourceName && <p><strong>Origen:</strong> {sourceName}</p>}
          {isIndeedTest && <p className="muted">Candidato de prueba de Indeed</p>}
          {resume && !resume.available && resume.status !== "FAILED" && resume.status !== "UNAVAILABLE" && (
            <p className="muted">Procesando CV…</p>
          )}
          {resume?.status === "FAILED" && (
            <p className="muted">No fue posible procesar el CV. Intenta nuevamente.</p>
          )}
          {resumeError && <p className="muted">{resumeError}</p>}
          {jobId && (
            <p>{evaluationCompleted ? "Evaluado para la vacante seleccionada" : "Pendiente de evaluación para la vacante seleccionada"}</p>
          )}
        </div>
        <div className="candidate-profile-actions">
          {canOpenResume && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={openResume}
              disabled={openingResume}
            >
              {openingResume ? "Abriendo…" : "Ver CV"}
            </button>
          )}
          <span className={`status-pill ${candidate.is_banned ? "status-disabled" : ""}`}>
            <i /> {candidate.is_banned ? "Vetado" : "Disponible"}
          </span>
        </div>
      </header>

      {candidate.is_banned && (
        <div className="candidate-ban-alert candidate-ban-alert--detail" role="alert">
          <strong>⚠ Este candidato está vetado</strong>
          <span>{candidate.banned_reason || "El perfil fue vetado por un administrador."}</span>
          <small>
            Se conserva su historial, pero queda excluido de nuevas asignaciones y recomendaciones.
          </small>
        </div>
      )}

      {!evaluationCompleted ? (
        <div className="empty-state">
          <span aria-hidden="true">{evaluation?.status === "FAILED" ? "!" : "↗"}</span>
          <strong>{evaluation?.status === "FAILED" ? "La evaluación no pudo completarse" : "Perfil pendiente de evaluación"}</strong>
          <p>{evaluation?.status === "FAILED"
            ? "Intenta evaluar nuevamente este candidato."
            : "Evalúa este candidato contra una vacante para ver su afinidad."}</p>
          <Link to="/candidates" className="btn btn-primary">Evaluar candidato</Link>
        </div>
      ) : (
        <div className="evaluation-layout">
          <aside className="panel score-panel"><span className="eyebrow">Afinidad global</span><strong className="score score-large">{numericScore}%</strong><div className="score-bar"><div className="score-fill" style={{ width: `${Math.max(0, Math.min(100, numericScore))}%` }} /></div><span className="badge badge-success">{recommendationLabel(evaluation.recommendation)}</span></aside>
          <div className="evaluation-content">
            <section className="panel"><span className="eyebrow">Lectura ejecutiva</span><h2>Resumen del perfil</h2><p className="analysis-copy">{evaluation.summary}</p></section>
            <div className="columns">
              <section className="panel insight-list strength-list"><h2><span>✓</span> Fortalezas</h2><ul>{evaluation.strengths?.map((item, index) => <li key={index}>{item}</li>)}</ul></section>
              <section className="panel insight-list gap-list"><h2><span>!</span> Brechas</h2><ul>{evaluation.gaps?.map((item, index) => <li key={index}>{item}</li>)}</ul></section>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default CandidateDetail;
