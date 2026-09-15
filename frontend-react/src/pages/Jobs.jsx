// eslint-disable-next-line no-unused-vars
import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import "./Jobs.css";

const MAX_PAGES = 100;

function formatDate(iso) {
  if (!iso) return "Sin fecha";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "Sin fecha";
    return d.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return "Sin fecha";
  }
}

function indeedLifecycle(status) {
  return status?.status?.globalStatus?.lifecycleStatus || status?.status?.lifecycleStatus || null;
}

async function loadAllJobCandidates(jobId) {
  const pageSize = 100;
  let page = 1;
  const all = [];
  while (page <= MAX_PAGES) {
    const { data } = await api.get(`/jobs/${jobId}/candidates`, { params: { page, page_size: pageSize } });
    const items = Array.isArray(data) ? data : [];
    all.push(...items);
    if (items.length < pageSize) break;
    page += 1;
  }
  if (page > MAX_PAGES) throw new Error("Límite de páginas alcanzado.");
  return all;
}

function Jobs() {
  const [jobs, setJobs] = useState([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [countryCode, setCountryCode] = useState("");
  const [city, setCity] = useState("");
  const [employmentType, setEmploymentType] = useState("");
  const [publicSlug, setPublicSlug] = useState("");
  const [editingJob, setEditingJob] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const [viewJob, setViewJob] = useState(null);
  const [jobCandidates, setJobCandidates] = useState([]);
  const [jobCandidatesLoading, setJobCandidatesLoading] = useState(false);
  const [jobCandidatesError, setJobCandidatesError] = useState("");

  const [indeedIntegration, setIndeedIntegration] = useState(null);
  const [indeedJobStatus, setIndeedJobStatus] = useState(null);
  const [indeedBusy, setIndeedBusy] = useState("");
  const [indeedError, setIndeedError] = useState("");

  const [deleteJobTarget, setDeleteJobTarget] = useState(null);
  const [deletingJob, setDeletingJob] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  const [successMessage, setSuccessMessage] = useState("");

  async function loadJobs() {
    try {
      const { data } = await api.get("/jobs");
      setJobs(Array.isArray(data) ? data : Array.isArray(data.jobs) ? data.jobs : []);
    } catch (requestError) {
      setJobs([]);
      setError(requestError.response?.data?.detail || requestError.response?.data?.error || "No fue posible cargar las vacantes.");
    }
  }

  async function loadIndeedIntegrationStatus() {
    try {
      const { data } = await api.get("/integrations/indeed/status");
      setIndeedIntegration(data);
    } catch {
      setIndeedIntegration({ enabled: false, configured: false });
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadJobs();
    loadIndeedIntegrationStatus();
  }, []);

  useEffect(() => {
    const modalOpen = !!(viewJob || deleteJobTarget);
    if (modalOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [viewJob, deleteJobTarget]);

  const closeJobDetails = useCallback(() => {
    setViewJob(null);
    setJobCandidates([]);
    setJobCandidatesError("");
    setIndeedJobStatus(null);
    setIndeedError("");
  }, []);

  useEffect(() => {
    function handleEscape(e) {
      if (e.key !== "Escape") return;
      if (deleteJobTarget && !deletingJob) {
        setDeleteJobTarget(null);
        setDeleteError("");
      } else if (viewJob) {
        setViewJob(null);
        setJobCandidates([]);
        setJobCandidatesError("");
        setIndeedJobStatus(null);
        setIndeedError("");
      }
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [deleteJobTarget, deletingJob, viewJob]);

  async function refreshIndeedJobStatus(job = viewJob) {
    if (!job || !indeedIntegration?.enabled || !indeedIntegration?.configured) return;
    setIndeedError("");
    try {
      const { data } = await api.get(`/jobs/${job.job_id}/integrations/indeed/status`);
      setIndeedJobStatus(data);
    } catch (requestError) {
      if (requestError.response?.status === 404) {
        setIndeedJobStatus({ unpublished: true });
        return;
      }
      setIndeedError(requestError.response?.data?.detail || "No fue posible consultar Indeed.");
    }
  }

  async function openJobDetails(job) {
    if (deleteJobTarget) {
      setDeleteJobTarget(null);
      setDeleteError("");
    }
    setViewJob(job);
    setJobCandidates([]);
    setJobCandidatesError("");
    setIndeedJobStatus(null);
    setIndeedError("");
    setJobCandidatesLoading(true);
    try {
      const all = await loadAllJobCandidates(job.job_id);
      setJobCandidates(all);
    } catch {
      setJobCandidatesError("No fue posible cargar los candidatos de esta vacante.");
    } finally {
      setJobCandidatesLoading(false);
    }
    await refreshIndeedJobStatus(job);
  }

  async function publishToIndeed() {
    if (!viewJob || indeedBusy) return;
    setIndeedBusy("publish");
    setIndeedError("");
    try {
      const { data } = await api.post(`/jobs/${viewJob.job_id}/integrations/indeed/publish`);
      setIndeedJobStatus(data);
      setSuccessMessage("Vacante enviada a Indeed.");
      setTimeout(() => setSuccessMessage(""), 5000);
    } catch (requestError) {
      setIndeedError(requestError.response?.data?.detail || "No fue posible publicar en Indeed.");
    } finally {
      setIndeedBusy("");
    }
  }

  async function expireOnIndeed() {
    if (!viewJob || indeedBusy) return;
    setIndeedBusy("expire");
    setIndeedError("");
    try {
      const { data } = await api.post(`/jobs/${viewJob.job_id}/integrations/indeed/expire`);
      setIndeedJobStatus(data);
      setSuccessMessage("Se solicitó el cierre de la vacante en Indeed.");
      setTimeout(() => setSuccessMessage(""), 5000);
    } catch (requestError) {
      setIndeedError(requestError.response?.data?.detail || "No fue posible cerrar la vacante en Indeed.");
    } finally {
      setIndeedBusy("");
    }
  }

  async function syncIndeedCandidates() {
    if (indeedBusy) return;
    setIndeedBusy("candidates");
    setIndeedError("");
    try {
      const { data } = await api.post("/integrations/indeed/candidates/sync");
      if (viewJob) {
        const all = await loadAllJobCandidates(viewJob.job_id);
        setJobCandidates(all);
      }
      setSuccessMessage(`Indeed: ${data.fetched || 0} candidatos procesados; ${data.created || 0} nuevos.`);
      setTimeout(() => setSuccessMessage(""), 5000);
    } catch (requestError) {
      setIndeedError(requestError.response?.data?.detail || "No fue posible sincronizar candidatos de Indeed.");
    } finally {
      setIndeedBusy("");
    }
  }

  async function syncIndeedDispositions() {
    if (indeedBusy) return;
    setIndeedBusy("dispositions");
    setIndeedError("");
    try {
      const { data } = await api.post("/integrations/indeed/dispositions/sync");
      setSuccessMessage(`Indeed: ${data.sent || 0} estados enviados; ${data.failed || 0} fallidos.`);
      setTimeout(() => setSuccessMessage(""), 5000);
    } catch (requestError) {
      setIndeedError(requestError.response?.data?.detail || "No fue posible sincronizar estados con Indeed.");
    } finally {
      setIndeedBusy("");
    }
  }

  function openDeleteJobModal(job) {
    if (viewJob) {
      closeJobDetails();
    }
    setDeleteJobTarget(job);
    setDeleteError("");
  }

  async function confirmDeleteJob(deleteCandidates) {
    if (!deleteJobTarget || deletingJob) return;
    try {
      setDeletingJob(true);
      setDeleteError("");
      await api.delete(`/jobs/${deleteJobTarget.job_id}`, { params: { delete_candidates: deleteCandidates } });
      setDeleteJobTarget(null);
      setDeleteError("");
      if (viewJob && viewJob.job_id === deleteJobTarget.job_id) closeJobDetails();
      await loadJobs();
      setSuccessMessage(
        deleteCandidates
          ? `Vacante y ${deleteJobTarget.candidate_count || 0} candidatos eliminados.`
          : "Vacante eliminada. Los candidatos se conservaron."
      );
      setTimeout(() => setSuccessMessage(""), 5000);
    } catch (requestError) {
      setDeleteError(requestError.response?.data?.detail || "No fue posible eliminar la vacante. Intenta nuevamente.");
    } finally {
      setDeletingJob(false);
    }
  }

  async function saveJob(event) {
    event.preventDefault();
    setError("");
    setSaving(true);
    const payload = {
      title,
      description,
      country_code: countryCode,
      city,
      employment_type: employmentType,
      public_slug: publicSlug,
    };
    try {
      if (editingJob) await api.put(`/jobs/${editingJob}`, payload);
      else await api.post("/jobs", payload);
      cancelForm();
      await loadJobs();
    } catch (requestError) {
      setError(requestError.response?.data?.detail || requestError.response?.data?.error || "No fue posible guardar la vacante.");
    } finally {
      setSaving(false);
    }
  }

  function editJob(job) {
    setEditingJob(job.job_id);
    setTitle(job.title);
    setDescription(job.description || "");
    setCountryCode(job.country_code || "");
    setCity(job.city || "");
    setEmploymentType(job.employment_type || "");
    setPublicSlug(job.public_slug || "");
    setError("");
    setShowForm(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function resetJobFields() {
    setTitle("");
    setDescription("");
    setCountryCode("");
    setCity("");
    setEmploymentType("");
    setPublicSlug("");
  }

  function cancelForm() {
    resetJobFields();
    setEditingJob(null);
    setShowForm(false);
    setError("");
  }

  function toggleForm() {
    if (showForm) cancelForm();
    else { setEditingJob(null); resetJobFields(); setError(""); setShowForm(true); }
  }

  const indeedReady = !!(indeedIntegration?.enabled && indeedIntegration?.configured);
  const lifecycle = indeedLifecycle(indeedJobStatus);
  const indeedPublished = !!(indeedJobStatus?.sourced_posting_id && !indeedJobStatus?.unpublished);

  return (
    <div className="page">
      <header className="page-header split-header">
        <div><span className="eyebrow">Gestión de posiciones</span><h1>Vacantes</h1><p>Define los perfiles que tu equipo necesita incorporar.</p></div>
        <button className="btn btn-primary" onClick={toggleForm}>{showForm ? "Cerrar formulario" : "Nueva vacante"}<span aria-hidden="true">{showForm ? "×" : "＋"}</span></button>
      </header>

      {error && <div className="alert alert-error" role="alert"><strong>No pudimos completar la acción.</strong><span>{error}</span></div>}
      {successMessage && <div className="alert alert-success" role="status" style={{ background: "var(--success-bg)", color: "var(--success)", borderColor: "var(--success)" }}>{successMessage}</div>}

      {showForm && (
        <section className="panel job-form-panel">
          <div className="panel-heading"><div><span className="eyebrow">{editingJob ? "Edición" : "Nueva posición"}</span><h2>{editingJob ? "Actualizar vacante" : "Define la vacante"}</h2></div><span className="step-badge">6 datos</span></div>
          <form onSubmit={saveJob} className="job-form">
            <div className="form-group"><label htmlFor="job-title">Título de la vacante</label><input id="job-title" maxLength={75} placeholder="Ej. Cloud Engineer" value={title} onChange={(e) => setTitle(e.target.value)} required /></div>
            <div className="form-group"><label htmlFor="job-description">Descripción y requisitos</label><textarea id="job-description" placeholder="Responsabilidades, experiencia, habilidades y criterios de éxito…" value={description} onChange={(e) => setDescription(e.target.value)} required /></div>
            <div className="job-publication-grid">
              <div className="form-group"><label htmlFor="job-country">País (ISO)</label><input id="job-country" maxLength={2} placeholder="CO" value={countryCode} onChange={(e) => setCountryCode(e.target.value.toUpperCase())} /></div>
              <div className="form-group"><label htmlFor="job-city">Ciudad</label><input id="job-city" placeholder="Bogotá" value={city} onChange={(e) => setCity(e.target.value)} /></div>
              <div className="form-group"><label htmlFor="job-employment">Tipo de empleo</label><select id="job-employment" value={employmentType} onChange={(e) => setEmploymentType(e.target.value)}><option value="">Sin definir</option><option value="FULL_TIME">Tiempo completo</option><option value="PART_TIME">Medio tiempo</option><option value="CONTRACT">Contrato</option><option value="TEMPORARY">Temporal</option><option value="INTERNSHIP">Prácticas</option></select></div>
              <div className="form-group"><label htmlFor="job-slug">URL pública</label><input id="job-slug" placeholder="country-manager-chile" value={publicSlug} onChange={(e) => setPublicSlug(e.target.value)} /></div>
            </div>
            <p className="muted job-publication-hint">Estos datos permiten publicar la misma vacante en asiaticorp.com/jobs e Indeed sin duplicarla.</p>
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
                {(job.city || job.country_code) && <p className="muted">{[job.city, job.country_code].filter(Boolean).join(" · ")}</p>}
                <p className="muted">{job.candidate_count || 0} candidato{job.candidate_count === 1 ? "" : "s"} asignado{job.candidate_count === 1 ? "" : "s"}</p>
                <div className="job-card-actions">
                  <button type="button" className="btn btn-primary" onClick={() => openJobDetails(job)}>Ver</button>
                  <Link className="btn btn-primary" to={`/candidates?job_id=${job.job_id}`}>Agregar candidatos</Link>
                  <button className="btn btn-secondary" onClick={() => editJob(job)}>Editar</button>
                  <button className="btn btn-danger" onClick={() => openDeleteJobModal(job)}>Eliminar</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {viewJob && (
        <div className="modal-overlay" onClick={closeJobDetails}>
          <div className="modal job-detail-modal" role="dialog" aria-modal="true" aria-labelledby="job-details-title" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <span className="eyebrow">Vacante</span>
                <h2 id="job-details-title">{viewJob.title}</h2>
                <span className="status-pill" style={{ marginTop: 8 }}><i /> Activa</span>
              </div>
              <button className="btn btn-close" onClick={closeJobDetails} aria-label="Cerrar detalle de vacante"><span aria-hidden="true">✕</span></button>
            </div>

            <div className="job-detail-section">
              <h3>Información de la vacante</h3>
              <div className="job-detail-info-grid">
                <div><span className="muted">Título</span><strong>{viewJob.title}</strong></div>
                <div><span className="muted">Fecha de creación</span><strong>{formatDate(viewJob.created_at)}</strong></div>
                <div><span className="muted">Candidatos</span><strong>{viewJob.candidate_count || 0}</strong></div>
                <div><span className="muted">Ubicación</span><strong>{[viewJob.city, viewJob.country_code].filter(Boolean).join(", ") || "Sin definir"}</strong></div>
              </div>
            </div>

            <div className="job-detail-section">
              <h3>Descripción y requisitos</h3>
              <p className="job-detail-description">{viewJob.description || "Sin descripción."}</p>
            </div>

            <div className="job-detail-section indeed-panel">
              <div className="job-detail-candidates-header"><h3>Indeed Employers</h3><span className={`badge ${indeedReady ? "badge-success" : ""}`}>{indeedReady ? "Conectado" : "No configurado"}</span></div>
              {!indeedReady ? (
                <p className="muted">La integración está instalada pero desactivada hasta configurar las credenciales de Indeed.</p>
              ) : (
                <>
                  <div className="indeed-status-grid">
                    <div><span className="muted">Publicación</span><strong>{indeedPublished ? "Publicada" : "No publicada"}</strong></div>
                    <div><span className="muted">Estado</span><strong>{lifecycle || (indeedPublished ? "Pendiente de consulta" : "—")}</strong></div>
                  </div>
                  {indeedError && <div className="job-detail-error"><p>{indeedError}</p></div>}
                  <div className="indeed-actions">
                    {!indeedPublished && <button className="btn btn-primary" disabled={!!indeedBusy} onClick={publishToIndeed}>{indeedBusy === "publish" ? "Publicando…" : "Publicar en Indeed"}</button>}
                    {indeedPublished && <button className="btn btn-secondary" disabled={!!indeedBusy} onClick={() => refreshIndeedJobStatus()}>{indeedBusy === "status" ? "Consultando…" : "Actualizar estado"}</button>}
                    <button className="btn btn-secondary" disabled={!!indeedBusy} onClick={syncIndeedCandidates}>{indeedBusy === "candidates" ? "Sincronizando…" : "Sincronizar candidatos"}</button>
                    <button className="btn btn-secondary" disabled={!!indeedBusy} onClick={syncIndeedDispositions}>{indeedBusy === "dispositions" ? "Enviando…" : "Sincronizar estados"}</button>
                    {indeedPublished && <button className="btn btn-danger" disabled={!!indeedBusy} onClick={expireOnIndeed}>{indeedBusy === "expire" ? "Cerrando…" : "Cerrar en Indeed"}</button>}
                  </div>
                </>
              )}
            </div>

            <div className="job-detail-section">
              <div className="job-detail-candidates-header"><h3>Candidatos asignados</h3><span className="badge badge-success">{jobCandidates.length}</span></div>

              {jobCandidatesLoading && <div className="job-detail-loading"><span className="page-loading"><span />Cargando candidatos…</span></div>}
              {!jobCandidatesLoading && jobCandidatesError && <div className="job-detail-error"><p>{jobCandidatesError}</p><button className="btn btn-secondary" onClick={() => openJobDetails(viewJob)}>Reintentar</button></div>}
              {!jobCandidatesLoading && !jobCandidatesError && jobCandidates.length === 0 && <div className="job-detail-empty"><p>No hay candidatos asignados a esta vacante.</p><Link className="btn btn-primary" to={`/candidates?job_id=${viewJob.job_id}`}>Agregar candidatos</Link></div>}
              {!jobCandidatesLoading && !jobCandidatesError && jobCandidates.length > 0 && (
                <div className="job-detail-candidate-list">
                  {jobCandidates.map((c) => (
                    <div className="job-detail-candidate-row" key={c.candidate_id}>
                      <div className="job-detail-candidate-avatar" aria-hidden="true">{(c.name || "?").charAt(0).toUpperCase()}</div>
                      <div className="job-detail-candidate-info"><strong>{c.name || "Sin nombre"}</strong><span>{c.email || "Sin correo registrado"}</span><small>{c.filename || "CV sin nombre"}</small></div>
                      <Link className="btn btn-secondary btn-sm" to={`/candidates/${c.candidate_id}`}>Ver candidato</Link>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="modal-footer"><button type="button" className="btn btn-ghost" onClick={closeJobDetails}>Cerrar</button><Link className="btn btn-primary" to={`/candidates?job_id=${viewJob.job_id}`}>Agregar candidatos</Link></div>
          </div>
        </div>
      )}

      {deleteJobTarget && (
        <div className="modal-overlay" onClick={() => { if (!deletingJob) { setDeleteJobTarget(null); setDeleteError(""); } }}>
          <div className="modal job-delete-modal" role="dialog" aria-modal="true" aria-labelledby="delete-job-title" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div><span className="eyebrow" style={{ color: "var(--danger)" }}>⚠ Eliminar vacante</span><h2 id="delete-job-title">¿qué deseas eliminar?</h2></div>
              <button className="btn btn-close" onClick={() => { if (!deletingJob) { setDeleteJobTarget(null); setDeleteError(""); } }} disabled={deletingJob} aria-label="Cerrar modal de eliminación"><span aria-hidden="true">✕</span></button>
            </div>

            <p className="job-delete-job-title">{deleteJobTarget.title}</p>
            <p className="muted" style={{ marginBottom: 16 }}>Esta vacante tiene {deleteJobTarget.candidate_count || 0} candidato{deleteJobTarget.candidate_count === 1 ? "" : "s"} asignado{deleteJobTarget.candidate_count === 1 ? "" : "s"}.</p>
            {deleteError && <div className="job-delete-error" role="alert">{deleteError}</div>}

            <div className="job-delete-options">
              <button type="button" className="job-delete-option job-delete-option-danger-outline" disabled={deletingJob} onClick={() => confirmDeleteJob(false)}><strong>Borrar solo la vacante</strong><span>Conserva los candidatos en tu cuenta.</span></button>
              <button type="button" className="job-delete-option job-delete-option-danger-solid" disabled={deletingJob || !deleteJobTarget.candidate_count} onClick={() => confirmDeleteJob(true)}><strong>Borrar vacante y candidatos</strong><span>Elimina también los {deleteJobTarget.candidate_count || 0} candidatos.{(deleteJobTarget.candidate_count || 0) > 0 && " Puede afectar otras vacantes donde estén."}</span></button>
              <button type="button" className="job-delete-option job-delete-option-cancel" disabled={deletingJob} onClick={() => { setDeleteJobTarget(null); setDeleteError(""); }}>Cancelar</button>
            </div>
            {deletingJob && <p className="job-delete-loading">Eliminando…</p>}
          </div>
        </div>
      )}
    </div>
  );
}

export default Jobs;