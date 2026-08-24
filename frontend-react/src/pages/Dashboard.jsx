import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";

function Dashboard() {
  const [jobs, setJobs] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [jobsResponse, candidatesResponse] = await Promise.all([
          api.get("/jobs"),
          api.get("/candidates"),
        ]);
        const jobsData = jobsResponse.data;
        const candidatesData = candidatesResponse.data;
        setJobs(Array.isArray(jobsData) ? jobsData : jobsData.jobs || []);
        setCandidates(Array.isArray(candidatesData) ? candidatesData : candidatesData.candidates || []);
      } catch (error) {
        console.error("No fue posible cargar el resumen", error);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return <div className="page"><div className="page-loading"><span /> Preparando tu workspace…</div></div>;
  }

  const coverage = jobs.length ? Math.min(100, Math.round((candidates.length / jobs.length) * 20)) : 0;

  return (
    <div className="page dashboard-page">
      <header className="page-header dashboard-header">
        <div>
          <span className="eyebrow">Vista general</span>
          <h1>Buenos días, equipo.</h1>
          <p>Así avanza tu proceso de selección hoy.</p>
        </div>
        <Link className="btn btn-primary" to="/candidates">Agregar candidato <span aria-hidden="true">＋</span></Link>
      </header>

      <section className="metrics-grid" aria-label="Indicadores principales">
        <MetricCard icon="▤" label="Vacantes activas" value={jobs.length} detail="Procesos en seguimiento" tone="blue" />
        <MetricCard icon="◎" label="Talento disponible" value={candidates.length} detail="Perfiles centralizados" tone="cyan" />
        <MetricCard icon="↗" label="Cobertura estimada" value={`${coverage}%`} detail="Candidatos por vacante" tone="violet" />
      </section>

      <div className="dashboard-grid">
        <section className="panel recent-jobs-panel">
          <div className="panel-heading">
            <div><span className="eyebrow">Pipeline</span><h2>Vacantes recientes</h2></div>
            <Link to="/jobs">Ver todas <span aria-hidden="true">→</span></Link>
          </div>

          {jobs.length === 0 ? (
            <div className="empty-state compact"><span aria-hidden="true">▤</span><strong>Aún no hay vacantes</strong><p>Crea la primera para comenzar a evaluar talento.</p><Link className="btn btn-secondary" to="/jobs">Crear vacante</Link></div>
          ) : (
            <div className="job-list">
              {jobs.slice(0, 4).map((job, index) => (
                <article className="job-row" key={job.job_id}>
                  <span className="job-index">{String(index + 1).padStart(2, "0")}</span>
                  <div><h3>{job.title}</h3><p>{job.description}</p></div>
                  <span className="status-pill"><i /> Activa</span>
                </article>
              ))}
            </div>
          )}
        </section>

        <aside className="panel intelligence-panel">
          <div className="intelligence-orb"><span>AI</span></div>
          <span className="eyebrow eyebrow-dark">Talent intelligence</span>
          <h2>Del currículum a la evidencia.</h2>
          <p>Compara cada perfil con los requisitos de la vacante y obtén fortalezas, brechas y una recomendación clara.</p>
          <Link className="text-link-light" to="/ranking">Explorar ranking <span aria-hidden="true">↗</span></Link>
        </aside>
      </div>
    </div>
  );
}

function MetricCard({ icon, label, value, detail, tone }) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div className="metric-top"><span className="metric-icon" aria-hidden="true">{icon}</span><span className="metric-trend">En vivo</span></div>
      <strong className="metric-value">{value}</strong>
      <span className="metric-label">{label}</span>
      <small>{detail}</small>
    </article>
  );
}

export default Dashboard;
