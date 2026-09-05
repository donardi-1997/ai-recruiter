import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";

function Jobs() {
  const [jobs, setJobs] = useState([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [editingJob, setEditingJob] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function loadJobs() {
    try {
      const { data } = await api.get("/jobs");
      setJobs(Array.isArray(data) ? data : Array.isArray(data.jobs) ? data.jobs : []);
    } catch (requestError) {
      setJobs([]);
      setError(requestError.response?.data?.detail || requestError.response?.data?.error || "No fue posible cargar las vacantes.");
    }
  }

  useEffect(() => {
    // The initial request synchronizes this view with the API.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadJobs();
  }, []);

  async function saveJob(event) {
    event.preventDefault();
    setError("");
    setSaving(true);
    try {
      if (editingJob) await api.put(`/jobs/${editingJob}`, { title, description });
      else await api.post("/jobs", { title, description });
      cancelForm();
      await loadJobs();
    } catch (requestError) {
      setError(requestError.response?.data?.detail || requestError.response?.data?.error || "No fue posible guardar la vacante.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteJob(id) {
    if (!window.confirm("¿Eliminar esta vacante? Esta acción no se puede deshacer.")) return;
    try {
      setError("");
      await api.delete(`/jobs/${id}`);
      await loadJobs();
    } catch (requestError) {
      setError(requestError.response?.data?.detail || requestError.response?.data?.error || "No fue posible eliminar la vacante.");
    }
  }

  function editJob(job) {
    setEditingJob(job.job_id);
    setTitle(job.title);
    setDescription(job.description);
    setError("");
    setShowForm(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function cancelForm() {
    setTitle("");
    setDescription("");
    setEditingJob(null);
    setShowForm(false);
    setError("");
  }

  function toggleForm() {
    if (showForm) cancelForm();
    else { setEditingJob(null); setTitle(""); setDescription(""); setError(""); setShowForm(true); }
  }

  return (
    <div className="page">
      <header className="page-header split-header">
        <div><span className="eyebrow">Gestión de posiciones</span><h1>Vacantes</h1><p>Define los perfiles que tu equipo necesita incorporar.</p></div>
        <button className="btn btn-primary" onClick={toggleForm}>{showForm ? "Cerrar formulario" : "Nueva vacante"}<span aria-hidden="true">{showForm ? "×" : "＋"}</span></button>
      </header>

      {error && <div className="alert alert-error" role="alert"><strong>No pudimos completar la acción.</strong><span>{error}</span></div>}

      {showForm && (
        <section className="panel job-form-panel">
          <div className="panel-heading"><div><span className="eyebrow">{editingJob ? "Edición" : "Nueva posición"}</span><h2>{editingJob ? "Actualizar vacante" : "Define la vacante"}</h2></div><span className="step-badge">2 datos</span></div>
          <form onSubmit={saveJob} className="job-form">
            <div className="form-group"><label htmlFor="job-title">Título de la vacante</label><input id="job-title" placeholder="Ej. Cloud Engineer" value={title} onChange={(e) => setTitle(e.target.value)} required /></div>
            <div className="form-group"><label htmlFor="job-description">Descripción y requisitos</label><textarea id="job-description" placeholder="Responsabilidades, experiencia, habilidades y criterios de éxito…" value={description} onChange={(e) => setDescription(e.target.value)} required /></div>
            <div className="form-actions"><button type="button" className="btn btn-ghost" onClick={cancelForm}>Cancelar</button><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Guardando…" : editingJob ? "Guardar cambios" : "Crear vacante"}<span aria-hidden="true">→</span></button></div>
          </form>
        </section>
      )}

      <section className="jobs-section">
        <div className="section-heading"><div><h2>Posiciones registradas</h2><p>{jobs.length} {jobs.length === 1 ? "vacante activa" : "vacantes activas"}</p></div></div>
        {jobs.length === 0 ? (
          <div className="empty-state"><span aria-hidden="true">▤</span><strong>Tu tablero de vacantes está vacío</strong><p>Crea una posición para comenzar a comparar candidatos.</p><button className="btn btn-secondary" onClick={() => setShowForm(true)}>Crear primera vacante</button></div>
        ) : (
          <div className="jobs-grid">
            {jobs.map((job) => (
              <article className="job-card" key={job.job_id}>
                <div className="job-card-top"><span className="job-card-icon" aria-hidden="true">▤</span><span className="status-pill"><i /> Activa</span></div>
                <h3>{job.title}</h3><p>{job.description}</p>
                <p className="muted">{job.candidate_count || 0} candidato{job.candidate_count === 1 ? "" : "s"} asignado{job.candidate_count === 1 ? "" : "s"}</p>
                <div className="job-card-actions"><Link className="btn btn-primary" to={`/candidates?job_id=${job.job_id}`}>Agregar candidatos</Link><button className="btn btn-secondary" onClick={() => editJob(job)}>Editar</button><button className="btn btn-danger btn-icon" aria-label={`Eliminar ${job.title}`} onClick={() => deleteJob(job.job_id)}>⌫</button></div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default Jobs;
