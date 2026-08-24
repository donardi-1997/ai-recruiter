import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api from "../api/client";

function CandidateDetail() {
  const { candidate_id } = useParams();
  const [candidate, setCandidate] = useState(null);
  const [evaluations, setEvaluations] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [candidateResponse, evaluationResponse] = await Promise.all([
          api.get(`/candidates/${candidate_id}`),
          api.get(`/candidates/${candidate_id}/evaluations`),
        ]);
        setCandidate(candidateResponse.data);
        setEvaluations(evaluationResponse.data.evaluations || []);
      } catch (error) {
        console.error("No fue posible cargar el candidato", error);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [candidate_id]);

  if (loading) return <div className="page"><div className="page-loading"><span /> Cargando perfil…</div></div>;
  const evaluation = evaluations[0];

  return (
    <div className="page candidate-detail-page">
      <Link to="/candidates" className="back-link">← Volver a candidatos</Link>
      <header className="candidate-profile-header">
        <div className="candidate-avatar">{candidate?.name?.slice(0, 2).toUpperCase() || "CV"}</div>
        <div><span className="eyebrow">Perfil de candidato</span><h1>{candidate?.name || "Candidato"}</h1><p>{candidate?.filename || "Currículum registrado"}</p></div>
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
