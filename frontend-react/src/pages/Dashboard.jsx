// eslint-disable-next-line no-unused-vars
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import { useSession } from "../context/SessionContext";

function getGreeting(date = new Date()) {
  const hour = date.getHours();

  if (hour >= 5 && hour < 12) return "Buenos días";
  if (hour >= 12 && hour < 19) return "Buenas tardes";
  return "Buenas noches";
}

function Dashboard() {
  const { principal, hasPermission } = useSession();
  const canRecruit = hasPermission("jobs.read") && hasPermission("candidates.read");
  const canManageEmployees = hasPermission("employees.read");
  const [jobs, setJobs] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [trainingAssignments, setTrainingAssignments] = useState([]);
  const [employeeSummary, setEmployeeSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [greeting, setGreeting] = useState(() => getGreeting());
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    const updateGreeting = () => setGreeting(getGreeting());
    const intervalId = window.setInterval(updateGreeting, 60_000);

    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    async function load() {
      try {
        if (canRecruit) {
          const requests = [
            api.get("/jobs"),
            api.get("/candidates"),
          ];
          if (canManageEmployees) {
            requests.push(api.get("/employees/summary"));
          }

          const [jobsResponse, candidatesResponse, employeeSummaryResponse] = await Promise.all(requests);
          const jobsData = jobsResponse.data;
          const candidatesData = candidatesResponse.data;
          setJobs(Array.isArray(jobsData) ? jobsData : jobsData.jobs || []);
          setCandidates(Array.isArray(candidatesData) ? candidatesData : candidatesData.candidates || []);
          if (canManageEmployees && employeeSummaryResponse) {
            setEmployeeSummary(employeeSummaryResponse.data);
          }
        } else {
          const { data } = await api.get("/training/me");
          setTrainingAssignments(Array.isArray(data?.items) ? data.items : []);
        }
      } catch {
        setLoadError("No fue posible cargar el resumen.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [canManageEmployees, canRecruit]);

  if (loading) {
    return <div className="page"><div className="page-loading"><span /> Preparando tu workspace…</div></div>;
  }

  if (!canRecruit) {
    const firstName = principal?.profile?.first_name || "equipo";
    const completedCourses = trainingAssignments.filter(
      (assignment) => assignment.status === "COMPLETED",
    ).length;
    const overallProgress = trainingAssignments.length
      ? Math.round(
        trainingAssignments.reduce(
          (total, assignment) => total + (assignment.course?.progress_percent || 0),
          0,
        ) / trainingAssignments.length,
      )
      : 0;

    return (
      <div className="page dashboard-page employee-dashboard">
        <header className="page-header dashboard-header">
          <div>
            <span className="eyebrow">Tu espacio ASIATI</span>
            <h1>{greeting}, {firstName}.</h1>
            <p>Aquí encontrarás tu proceso de inducción, capacitación y progreso.</p>
          </div>
        </header>

        {loadError && (
          <div className="alert" role="alert">{loadError}</div>
        )}

        <section className="panel employee-welcome-panel">
          <div className="employee-welcome-copy">
            <span className="eyebrow">Onboarding</span>
            <h2>Conoce ASIATI y cómo trabajamos.</h2>
            <p>
              {trainingAssignments.length
                ? `Tienes ${trainingAssignments.length} curso${trainingAssignments.length === 1 ? "" : "s"} asignado${trainingAssignments.length === 1 ? "" : "s"}.`
                : "Cuando te asignen una capacitación aparecerá aquí automáticamente."}
            </p>
            <span className="employee-onboarding-state">
              Onboarding: {
                principal?.profile?.onboarding_status === "COMPLETED"
                  ? "Completado"
                  : principal?.profile?.onboarding_status === "IN_PROGRESS"
                    ? "En progreso"
                    : principal?.profile?.onboarding_status === "PENDING"
                      ? "Pendiente"
                      : "No requerido"
              }
            </span>
            <Link className="btn btn-primary" to="/training">Ir a capacitación</Link>
          </div>
          <div className="employee-progress-preview" aria-label="Progreso de capacitación">
            <span>Progreso general</span>
            <strong>{overallProgress}%</strong>
            <div><i style={{ width: `${overallProgress}%` }} /></div>
            <small>
              {trainingAssignments.length
                ? `${completedCourses} de ${trainingAssignments.length} cursos completados`
                : "Aún no tienes cursos asignados."}
            </small>
          </div>
        </section>
      </div>
    );
  }

  const coverage = jobs.length ? Math.min(100, Math.round((candidates.length / jobs.length) * 20)) : 0;

  return (
    <div className="page dashboard-page">
      <header className="page-header dashboard-header">
        <div>
          <span className="eyebrow">Vista general</span>
          <h1>{greeting}, equipo.</h1>
          <p>Así avanza tu proceso de selección hoy.</p>
        </div>
       </header>

      {loadError && (
        <div className="empty-state" role="alert">
          <strong>No se pudo cargar el resumen</strong>
          <p>{loadError}</p>
        </div>
      )}

      <section className="metrics-grid" aria-label="Indicadores principales">
        <MetricCard icon="▤" label="Vacantes activas" value={jobs.length} detail="Procesos en seguimiento" tone="blue" />
        <MetricCard icon="◎" label="Talento disponible" value={candidates.length} detail="Perfiles centralizados" tone="cyan" />
        <MetricCard icon="↗" label="Cobertura estimada" value={`${coverage}%`} detail="Candidatos por vacante" tone="violet" />
      </section>

      {canManageEmployees && employeeSummary && (
        <section className="panel onboarding-summary-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Talento Humano</span>
              <h2>Onboarding del equipo</h2>
            </div>
            <Link to="/employees">Ver empleados <span aria-hidden="true">→</span></Link>
          </div>

          <div className="onboarding-summary-grid">
            <div>
              <span>Empleados activos</span>
              <strong>{employeeSummary.active}</strong>
            </div>
            <div>
              <span>Pendientes</span>
              <strong>{employeeSummary.onboarding.pending}</strong>
            </div>
            <div>
              <span>En progreso</span>
              <strong>{employeeSummary.onboarding.in_progress}</strong>
            </div>
            <div>
              <span>Completados</span>
              <strong>{employeeSummary.onboarding.completed}</strong>
            </div>
            <div className="onboarding-summary-progress">
              <span>Finalización onboarding</span>
              <strong>{employeeSummary.onboarding.completion_percent}%</strong>
              <div><i style={{ width: `${employeeSummary.onboarding.completion_percent}%` }} /></div>
            </div>
          </div>
        </section>
      )}

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
