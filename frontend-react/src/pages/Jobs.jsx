// eslint-disable-next-line no-unused-vars
import React, { useEffect, useState, useCallback, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api from "../api/client";
import "./Jobs.css";
import "./JobsPagination.css";

const MAX_PAGES = 100;
const PAGE_SIZE_OPTIONS = [12, 24, 48];
const SORT_OPTIONS = new Set([
  "created_desc",
  "created_asc",
  "candidates_desc",
  "candidates_asc",
]);

function positiveInteger(value, fallback) {
  const parsed = Number.parseInt(String(value || ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function compactPageNumbers(totalPages, currentPage) {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1);
  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  return [...pages]
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((a, b) => a - b);
}

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

function proposalList(values) {
  return (Array.isArray(values) ? values : [])
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

function appendProposalSection(blocks, label, values) {
  const items = proposalList(values);
  if (!items.length) return;
  blocks.push(`${label}\n${items.map((item) => `- ${item}`).join("\n")}`);
}

function formatEnrichmentProposalDescription(proposal, fallbackDescription = "") {
  const source = proposal || {};
  const blocks = [];
  const introduction = String(
    source.improved_description || fallbackDescription || ""
  ).trim();

  if (introduction) blocks.push(introduction);

  appendProposalSection(blocks, "Tecnologías requeridas", source.required_technologies);
  appendProposalSection(blocks, "Tecnologías deseables", source.preferred_technologies);

  appendProposalSection(
    blocks,
    "Certificaciones sugeridas",
    [
      ...proposalList(source.required_certifications),
      ...proposalList(source.preferred_certifications),
    ],
  );

  const experience = [];
  if (
    source.minimum_years_experience !== null
    && source.minimum_years_experience !== undefined
    && source.minimum_years_experience !== ""
  ) {
    experience.push(
      `Experiencia mínima de ${source.minimum_years_experience} años.`
    );
  }
  experience.push(...proposalList(source.specific_experience));
  appendProposalSection(blocks, "Experiencia específica", experience);

  appendProposalSection(blocks, "Responsabilidades", source.responsibilities);
  appendProposalSection(blocks, "Conocimiento de dominio", source.domain_knowledge);
  appendProposalSection(blocks, "Educación", source.education);
  appendProposalSection(blocks, "Idiomas", source.languages);
  appendProposalSection(blocks, "Competencias técnicas", source.technical_competencies);
  appendProposalSection(
    blocks,
    "Preguntas por validar (no son requisitos de evaluación)",
    source.assumptions_to_validate,
  );

  return blocks.join("\n\n").trim();
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
  const [searchParams, setSearchParams] = useSearchParams();
  const page = positiveInteger(searchParams.get("page"), 1);
  const requestedPageSize = positiveInteger(searchParams.get("page_size"), 12);
  const pageSize = PAGE_SIZE_OPTIONS.includes(requestedPageSize) ? requestedPageSize : 12;
  const requestedSort = searchParams.get("sort") || "created_desc";
  const sort = SORT_OPTIONS.has(requestedSort) ? requestedSort : "created_desc";
  const query = searchParams.get("q") || "";

  const [jobs, setJobs] = useState([]);
  const [jobsPage, setJobsPage] = useState({
    page,
    page_size: pageSize,
    total: 0,
    total_pages: 0,
  });
  const [jobSearch, setJobSearch] = useState(query);
  const [title, setTitle] = useState("");
  const [indeedDescription, setIndeedDescription] = useState("");
  const [aiDescription, setAiDescription] = useState("");
  const [activeDescriptionSource, setActiveDescriptionSource] = useState("indeed");
  const [descriptionTab, setDescriptionTab] = useState("indeed");
  const [detailDescriptionTab, setDetailDescriptionTab] = useState("indeed");
  const [descriptionSourceBusy, setDescriptionSourceBusy] = useState(false);
  const [countryCode, setCountryCode] = useState("");
  const [city, setCity] = useState("");
  const [employmentType, setEmploymentType] = useState("");
  const [publicSlug, setPublicSlug] = useState("");
  const [evaluationProfile, setEvaluationProfile] = useState(null);
  const [editingJob, setEditingJob] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichmentProposal, setEnrichmentProposal] = useState(null);
  const [enrichmentError, setEnrichmentError] = useState("");

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
  const detailsRequestRef = useRef(0);

  const loadJobs = useCallback(async () => {
    try {
      const { data } = await api.get("/jobs/page", {
        params: {
          page,
          page_size: pageSize,
          sort,
          q: query,
        },
      });
      setJobs(Array.isArray(data?.items) ? data.items : []);
      setJobsPage({
        page: Number(data?.page || page),
        page_size: Number(data?.page_size || pageSize),
        total: Number(data?.total || 0),
        total_pages: Number(data?.total_pages || 0),
      });
      setError("");
    } catch (requestError) {
      setJobs([]);
      setJobsPage({ page, page_size: pageSize, total: 0, total_pages: 0 });
      setError(requestError.response?.data?.detail || requestError.response?.data?.error || "No fue posible cargar las vacantes.");
    }
  }, [page, pageSize, query, sort]);

  function updateListParams(nextValues) {
    const next = new URLSearchParams(searchParams);
    Object.entries(nextValues).forEach(([key, value]) => {
      if (key === "q" && !String(value || "").trim()) next.delete(key);
      else next.set(key, String(value));
    });
    setSearchParams(next, { replace: true });
  }

  function submitJobSearch(event) {
    event.preventDefault();
    updateListParams({ page: 1, q: jobSearch.trim() });
  }

  function clearJobSearch() {
    setJobSearch("");
    updateListParams({ page: 1, q: "" });
  }

  function goToPage(nextPage) {
    if (nextPage < 1 || nextPage > Math.max(jobsPage.total_pages, 1) || nextPage === page) return;
    updateListParams({ page: nextPage });
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
    loadJobs();
  }, [loadJobs]);

  useEffect(() => {
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
    detailsRequestRef.current += 1;
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
        closeJobDetails();
      }
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [closeJobDetails, deleteJobTarget, deletingJob, viewJob]);

  async function refreshIndeedJobStatus(job = viewJob, requestId = null) {
    if (!job || !indeedIntegration?.enabled || !indeedIntegration?.configured) return;
    if (requestId == null || requestId === detailsRequestRef.current) {
      setIndeedError("");
    }
    try {
      const { data } = await api.get(`/jobs/${job.job_id}/integrations/indeed/status`);
      if (requestId != null && requestId !== detailsRequestRef.current) return;
      setIndeedJobStatus(data);
    } catch (requestError) {
      if (requestId != null && requestId !== detailsRequestRef.current) return;
      if (requestError.response?.status === 404) {
        setIndeedJobStatus({ unpublished: true });
        return;
      }
      setIndeedError(requestError.response?.data?.detail || "No fue posible consultar Indeed.");
    }
  }

  async function openJobDetails(job) {
    const requestId = detailsRequestRef.current + 1;
    detailsRequestRef.current = requestId;

    if (deleteJobTarget) {
      setDeleteJobTarget(null);
      setDeleteError("");
    }
    setViewJob(job);
    setDetailDescriptionTab(job.active_description_source || (job.ai_description ? "ai" : "indeed"));
    setJobCandidates([]);
    setJobCandidatesError("");
    setIndeedJobStatus(null);
    setIndeedError("");
    setJobCandidatesLoading(true);
    try {
      const all = await loadAllJobCandidates(job.job_id);
      if (requestId !== detailsRequestRef.current) return;
      setJobCandidates(all);
    } catch {
      if (requestId !== detailsRequestRef.current) return;
      setJobCandidatesError("No fue posible cargar los candidatos de esta vacante.");
    } finally {
      if (requestId === detailsRequestRef.current) {
        setJobCandidatesLoading(false);
      }
    }
    if (requestId === detailsRequestRef.current) {
      await refreshIndeedJobStatus(job, requestId);
    }
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

  async function enrichJobDraft() {
    if (enriching || !title.trim()) return;
    setEnriching(true);
    setEnrichmentError("");
    setEnrichmentProposal(null);
    try {
      const { data } = await api.post("/jobs/enrich", {
        title,
        description: activeDescription || null,
        country_code: countryCode || null,
        city: city || null,
        employment_type: employmentType || null,
        evaluation_profile: evaluationProfile,
      });
      setEnrichmentProposal(data?.proposal || null);
    } catch (requestError) {
      setEnrichmentError(
        requestError.response?.data?.detail ||
        "No fue posible enriquecer la vacante. Puedes continuar con tu borrador."
      );
    } finally {
      setEnriching(false);
    }
  }

  function applyEnrichmentProposal() {
    if (!enrichmentProposal) return;
    const profile = { ...enrichmentProposal };
    delete profile.improved_description;
    const generatedDescription = (
      formatEnrichmentProposalDescription(enrichmentProposal, activeDescription)
      || activeDescription
    );
    setAiDescription(generatedDescription);
    setActiveDescriptionSource("ai");
    setDescriptionTab("ai");
    setEvaluationProfile(profile);
    setEnrichmentProposal(null);
    setEnrichmentError("");
  }

  function discardEnrichmentProposal() {
    setEnrichmentProposal(null);
    setEnrichmentError("");
  }

  async function saveJob(event) {
    event.preventDefault();
    setError("");
    if (!String(activeDescription || "").trim()) {
      setError("La descripción activa debe tener contenido antes de guardar.");
      return;
    }
    setSaving(true);
    const payload = {
      title,
      description: activeDescription,
      indeed_description: indeedDescription,
      ai_description: aiDescription,
      active_description_source: activeDescriptionSource,
      country_code: countryCode,
      city,
      employment_type: employmentType,
      public_slug: publicSlug,
      evaluation_profile: evaluationProfile,
    };
    try {
      if (editingJob) {
        const { data } = await api.put(`/jobs/${editingJob}`, payload);
        if (data?.reevaluation_scheduled) {
          setSuccessMessage(
            `Perfil actualizado · reevaluación de ${data.reevaluation_candidate_count || 0} candidatos pendiente`
          );
        } else {
          setSuccessMessage("Vacante actualizada.");
        }
      } else {
        await api.post("/jobs", payload);
        setSuccessMessage("Vacante creada.");
      }
      cancelForm();
      await loadJobs();
      setTimeout(() => setSuccessMessage(""), 5000);
    } catch (requestError) {
      setError(requestError.response?.data?.detail || requestError.response?.data?.error || "No fue posible guardar la vacante.");
    } finally {
      setSaving(false);
    }
  }

  function editJob(job) {
    setEditingJob(job.job_id);
    setTitle(job.title);
    const source = job.active_description_source || (job.ai_description ? "ai" : "indeed");
    const originalDescription = (
      job.indeed_description
      ?? (source === "indeed" ? (job.description || "") : "")
    );
    const generatedDescription = (
      job.ai_description
      ?? (source === "ai" ? (job.description || "") : "")
    );
    setIndeedDescription(originalDescription);
    setAiDescription(generatedDescription);
    setActiveDescriptionSource(source);
    setDescriptionTab(source);
    setCountryCode(job.country_code || "");
    setCity(job.city || "");
    setEmploymentType(job.employment_type || "");
    setPublicSlug(job.public_slug || "");
    setEvaluationProfile(job.evaluation_profile || null);
    setEnrichmentProposal(null);
    setEnrichmentError("");
    setError("");
    setShowForm(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function resetJobFields() {
    setTitle("");
    setIndeedDescription("");
    setAiDescription("");
    setActiveDescriptionSource("indeed");
    setDescriptionTab("indeed");
    setDetailDescriptionTab("indeed");
    setCountryCode("");
    setCity("");
    setEmploymentType("");
    setPublicSlug("");
    setEvaluationProfile(null);
    setEnrichmentProposal(null);
    setEnrichmentError("");
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

  const description = descriptionTab === "ai" ? aiDescription : indeedDescription;
  const activeDescription = activeDescriptionSource === "ai" ? aiDescription : indeedDescription;

  function updateVisibleDescription(value) {
    if (descriptionTab === "ai") setAiDescription(value);
    else setIndeedDescription(value);
  }

  async function activateDescriptionSource(source) {
    if (!viewJob || descriptionSourceBusy) return;
    const sourceDescription = source === "ai"
      ? (viewJob.ai_description ?? (viewJob.active_description_source === "ai" ? viewJob.description : null))
      : (viewJob.indeed_description ?? (viewJob.active_description_source !== "ai" ? viewJob.description : null));
    if (!String(sourceDescription || "").trim()) return;

    setDescriptionSourceBusy(true);
    setError("");
    try {
      const { data } = await api.put(`/jobs/${viewJob.job_id}`, {
        active_description_source: source,
      });
      const merged = {
        ...viewJob,
        ...data,
        candidate_count: viewJob.candidate_count,
      };
      setViewJob(merged);
      setJobs((current) => current.map((job) => (
        job.job_id === merged.job_id ? { ...job, ...merged } : job
      )));
      if (data?.reevaluation_scheduled) {
        setSuccessMessage(
          `Descripción activa actualizada · reevaluación de ${data.reevaluation_candidate_count || 0} candidatos pendiente`
        );
      } else {
        setSuccessMessage(`Descripción activa: ${source === "ai" ? "Optimizada por IA" : "Original de Indeed"}.`);
      }
      setTimeout(() => setSuccessMessage(""), 5000);
    } catch (requestError) {
      setError(requestError.response?.data?.detail || "No fue posible cambiar la descripción activa.");
    } finally {
      setDescriptionSourceBusy(false);
    }
  }

  const indeedReady = !!(indeedIntegration?.enabled && indeedIntegration?.configured);
  const lifecycle = indeedLifecycle(indeedJobStatus);
  const indeedPublished = !!(indeedJobStatus?.sourced_posting_id && !indeedJobStatus?.unpublished);
  const editingJobData = editingJob ? jobs.find((job) => job.job_id === editingJob) : null;
  const pageStart = jobsPage.total ? ((page - 1) * pageSize) + 1 : 0;
  const pageEnd = jobsPage.total ? Math.min(page * pageSize, jobsPage.total) : 0;
  const visiblePages = compactPageNumbers(jobsPage.total_pages, page);

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
            <section className="job-description-editor" aria-label="Versiones de la descripción">
              <div className="job-description-source-header">
                <div>
                  <strong>Descripción utilizada por AI Recruiter</strong>
                  <p className="muted">Elige qué versión usa el ranking y la evaluación. Ver una pestaña no cambia la versión activa.</p>
                </div>
                <div className="job-description-source-picker" role="radiogroup" aria-label="Descripción activa">
                  <button
                    type="button"
                    role="radio"
                    aria-checked={activeDescriptionSource === "indeed"}
                    className={`job-source-option ${activeDescriptionSource === "indeed" ? "is-active" : ""}`}
                    onClick={() => setActiveDescriptionSource("indeed")}
                    disabled={!indeedDescription.trim() && activeDescriptionSource !== "indeed"}
                    title={!indeedDescription.trim() && activeDescriptionSource !== "indeed" ? "Escribe primero una descripción original" : undefined}
                  >
                    Original · Indeed
                  </button>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={activeDescriptionSource === "ai"}
                    className={`job-source-option ${activeDescriptionSource === "ai" ? "is-active" : ""}`}
                    onClick={() => setActiveDescriptionSource("ai")}
                    disabled={!aiDescription.trim()}
                    title={!aiDescription.trim() ? "Genera o escribe primero una versión IA" : undefined}
                  >
                    Optimizada · IA
                  </button>
                </div>
              </div>

              <div className="job-description-tabs" role="tablist" aria-label="Ver descripción">
                <button type="button" role="tab" aria-selected={descriptionTab === "indeed"} className={descriptionTab === "indeed" ? "is-active" : ""} onClick={() => setDescriptionTab("indeed")}>Original · Indeed</button>
                <button type="button" role="tab" aria-selected={descriptionTab === "ai"} className={descriptionTab === "ai" ? "is-active" : ""} onClick={() => setDescriptionTab("ai")}>Optimizada · IA</button>
              </div>

              <div className="form-group job-description-field">
                <div className="job-description-field-heading">
                  <label htmlFor="job-description">Descripción y requisitos</label>
                  {descriptionTab === activeDescriptionSource && <span className="badge badge-success">ACTIVA</span>}
                </div>
                <textarea
                  id="job-description"
                  placeholder={descriptionTab === "ai" ? "Genera una propuesta con IA o escribe una versión optimizada…" : "Responsabilidades, experiencia, habilidades y criterios de éxito…"}
                  value={description}
                  onChange={(e) => updateVisibleDescription(e.target.value)}
                  required={descriptionTab === activeDescriptionSource}
                />
                <p className="muted job-description-source-help">
                  {descriptionTab === "indeed"
                    ? "La ingesta actualiza únicamente esta versión. La descripción IA se conserva."
                    : "Esta versión es independiente y no se sobrescribe durante nuevas ingestas de Indeed."}
                </p>
              </div>
            </section>

            <div className="job-enrichment-actions">
              <div>
                <strong>¿Quieres ayuda para completar el perfil?</strong>
                <p className="muted">
                  {editingJob
                    ? "La IA usa el contexto de Asiati y los datos actuales. Nada se guarda hasta que pulses Guardar cambios."
                    : "La IA usa el contexto de Asiati y tu borrador. Nada se guarda hasta que crees la vacante."}
                </p>
              </div>
              <button type="button" className="btn btn-secondary" onClick={enrichJobDraft} disabled={enriching || !title.trim()}>{enriching ? "Enriqueciendo…" : "Enriquecer con IA"}</button>
            </div>

            {enrichmentError && <div className="alert alert-error" role="alert"><span>{enrichmentError}</span></div>}

            {enrichmentProposal && (
              <section className="job-enrichment-proposal" aria-label="Propuesta de IA">
                <div className="job-enrichment-heading"><div><span className="eyebrow">Asistente de vacantes</span><h3>Propuesta de IA</h3></div><span className="badge">Revisar antes de aplicar</span></div>
                <p>{enrichmentProposal.improved_description}</p>
                <div className="job-enrichment-grid">
                  <div><strong>Tecnologías requeridas</strong><ul>{(enrichmentProposal.required_technologies || []).map((item) => <li key={`required-${item}`}>{item}</li>)}</ul></div>
                  <div><strong>Tecnologías deseables</strong><ul>{(enrichmentProposal.preferred_technologies || []).map((item) => <li key={`preferred-${item}`}>{item}</li>)}</ul></div>
                  <div><strong>Certificaciones sugeridas</strong><ul>{[...(enrichmentProposal.required_certifications || []), ...(enrichmentProposal.preferred_certifications || [])].map((item) => <li key={`cert-${item}`}>{item}</li>)}</ul></div>
                  <div><strong>Experiencia específica</strong><ul>{(enrichmentProposal.specific_experience || []).map((item) => <li key={`experience-${item}`}>{item}</li>)}</ul></div>
                  <div><strong>Responsabilidades</strong><ul>{(enrichmentProposal.responsibilities || []).map((item) => <li key={`responsibility-${item}`}>{item}</li>)}</ul></div>
                  <div><strong>Preguntas por validar</strong><ul>{(enrichmentProposal.assumptions_to_validate || []).map((item) => <li key={`assumption-${item}`}>{item}</li>)}</ul></div>
                </div>
                <div className="form-actions"><button type="button" className="btn btn-ghost" onClick={discardEnrichmentProposal}>Descartar</button><button type="button" className="btn btn-secondary" aria-label="Aplicar propuesta · Guardar como versión IA" onClick={applyEnrichmentProposal}>Guardar como versión IA</button></div>
              </section>
            )}

            <div className="job-publication-grid">
              <div className="form-group"><label htmlFor="job-country">País (ISO)</label><input id="job-country" maxLength={2} placeholder="CO" value={countryCode} onChange={(e) => setCountryCode(e.target.value.toUpperCase())} /></div>
              <div className="form-group"><label htmlFor="job-city">Ciudad</label><input id="job-city" placeholder="Bogotá" value={city} onChange={(e) => setCity(e.target.value)} /></div>
              <div className="form-group"><label htmlFor="job-employment">Tipo de empleo</label><select id="job-employment" value={employmentType} onChange={(e) => setEmploymentType(e.target.value)}><option value="">Sin definir</option><option value="FULL_TIME">Tiempo completo</option><option value="PART_TIME">Medio tiempo</option><option value="CONTRACT">Contrato</option><option value="TEMPORARY">Temporal</option><option value="INTERNSHIP">Prácticas</option></select></div>
              <div className="form-group"><label htmlFor="job-slug">URL pública</label><input id="job-slug" placeholder="country-manager-chile" value={publicSlug} onChange={(e) => setPublicSlug(e.target.value)} /></div>
            </div>
            <p className="muted job-publication-hint">Estos datos permiten publicar la misma vacante en asiaticorp.com/jobs e Indeed sin duplicarla.</p>

            {editingJob && (editingJobData?.candidate_count || 0) > 0 && (
              <div className="job-reevaluation-note" role="note">
                <strong>Esta vacante tiene candidatos evaluados.</strong>
                <span>Los cambios en el perfil harán que sus evaluaciones se actualicen automáticamente.</span>
              </div>
            )}

            <div className="form-actions"><button type="button" className="btn btn-ghost" onClick={cancelForm}>Cancelar</button><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Guardando…" : editingJob ? "Guardar cambios" : "Crear vacante"}<span aria-hidden="true">→</span></button></div>
          </form>
        </section>
      )}

      <section className="jobs-section">
        <div className="section-heading"><div><h2>Posiciones registradas</h2><p>{jobsPage.total} {jobsPage.total === 1 ? "vacante activa" : "vacantes activas"}</p></div></div>

        <div className="jobs-list-toolbar">
          <form className="jobs-search" onSubmit={submitJobSearch}>
            <label className="jobs-filter jobs-search-filter">
              <span>Buscar vacante</span>
              <input
                aria-label="Buscar vacante"
                type="search"
                placeholder="Título de la vacante"
                value={jobSearch}
                onChange={(event) => setJobSearch(event.target.value)}
              />
            </label>
            <button type="submit" className="btn btn-secondary">Buscar</button>
            {query && <button type="button" className="btn btn-ghost" onClick={clearJobSearch}>Limpiar</button>}
          </form>

          <div className="jobs-list-filters">
            <label className="jobs-filter">
              <span>Ordenar por</span>
              <select
                aria-label="Ordenar por"
                value={sort}
                onChange={(event) => updateListParams({ page: 1, sort: event.target.value })}
              >
                <option value="created_desc">Más recientes</option>
                <option value="created_asc">Más antiguas</option>
                <option value="candidates_desc">Más candidatos</option>
                <option value="candidates_asc">Menos candidatos</option>
              </select>
            </label>
            <label className="jobs-filter">
              <span>Vacantes por página</span>
              <select
                aria-label="Vacantes por página"
                value={String(pageSize)}
                onChange={(event) => updateListParams({ page: 1, page_size: event.target.value })}
              >
                {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size}</option>)}
              </select>
            </label>
          </div>
        </div>

        <div className="jobs-page-meta">
          <span>Mostrando {pageStart}–{pageEnd} de {jobsPage.total} vacantes</span>
        </div>

        {jobs.length === 0 ? (
          <div className="empty-state">
            <span aria-hidden="true">▤</span>
            <strong>{query ? "No encontramos vacantes con ese filtro" : "Tu tablero de vacantes está vacío"}</strong>
            <p>{query ? "Prueba otro título o limpia la búsqueda." : "Crea una posición para comenzar a comparar candidatos."}</p>
            {query
              ? <button className="btn btn-secondary" type="button" onClick={clearJobSearch}>Limpiar búsqueda</button>
              : <button className="btn btn-secondary" onClick={() => setShowForm(true)}>Crear primera vacante</button>}
          </div>
        ) : (
          <div className="jobs-grid">
            {jobs.map((job) => (
              <article className="job-card" key={job.job_id}>
                <div className="job-card-top"><span className="job-card-icon" aria-hidden="true">▤</span><span className="status-pill"><i /> Activa</span></div>
                <h3>{job.title}</h3><p>{job.description}</p>
                <p className="job-description-source-meta">
                  Descripción activa: <strong>{job.active_description_source === "ai" ? "IA" : "Indeed"}</strong>
                </p>
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

        {jobsPage.total_pages > 1 && (
          <nav className="jobs-pagination" aria-label="Paginación de vacantes">
            <button
              type="button"
              className="jobs-page-button jobs-page-edge"
              disabled={page <= 1}
              onClick={() => goToPage(page - 1)}
            >
              ‹ Anterior
            </button>
            <div className="jobs-page-numbers">
              {visiblePages.map((pageNumber, index) => {
                const previous = visiblePages[index - 1];
                return (
                  <React.Fragment key={pageNumber}>
                    {previous && pageNumber - previous > 1 && <span className="jobs-page-ellipsis" aria-hidden="true">…</span>}
                    <button
                      type="button"
                      className={`jobs-page-button ${pageNumber === page ? "is-active" : ""}`}
                      aria-current={pageNumber === page ? "page" : undefined}
                      aria-label={`Página ${pageNumber}`}
                      onClick={() => goToPage(pageNumber)}
                    >
                      {pageNumber}
                    </button>
                  </React.Fragment>
                );
              })}
            </div>
            <button
              type="button"
              className="jobs-page-button jobs-page-edge"
              disabled={page >= jobsPage.total_pages}
              onClick={() => goToPage(page + 1)}
            >
              Siguiente ›
            </button>
          </nav>
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
              <div className="job-detail-description-heading">
                <div>
                  <h3>Descripción y requisitos</h3>
                  <p className="muted">La pestaña visible y la descripción usada por el sistema son controles independientes.</p>
                </div>
                <span className="badge badge-success">
                  Activa: {viewJob.active_description_source === "ai" ? "IA" : "Indeed"}
                </span>
              </div>

              <div className="job-description-tabs" role="tablist" aria-label="Versiones de la descripción de la vacante">
                <button type="button" role="tab" aria-selected={detailDescriptionTab === "indeed"} className={detailDescriptionTab === "indeed" ? "is-active" : ""} onClick={() => setDetailDescriptionTab("indeed")}>Original · Indeed</button>
                <button type="button" role="tab" aria-selected={detailDescriptionTab === "ai"} className={detailDescriptionTab === "ai" ? "is-active" : ""} onClick={() => setDetailDescriptionTab("ai")}>Optimizada · IA</button>
              </div>

              {(() => {
                const source = viewJob.active_description_source || (viewJob.ai_description ? "ai" : "indeed");
                const original = viewJob.indeed_description ?? (source === "indeed" ? viewJob.description : null);
                const generated = viewJob.ai_description ?? (source === "ai" ? viewJob.description : null);
                const visibleDescription = detailDescriptionTab === "ai" ? generated : original;
                const hasAnyDescription = Boolean(String(original || generated || "").trim());
                const canActivate = Boolean(String(visibleDescription || "").trim()) && detailDescriptionTab !== source;
                return (
                  <>
                    <p className="job-detail-description">
                      {visibleDescription || (hasAnyDescription ? "Esta versión aún no tiene contenido." : "Sin descripción.")}
                    </p>
                    <div className="job-description-detail-actions">
                      {canActivate && (
                        <button type="button" className="btn btn-secondary" disabled={descriptionSourceBusy} onClick={() => activateDescriptionSource(detailDescriptionTab)}>
                          {descriptionSourceBusy ? "Actualizando…" : "Usar esta descripción"}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => {
                          const job = viewJob;
                          closeJobDetails();
                          editJob(job);
                          setDescriptionTab(detailDescriptionTab);
                        }}
                      >
                        {hasAnyDescription ? "Editar versiones" : "Editar y enriquecer"}
                      </button>
                    </div>
                  </>
                );
              })()}
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
