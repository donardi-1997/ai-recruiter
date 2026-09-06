// eslint-disable-next-line no-unused-vars
import React from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import api from "../api/client";
import "./Ranking.css";

function Ranking() {
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState("");
  const [ranking, setRanking] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [requirements, setRequirements] = useState([]);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [requirementsLoading, setRequirementsLoading] = useState(false);

  const [minScore, setMinScore] = useState(0);
  const [maxScore, setMaxScore] = useState(100);
  const [recommendationFilter, setRecommendationFilter] = useState("");
  const [rankingScope, setRankingScope] = useState("assigned");

  const [rankingGeneratedAt, setRankingGeneratedAt] = useState(null);
  const [rankingVersion, setRankingVersion] = useState(null);
  const [isEvaluatingCandidates, setIsEvaluatingCandidates] = useState(false);
  const [isRefreshingRanking, setIsRefreshingRanking] = useState(false);
  const [isRecalculating, setIsRecalculating] = useState(false);
  const [actionFeedback, setActionFeedback] = useState(null);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalPages, setTotalPages] = useState(0);
  const [rankingBaseTotal, setRankingBaseTotal] = useState(0);
  const [rankingLoadedScope, setRankingLoadedScope] = useState(null);
  const [rankingMessage, setRankingMessage] = useState("");

  const [rankingInfo, setRankingInfo] = useState({
    total: 0,
    pending: 0,
    minimum: 0,
    maximum: 0,
  });

  const hasRanking =
    rankingVersion != null &&
    rankingLoadedScope === rankingScope &&
    rankingBaseTotal > 0;

  const evaluatedCount = Math.max(rankingInfo.total - rankingInfo.pending, 0);

  const rankingActionBusy =
    isEvaluatingCandidates || isRefreshingRanking || isRecalculating;

  // ============================================================
  // LOAD JOBS
  // ============================================================

  async function loadJobs() {
    try {
      const response = await api.get("/jobs");
      const data = response.data;
      const loadedJobs = Array.isArray(data) ? data : data.jobs || [];
      setJobs(loadedJobs);

      if (!selectedJob && loadedJobs.length > 0) {
        const firstJobId = loadedJobs[0].job_id;
        setSelectedJob(firstJobId);
        await loadRanking(1, pageSize, firstJobId, rankingScope);
      }
    } catch (error) {
      console.error("ERROR LOADING JOBS:", error.response?.data || error);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ============================================================
  // LOAD RANKING
  // ============================================================

  async function loadRanking(
    targetPage = page,
    targetPageSize = pageSize,
    targetJob = selectedJob,
    targetScope = rankingScope,
  ) {
    if (!targetJob) return false;

    if (minScore < 0 || minScore > 100) {
      alert("El puntaje mínimo debe estar entre 0 y 100");
      return false;
    }
    if (maxScore < 0 || maxScore > 100) {
      alert("El puntaje máximo debe estar entre 0 y 100");
      return false;
    }
    if (minScore > maxScore) {
      alert("El puntaje mínimo no puede ser mayor que el puntaje máximo");
      return false;
    }

    try {
      setLoading(true);
      const params = {
        min_score: minScore,
        max_score: maxScore,
        page: targetPage,
        page_size: targetPageSize,
        scope: targetScope,
      };
      if (recommendationFilter) params.recommendation = recommendationFilter;

      const response = await api.get(`/jobs/${targetJob}/ranking`, { params });
      const data = response.data;
      const candidates = data.candidates || data.ranking || data.items || [];

      setRanking(candidates);
      setRankingGeneratedAt(data.ranking_generated_at || null);
      setRankingVersion(data.ranking_version ?? null);
      setRankingLoadedScope(data.ranking_scope ?? targetScope);
      setRankingBaseTotal(data.ranking_total ?? data.total ?? candidates.length);
      setPage(data.page ?? targetPage);
      setTotalPages(data.total_pages ?? 0);

      const completedCandidates = candidates.filter(
        (c) => c.status === "COMPLETED" && c.match_score != null,
      );
      const visibleScores = completedCandidates.map((c) => Number(c.match_score));

      setRankingInfo({
        total: data.total ?? candidates.length,
        pending: data.pending_candidates ?? 0,
        minimum:
          data.score_min ??
          (visibleScores.length > 0 ? Math.min(...visibleScores) : null),
        maximum:
          data.score_max ??
          (visibleScores.length > 0 ? Math.max(...visibleScores) : null),
      });

      if (candidates.length > 0) setRankingMessage("");
      return true;
    } catch (error) {
      console.error("ERROR LOADING RANKING:", error.response?.data || error);
      alert(error.response?.data?.detail || "No fue posible cargar el ranking");
      return false;
    } finally {
      setLoading(false);
    }
  }

  // ============================================================
  // EVALUAR CANDIDATOS
  // ============================================================

  async function evaluateCandidates() {
    if (!selectedJob) {
      alert("Seleccione una vacante");
      return;
    }

    if (isEvaluatingCandidates || isRefreshingRanking || isRecalculating) {
      return;
    }

    try {
      setIsEvaluatingCandidates(true);
      setActionFeedback(null);
      setRankingMessage("");

      const response = await api.post(
        `/jobs/${selectedJob}/ranking/recalculate`,
        null,
        {
          params: {
            mode: "incremental",
            scope: "assigned",
          },
        },
      );

      const result = response.data;

      setPage(1);
      await loadRanking(1, pageSize, selectedJob, rankingScope);

      if (result.total_candidates === 0) {
        setActionFeedback({
          type: "info",
          message: "No hay candidatos asignados a esta vacante.",
        });
      } else if (result.failed > 0) {
        setActionFeedback({
          type: "error",
          message: `Evaluación completada: ${result.evaluated} candidatos procesados y ${result.failed} con error.`,
        });
      } else {
        setActionFeedback({
          type: "success",
          message: `Evaluación completada: ${result.evaluated} candidatos procesados.`,
        });
      }
    } catch (error) {
      console.error(
        "ERROR EVALUATING CANDIDATES:",
        error.response?.data || error,
      );
      setActionFeedback({
        type: "error",
        message:
          error.response?.data?.detail ||
          "No fue posible evaluar los candidatos. Intenta nuevamente.",
      });
    } finally {
      setIsEvaluatingCandidates(false);
    }
  }

  // ============================================================
  // ACTUALIZAR RANKING
  // ============================================================

  // Refresh only: GET current persisted ranking.
  // This action must never call the LLM or Bedrock.
  async function refreshRanking() {
    if (!selectedJob) {
      alert("Seleccione una vacante");
      return;
    }

    if (isEvaluatingCandidates || isRefreshingRanking || isRecalculating) {
      return;
    }

    try {
      setIsRefreshingRanking(true);
      setActionFeedback(null);
      setRankingMessage("");
      setPage(1);

      const refreshed = await loadRanking(
        1,
        pageSize,
        selectedJob,
        rankingScope,
      );

      if (refreshed) {
        setActionFeedback({
          type: "success",
          message: "Ranking actualizado.",
        });
      }
    } catch (error) {
      console.error(
        "ERROR REFRESHING RANKING:",
        error.response?.data || error,
      );
      setActionFeedback({
        type: "error",
        message:
          error.response?.data?.detail ||
          "No fue posible actualizar el ranking.",
      });
    } finally {
      setIsRefreshingRanking(false);
    }
  }

  // ============================================================
  // RECALCULAR RANKING
  // ============================================================

  // Full recalculation forces evaluation of all assigned
  // candidates and therefore may invoke Bedrock/LLM.
  async function recalculateRanking() {
    if (!selectedJob) {
      alert("Seleccione una vacante");
      return;
    }

    if (isEvaluatingCandidates || isRefreshingRanking || isRecalculating) {
      return;
    }

    const confirmed = window.confirm(
      "Se volverán a evaluar todos los candidatos asignados a esta vacante y se reconstruirá el ranking. Esta operación puede tardar y consumir recursos de IA. ¿Deseas continuar?",
    );

    if (!confirmed) {
      return;
    }

    try {
      setIsRecalculating(true);
      setActionFeedback(null);
      setRankingMessage("");

      const response = await api.post(
        `/jobs/${selectedJob}/ranking/recalculate`,
        null,
        {
          params: {
            mode: "full",
            scope: "assigned",
          },
        },
      );

      const result = response.data;

      setPage(1);
      await loadRanking(1, pageSize, selectedJob, rankingScope);

      if (result.failed > 0) {
        setActionFeedback({
          type: "error",
          message: `Ranking recalculado, pero ${result.failed} candidato(s) no pudieron evaluarse.`,
        });
      } else {
        setActionFeedback({
          type: "success",
          message: "Ranking recalculado correctamente.",
        });
      }
    } catch (error) {
      console.error(
        "ERROR RECALCULATING RANKING:",
        error.response?.data || error,
      );
      setActionFeedback({
        type: "error",
        message:
          error.response?.data?.detail ||
          "No fue posible recalcular el ranking. Intenta nuevamente.",
      });
    } finally {
      setIsRecalculating(false);
    }
  }

  // ============================================================
  // PAGINATION / FILTERS
  // ============================================================

  async function changePage(nextPage) {
    if (nextPage < 1 || nextPage > totalPages || nextPage === page) return;
    setPage(nextPage);
    await loadRanking(nextPage, pageSize);
  }

  async function changePageSize(event) {
    const nextPageSize = Number(event.target.value);
    setPageSize(nextPageSize);
    setPage(1);
    await loadRanking(1, nextPageSize);
  }

  async function applyFilters() {
    setPage(1);
    await loadRanking(1, pageSize);
  }

  async function handleJobChange(event) {
    const nextJob = event.target.value;
    setSelectedJob(nextJob);
    setPage(1);
    setRankingMessage("");
    setActionFeedback(null);

    if (!nextJob) {
      setRanking([]);
      setRankingGeneratedAt(null);
      setRankingVersion(null);
      setRankingLoadedScope(null);
      setRankingBaseTotal(0);
      setTotalPages(0);
      setRankingInfo({ total: 0, pending: 0, minimum: 0, maximum: 0 });
      return;
    }

    await loadRanking(1, pageSize, nextJob, rankingScope);
  }

  async function handleScopeChange(event) {
    const nextScope = event.target.value;
    setRankingScope(nextScope);
    setPage(1);
    setRankingMessage("");
    if (!selectedJob) return;
    await loadRanking(1, pageSize, selectedJob, nextScope);
  }

  // ============================================================
  // ANALYSIS MODAL
  // ============================================================

  async function openAnalysis(candidate) {
    setSelectedCandidate(candidate);
    setAnalysis(null);
    setRequirements([]);

    try {
      setAnalysisLoading(true);
      const analysisResponse = await api.get(
        `/jobs/${selectedJob}/candidates/${candidate.candidate_id}/explanation`,
      );
      setAnalysis(analysisResponse.data);
    } catch (error) {
      console.error("ERROR ANALYSIS:", error.response?.data || error);
    } finally {
      setAnalysisLoading(false);
    }

    try {
      setRequirementsLoading(true);
      const requirementsResponse = await api.get(
        `/jobs/${selectedJob}/candidates/${candidate.candidate_id}/requirements`,
      );
      setRequirements(requirementsResponse.data.requirements || []);
    } catch (error) {
      console.error("ERROR REQUIREMENTS:", error.response?.data || error);
    } finally {
      setRequirementsLoading(false);
    }
  }

  function closeModal() {
    setSelectedCandidate(null);
    setAnalysis(null);
    setRequirements([]);
  }

  // ============================================================
  // HELPERS
  // ============================================================

  function getRecommendationLabel(recommendation) {
    if (recommendation === "STRONG_MATCH") return "Excelente coincidencia";
    if (recommendation === "GOOD_MATCH") return "Buena coincidencia";
    if (recommendation === "PARTIAL_MATCH") return "Coincidencia parcial";
    if (recommendation === "LOW_MATCH") return "Baja coincidencia";
    if (recommendation === "EVALUATION_FAILED") return "Evaluación fallida";
    if (recommendation === "PENDING") return "Pendiente";
    return "Sin clasificación";
  }

  function getRecommendationClass(recommendation) {
    if (recommendation === "STRONG_MATCH") return "ranking-badge--strong";
    if (recommendation === "GOOD_MATCH") return "ranking-badge--good";
    if (recommendation === "PARTIAL_MATCH") return "ranking-badge--partial";
    if (recommendation === "LOW_MATCH") return "ranking-badge--low";
    if (recommendation === "EVALUATION_FAILED") return "ranking-badge--failed";
    if (recommendation === "PENDING") return "ranking-badge--pending";
    return "ranking-badge--low";
  }

  function getRequirementLabel(status) {
    if (status === "MATCH") return "Cumple";
    if (status === "PARTIAL") return "Cumple parcialmente";
    if (status === "MISSING") return "No cumple";
    return status || "Sin evaluar";
  }

  function getRequirementClass(status) {
    if (status === "MATCH") return "ranking-badge--strong";
    if (status === "PARTIAL") return "ranking-badge--partial";
    return "ranking-badge--failed";
  }

  // ============================================================
  // RENDER
  // ============================================================

  return (
    <div className="page ranking-page">

      {/* 1. HEADER */}
      <header className="ranking-header">
        <div className="ranking-header-text">
          <span className="eyebrow">Decisiones asistidas por IA</span>
          <h1>Ranking de candidatos</h1>
          <p>Compara, evalúa y prioriza candidatos para cada vacante.</p>
        </div>
      </header>

      {/* 2. JOB PANEL + ACTIONS */}
      <div className="ranking-job-panel">
        <div className="ranking-job-panel-left">
          <span className="ranking-job-label">Vacante activa</span>
          <select
            className="ranking-job-select"
            value={selectedJob}
            onChange={handleJobChange}
          >
            <option value="">Seleccione vacante</option>
            {jobs.map((job) => (
              <option key={job.job_id} value={job.job_id}>{job.title}</option>
            ))}
          </select>
          <p className="ranking-job-hint">
            {selectedJob
              ? "Ranking y evaluaciones de esta vacante"
              : "Selecciona una vacante para comenzar"}
          </p>
        </div>
        <div className="ranking-job-panel-right">
          {selectedJob && rankingInfo.pending > 0 && (
            <span className="ranking-pending-badge ranking-pending-badge--warning">
              {rankingInfo.pending} pendiente{rankingInfo.pending === 1 ? "" : "s"}
            </span>
          )}
          {selectedJob && rankingInfo.pending === 0 && rankingInfo.total > 0 && (
            <span className="ranking-pending-badge ranking-pending-badge--success">
              Evaluaciones al día
            </span>
          )}
          <div className="ranking-job-actions">
            <button
              className="btn btn-primary"
              onClick={evaluateCandidates}
              disabled={!selectedJob || loading || rankingActionBusy}
              title="Procesa candidatos pendientes de esta vacante."
            >
              {isEvaluatingCandidates && <span className="ranking-spinner" />}
              {isEvaluatingCandidates ? "Evaluando candidatos..." : "Evaluar candidatos"}
            </button>
            <button
              className="btn btn-secondary"
              onClick={refreshRanking}
              disabled={!selectedJob || loading || rankingActionBusy}
              title="Actualiza la información mostrada sin volver a evaluar."
            >
              {isRefreshingRanking && <span className="ranking-spinner" />}
              {isRefreshingRanking ? "Actualizando ranking..." : "Actualizar ranking"}
            </button>
            <button
              className="btn ranking-btn-recalculate"
              onClick={recalculateRanking}
              disabled={!selectedJob || loading || rankingActionBusy}
              title="Vuelve a evaluar todos los candidatos de esta vacante."
            >
              {isRecalculating && <span className="ranking-spinner" />}
              {isRecalculating ? "Recalculando ranking..." : "Recalcular ranking"}
            </button>
          </div>
        </div>
      </div>

      {/* 3. METRICS */}
      {selectedJob && rankingInfo.total > 0 && (
        <div className="ranking-metrics">
          <div className="ranking-metric">
            <span className="ranking-metric-label">Candidatos</span>
            <span className="ranking-metric-value">{rankingInfo.total}</span>
          </div>
          <div className="ranking-metric">
            <span className="ranking-metric-label">Evaluados</span>
            <span className="ranking-metric-value">{evaluatedCount}</span>
          </div>
          <div className="ranking-metric">
            <span className="ranking-metric-label">Pendientes</span>
            <span className="ranking-metric-value">{rankingInfo.pending}</span>
          </div>
          <div className="ranking-metric">
            <span className="ranking-metric-label">Rango de puntuación</span>
            <span className="ranking-metric-value">
              {rankingInfo.minimum != null && rankingInfo.maximum != null
                ? `${rankingInfo.minimum}% – ${rankingInfo.maximum}%`
                : "—"}
            </span>
          </div>
        </div>
      )}

      {/* 4. FILTERS */}
      {selectedJob && (
        <div className="ranking-filter-panel">
          <div className="ranking-filter-header">
            <h3>Filtros del ranking</h3>
            <p>Ajusta los resultados sin modificar las evaluaciones.</p>
          </div>
          <div className="ranking-filter-grid">
            <div>
              <label>Fuente de candidatos</label>
              <select value={rankingScope} onChange={handleScopeChange}>
                <option value="assigned">Solo esta vacante</option>
                <option value="all">Todos mis candidatos</option>
              </select>
            </div>
            <div>
              <label>Puntaje mínimo</label>
              <input type="number" min="0" max="100" value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} />
            </div>
            <div>
              <label>Puntaje máximo</label>
              <input type="number" min="0" max="100" value={maxScore} onChange={(e) => setMaxScore(Number(e.target.value))} />
            </div>
            <div>
              <label>Clasificación</label>
              <select value={recommendationFilter} onChange={(e) => setRecommendationFilter(e.target.value)}>
                <option value="">Todas</option>
                <option value="STRONG_MATCH">Excelente coincidencia</option>
                <option value="GOOD_MATCH">Buena coincidencia</option>
                <option value="PARTIAL_MATCH">Coincidencia parcial</option>
                <option value="LOW_MATCH">Baja coincidencia</option>
              </select>
            </div>
            <div className="ranking-filter-actions">
              <button
                className="btn btn-secondary"
                onClick={applyFilters}
                disabled={!hasRanking || loading || rankingActionBusy}
              >
                Aplicar filtros
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 5. FEEDBACK */}
      {actionFeedback && (
        <div className={`ranking-feedback ranking-feedback--${actionFeedback.type}`} role="status" aria-live="polite">
          {actionFeedback.message}
        </div>
      )}

      {/* 6. RANKING METADATA */}
      {selectedJob && (
        <div className="ranking-meta">
          <div className="ranking-meta-info">
            {hasRanking && rankingGeneratedAt
              ? `Último ranking · v${rankingVersion} · ${new Date(rankingGeneratedAt).toLocaleString("es-ES")}`
              : "\u00A0"}
          </div>
        </div>
      )}

      {/* 7. LOADING STATE */}
      {loading && ranking.length === 0 && (
        <div className="ranking-skeleton">
          {[1, 2, 3].map((i) => (
            <div className="ranking-skeleton-card" key={i}>
              <div className="ranking-skeleton-line ranking-skeleton-line--medium" />
              <div className="ranking-skeleton-line ranking-skeleton-line--short" style={{ marginTop: 10 }} />
              <div className="ranking-skeleton-line ranking-skeleton-line--bar" />
            </div>
          ))}
        </div>
      )}

      {/* 8. EMPTY STATES */}
      {!loading && selectedJob && ranking.length === 0 && (
        <div className="ranking-empty">
          <div className="ranking-empty-icon">📋</div>
          {rankingInfo.pending > 0 ? (
            <>
              <h3>Hay candidatos pendientes de evaluación</h3>
              <p>Usa "Evaluar candidatos" para procesar los candidatos asignados a esta vacante.</p>
            </>
          ) : (
            <>
              <h3>No hay candidatos con estos filtros</h3>
              <p>{rankingMessage || "Ajusta los filtros o cambia la fuente de candidatos para ver resultados."}</p>
            </>
          )}
        </div>
      )}

      {/* 9. CANDIDATE LIST */}
      {!loading && ranking.length > 0 && (
        <div className="ranking-candidates">
          {ranking.map((candidate, index) => {
            const isFailed = candidate.status === "FAILED";
            const isPending = candidate.status === "PENDING";
            const position = candidate.position ?? ((page - 1) * pageSize + index + 1);

            return (
              <div key={candidate.candidate_id} className="ranking-candidate-card">
                <div className="ranking-candidate-header">
                  <div className="ranking-candidate-header-left">
                    <span className="ranking-candidate-position">#{position}</span>
                    <span className="ranking-candidate-name">{candidate.candidate_name}</span>
                    <span className="ranking-candidate-status">
                      <span className={`ranking-badge ${getRecommendationClass(candidate.recommendation)}`}>
                        {getRecommendationLabel(candidate.recommendation)}
                      </span>
                    </span>
                  </div>
                  <div className="ranking-candidate-score">
                    {isFailed || isPending ? (
                      <span className={isFailed ? "ranking-candidate-failed" : "ranking-candidate-pending-label"}>
                        {isFailed ? "Evaluación fallida" : "Pendiente de evaluación"}
                      </span>
                    ) : (
                      <span className="ranking-candidate-score-value">{candidate.match_score}%</span>
                    )}
                  </div>
                </div>

                {/* Score bar */}
                {!isFailed && !isPending && (
                  <div className="ranking-score-track">
                    <div className="ranking-score-fill" style={{ width: `${candidate.match_score}%` }} />
                  </div>
                )}

                {/* Strengths */}
                <div className="ranking-chips-section">
                  <span className="ranking-chips-label">Fortalezas</span>
                  {candidate.strengths?.length ? (
                    <div className="ranking-chips">
                      {candidate.strengths.map((item, i) => (
                        <span key={i} className="ranking-chip ranking-strength-chip">{item}</span>
                      ))}
                    </div>
                  ) : (
                    <span className="ranking-chips-empty">Sin fortalezas registradas</span>
                  )}
                </div>

                {/* Gaps */}
                <div className="ranking-chips-section">
                  <span className="ranking-chips-label">Brechas</span>
                  {candidate.gaps?.length ? (
                    <div className="ranking-chips">
                      {candidate.gaps.map((item, i) => (
                        <span key={i} className="ranking-chip ranking-gap-chip">{item}</span>
                      ))}
                    </div>
                  ) : (
                    <span className="ranking-chips-empty">Sin brechas relevantes</span>
                  )}
                </div>

                <button
                  className="btn btn-secondary ranking-analysis-btn"
                  onClick={() => openAnalysis(candidate)}
                >
                  Ver análisis
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* 10. PAGINATION */}
      {rankingInfo.total > 0 && (
        <div className="ranking-pagination">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span>Mostrar</span>
            <select value={pageSize} onChange={changePageSize}>
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <span>por página</span>
          </div>
          <span className="ranking-pagination-info">
            Mostrando {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, rankingInfo.total)} de {rankingInfo.total}
          </span>
          <div className="ranking-pagination-controls">
            <button className="btn btn-secondary" onClick={() => changePage(page - 1)} disabled={page <= 1 || loading}>
              Anterior
            </button>
            <span className="ranking-pagination-page">
              Página {page} de {Math.max(totalPages, 1)}
            </span>
            <button className="btn btn-secondary" onClick={() => changePage(page + 1)} disabled={page >= totalPages || loading}>
              Siguiente
            </button>
          </div>
        </div>
      )}

      {/* ========================================================
          ANALYSIS MODAL
      ======================================================== */}
      {selectedCandidate && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal ranking-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{selectedCandidate.candidate_name}</h2>
              <button className="btn btn-close" onClick={closeModal}>✕</button>
            </div>

            {selectedCandidate.status === "FAILED" || selectedCandidate.status === "PENDING" ? (
              <div style={{ marginTop: 10 }}>
                <h1 style={{ color: "var(--danger)", fontSize: "1.8rem" }}>
                  {selectedCandidate.status === "FAILED" ? "Evaluación fallida" : "Evaluación pendiente"}
                </h1>
                {selectedCandidate.error_message && (
                  <p className="muted" style={{ marginTop: 8 }}>{selectedCandidate.error_message}</p>
                )}
              </div>
            ) : (
              <>
                <span className="ranking-modal-score">{selectedCandidate.match_score}%</span>
                <div style={{ marginTop: 10 }}>
                  <span className={`ranking-badge ${getRecommendationClass(selectedCandidate.recommendation)}`}>
                    {getRecommendationLabel(selectedCandidate.recommendation)}
                  </span>
                </div>
              </>
            )}

            <div className="ranking-modal-section">
              <h3>Fortalezas</h3>
              {selectedCandidate.strengths?.length ? (
                <ul className="ranking-modal-list">
                  {selectedCandidate.strengths.map((item, i) => <li key={i}>{item}</li>)}
                </ul>
              ) : <p className="muted">Sin datos</p>}
            </div>

            <div className="ranking-modal-section">
              <h3>Brechas</h3>
              {selectedCandidate.gaps?.length ? (
                <ul className="ranking-modal-list">
                  {selectedCandidate.gaps.map((item, i) => <li key={i}>{item}</li>)}
                </ul>
              ) : <p className="muted">Sin brechas</p>}
            </div>

            <hr />

            <div className="ranking-modal-section">
              <h3>Requisitos evaluados</h3>
              {requirementsLoading && <p className="muted">Cargando requisitos...</p>}
              {!requirementsLoading && requirements.length === 0 && <p className="muted">No hay requisitos disponibles.</p>}
              {requirements.map((req, i) => (
                <div key={i} className="ranking-modal-requirement">
                  <strong>{req.requirement}</strong>
                  <span className={`ranking-badge ${getRequirementClass(req.status)}`} style={{ marginTop: 6 }}>
                    {getRequirementLabel(req.status)}
                  </span>
                  {req.evidence && <p className="ranking-modal-evidence"><strong>Evidencia:</strong> {req.evidence}</p>}
                </div>
              ))}
            </div>

            <hr />

            <div className="ranking-modal-section">
              <h3>Análisis IA</h3>
              {analysisLoading && <p className="muted">Generando análisis...</p>}
              {analysis && <p style={{ lineHeight: 1.6, color: "var(--ink-soft)" }}>{analysis.explanation || analysis.summary || analysis.analysis}</p>}
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 24 }}>
              <button className="btn btn-ghost" onClick={closeModal}>Cerrar</button>
              <Link className="btn btn-primary" to={`/candidates/${selectedCandidate.candidate_id}?job_id=${selectedJob}`}>
                Abrir ficha de esta vacante
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Ranking;
