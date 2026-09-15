// eslint-disable-next-line no-unused-vars
import React, { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import api from "../api/client";

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

  useEffect(() => {
    async function load() {
      try {
        const [candidateResponse, evaluationResponse] = await Promise.all([
          api.get(`/candidates/${candidate_id}`),
          api.get(jobId
            ? `/jobs/${jobId}/candidates/${candidate_id}`
            : `/candidates/${candidate_id}/evaluations`),
        ]);
        setCandidate(candidateResponse.data);
        setEvaluations(jobId
          ? [evaluationResponse.data]
          : evaluationResponse.data.evaluations || []);

        if (jobId) {
          try {
            const indeedResponse = await api.get(
              `/jobs/${jobId}/candidates/${candidate_id}/integrations/indeed`
            );
            setIndeedDetails(indeedResponse.data);
          } catch {
            // Not every candidate comes from Indeed. Keep the core profile usable.
            setIndeedDetails(null);
          }
        }
      } catch (error) {
        console.error("No fue posible cargar el candidato", error);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [candidate_id, jobId]);

  async function openResume() {
    if (!jobId || !indeedDetails?.resume?.available) return;
    setOpeningResume(true);
    setResumeError("");
    try {
      const response = await api.get(
        `/jobs/${jobId}/candidates/${candidate_id}/resume`
      );
      window.open(response.data.url, "_blank", "noopener,noreferrer");
    } catch {
      setResumeError("No fue posible abrir el CV. Intenta nuevamente.");
    } finally {
      setOpeningResume(false);
    }
  }

  if (loading) return <div className="page"><div className="page-loading"><span /> Cargando perfil…</div></div>;
  const evaluation = evaluations[0];
  const sourceName = indeedDetails?.source_name || candidate?.metadata?.source_name || candidate?.metadata?.source;
  const resume = indeedDetails?.resume;
  const resumeName = resume?.name || candidate?.filename || candidate?.metadata?.resume_name || "Currículum registrado";
  const isIndeedTest = indeedDetails?.staged_test ?? candidate?.metadata?.indeed_staged_test;

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
          {resume?.available && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={openResume}
              disabled={openingResume}
            >
              {openingResume ? "Abriendo…" : "Ver CV"}
            </button>
          )}
          {resumeError && <p className="muted">{resumeError}</p>}
          {jobId && <p>Evaluado para la vacante seleccionada</p>}
        </div>
        <span className="status-pill"><i /> Disponible</span>
      </header>

      {!evaluation ? (
        <div className="empty-state"><span aria-hidden="true">↗</span><strong>Perfil pendiente de evaluación</strong><p>Evalúa este candidato contra una vacante para ver su afinidad.</p><Link to="/candidates" className="btn btn-primary">Evaluar candidato</Link></div>
      ) : (
        <div className="evaluation-layout">
          <aside className="panel score-panel"><span className="eyebrow">Afinidad global</span><strong className="score score-large">{evaluation.match_score}%</strong><div className="score-bar"><div className="score-fill" style={{ width: `${evaluation.match_score}%` }} /></div><span className="badge badge-success">{evaluation.recommendation}</span></aside>
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
