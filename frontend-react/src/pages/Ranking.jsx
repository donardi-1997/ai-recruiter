// eslint-disable-next-line no-unused-vars
import React from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import api from "../api/client";

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

  const [showModeModal, setShowModeModal] = useState(false);

  const [rankingGeneratedAt, setRankingGeneratedAt] = useState(null);

  const [rankingVersion, setRankingVersion] = useState(null);

  const [isRecalculating, setIsRecalculating] = useState(false);

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

  // ============================================================
  // LOAD JOBS
  // ============================================================

  async function loadJobs() {
    try {
      const response = await api.get("/jobs");

      const data = response.data;

      setJobs(Array.isArray(data) ? data : data.jobs || []);
    } catch (error) {
      console.error("ERROR LOADING JOBS:", error.response?.data || error);
    }
  }

  useEffect(() => {
    // The initial request synchronizes this view with the API.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadJobs();
  }, []);

  useEffect(() => {
    if (!selectedJob && jobs.length > 0) {
      // Select the first owned vacancy so the ranking is visible on entry.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedJob(jobs[0].job_id);
    }
  }, [jobs, selectedJob]);

  // ============================================================
  // LOAD RANKING
  // ============================================================

  async function loadRanking(
    targetPage = page,
    targetPageSize = pageSize,
  ) {
    if (!selectedJob) {
      return;
    }

    if (minScore < 0 || minScore > 100) {
      alert(
        "El puntaje mínimo debe estar entre 0 y 100",
      );
      return;
    }

    if (maxScore < 0 || maxScore > 100) {
      alert(
        "El puntaje máximo debe estar entre 0 y 100",
      );
      return;
    }

    if (minScore > maxScore) {
      alert(
        "El puntaje mínimo no puede ser mayor que el puntaje máximo",
      );
      return;
    }

    try {
      setLoading(true);

      const params = {
        min_score: minScore,
        max_score: maxScore,
        page: targetPage,
        page_size: targetPageSize,
        scope: rankingScope,
      };

      if (recommendationFilter) {
        params.recommendation =
          recommendationFilter;
      }

      const response = await api.get(
        `/jobs/${selectedJob}/ranking`,
        { params },
      );

      console.log(
        "RANKING RESPONSE:",
        response.data,
      );

      const data = response.data;

      const candidates =
        data.candidates ||
        data.ranking ||
        data.items ||
        [];

      setRanking(candidates);

      setRankingGeneratedAt(
        data.ranking_generated_at || null,
      );

      setRankingVersion(
        data.ranking_version ?? null,
      );

      setRankingLoadedScope(
        data.ranking_scope ?? rankingScope,
      );

      setRankingBaseTotal(
        data.ranking_total ??
          data.total ??
          candidates.length,
      );

      setPage(
        data.page ?? targetPage,
      );

      setTotalPages(
        data.total_pages ?? 0,
      );

      const completedCandidates =
        candidates.filter(
          (candidate) =>
            candidate.status === "COMPLETED" &&
            candidate.match_score != null,
        );

      const visibleScores =
        completedCandidates.map(
          (candidate) =>
            Number(candidate.match_score),
        );

      setRankingInfo({
        total:
          data.total ??
          candidates.length,

        pending:
          data.pending_candidates ??
          0,

        minimum:
          data.score_min ??
          (
            visibleScores.length > 0
              ? Math.min(...visibleScores)
              : null
          ),

        maximum:
          data.score_max ??
          (
            visibleScores.length > 0
              ? Math.max(...visibleScores)
              : null
          ),
      });

      if (candidates.length > 0) {
        setRankingMessage("");
      }

    } catch (error) {
      console.error(
        "ERROR LOADING RANKING:",
        error.response?.data || error,
      );

      alert(
        error.response?.data?.detail ||
          "No fue posible cargar el ranking",
      );

    } finally {
      setLoading(false);
    }
  }


  async function viewRanking() {
    if (!selectedJob) {
      alert("Seleccione una vacante");
      return;
    }

    if (isRecalculating) {
      return;
    }

    try {
      setIsRecalculating(true);
      setRankingMessage("");

      const response = await api.post(
        `/jobs/${selectedJob}/ranking/recalculate`,
        null,
        {
          params: {
            mode: "incremental",
            scope: rankingScope,
          },
        },
      );

      const result = response.data;

      await loadRanking(
        1,
        pageSize,
      );

      setPage(1);

      if (
        result.total_candidates === 0
      ) {
        setRankingMessage(
          rankingScope === "assigned"
            ? "No hay candidatos asignados a esta vacante."
            : "No hay candidatos disponibles para evaluar.",
        );
      }

    } catch (error) {
      console.error(
        "ERROR GENERATING RANKING:",
        error.response?.data || error,
      );

      alert(
        error.response?.data?.detail ||
          "No fue posible generar el ranking",
      );

    } finally {
      setIsRecalculating(false);
    }
  }


  async function evaluateRanking() {
    if (!selectedJob) {
      alert("Seleccione una vacante");
      return;
    }

    if (isRecalculating) {
      return;
    }

    try {
      setIsRecalculating(true);
      setRankingMessage("");

      const response = await api.post(
        `/jobs/${selectedJob}/ranking/recalculate`,
        null,
        {
          params: {
            mode: "incremental",
            scope: rankingScope,
          },
        },
      );

      const result = response.data;

      setPage(1);

      await loadRanking(
        1,
        pageSize,
      );

      if (result.total_candidates === 0) {
        setRankingMessage(
          rankingScope === "assigned"
            ? "No hay candidatos asignados a esta vacante."
            : "No hay candidatos disponibles para evaluar.",
        );
      }
    } catch (error) {
      console.error(
        "ERROR EVALUATING RANKING:",
        error.response?.data || error,
      );

      alert(
        error.response?.data?.detail ||
          "No fue posible evaluar el ranking",
      );
    } finally {
      setIsRecalculating(false);
    }
  }


  async function recalculateRanking(mode) {
    if (!selectedJob) {
      alert("Seleccione una vacante");
      return;
    }

    setShowModeModal(false);

    const label =
      mode === "incremental"
        ? "Solo nuevos candidatos"
        : "Recalcular todo";

    if (!window.confirm(`¿${label}?`)) {
      return;
    }

    try {
      setIsRecalculating(true);

      await api.post(
        `/jobs/${selectedJob}/ranking/recalculate`,
        null,
        {
          params: {
            mode,
            scope: rankingScope,
          },
        },
      );

      setPage(1);

      await loadRanking(
        1,
        pageSize,
      );

    } catch (error) {
      alert(
        error.response?.data?.detail ||
          "No fue posible recalcular el ranking",
      );

    } finally {
      setIsRecalculating(false);
    }
  }


  async function changePage(nextPage) {
    if (
      nextPage < 1 ||
      nextPage > totalPages ||
      nextPage === page
    ) {
      return;
    }

    setPage(nextPage);

    await loadRanking(
      nextPage,
      pageSize,
    );
  }


  async function changePageSize(event) {
    const nextPageSize =
      Number(event.target.value);

    setPageSize(nextPageSize);
    setPage(1);

    await loadRanking(
      1,
      nextPageSize,
    );
  }


  async function applyFilters() {
    setPage(1);

    await loadRanking(
      1,
      pageSize,
    );
  }


  useEffect(() => {
    if (selectedJob) {
      setPage(1);
      setRankingMessage("");

      loadRanking(
        1,
        pageSize,
      );
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedJob, rankingScope]);

  // ============================================================
  // OPEN ANALYSIS
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

  // ============================================================
  // CLOSE MODAL
  // ============================================================

  function closeModal() {
    setSelectedCandidate(null);

    setAnalysis(null);

    setRequirements([]);
  }

  // ============================================================
  // RECOMMENDATION LABEL
  // ============================================================

  function getRecommendationLabel(recommendation) {
    if (recommendation === "STRONG_MATCH") {
      return "Excelente coincidencia";
    }

    if (recommendation === "GOOD_MATCH") {
      return "Buena coincidencia";
    }

    if (recommendation === "PARTIAL_MATCH") {
      return "Coincidencia parcial";
    }

    if (recommendation === "LOW_MATCH") {
      return "Baja coincidencia";
    }

    if (recommendation === "EVALUATION_FAILED") {
      return "Evaluación fallida";
    }

    if (recommendation === "PENDING") {
      return "Pendiente";
    }

    return "Sin clasificación";
  }

  // ============================================================
  // BADGE STYLE
  // ============================================================

  function badgeStyle(recommendation) {
    if (recommendation === "STRONG_MATCH") {
      return {
        background: "#dcfce7",
        color: "#166534",
      };
    }

    if (recommendation === "GOOD_MATCH" || recommendation === "PARTIAL_MATCH") {
      return {
        background: "#fef3c7",
        color: "#92400e",
      };
    }

    if (recommendation === "EVALUATION_FAILED") {
      return {
        background: "#fef2f2",
        color: "#991b1b",
        border: "1px solid #fecaca",
      };
    }

    if (recommendation === "PENDING") {
      return {
        background: "#f1f5f9",
        color: "#475569",
      };
    }

    return {
      background: "#fee2e2",
      color: "#991b1b",
    };
  }

  // ============================================================
  // REQUIREMENT STATUS
  // ============================================================

  function getRequirementLabel(status) {
    if (status === "MATCH") {
      return "Cumple";
    }

    if (status === "PARTIAL") {
      return "Cumple parcialmente";
    }

    if (status === "MISSING") {
      return "No cumple";
    }

    return status || "Sin evaluar";
  }

  function getRequirementStyle(status) {
    if (status === "MATCH") {
      return {
        background: "#dcfce7",
        color: "#166534",
      };
    }

    if (status === "PARTIAL") {
      return {
        background: "#fef3c7",
        color: "#92400e",
      };
    }

    return {
      background: "#fee2e2",
      color: "#991b1b",
    };
  }

  // ============================================================
  // RENDER
  // ============================================================

  return (
    <div
      className="page ranking-page"
      style={{
        padding: "40px",
      }}
    >
      <header className="page-header"><span className="eyebrow">Decisiones asistidas por IA</span><h1>Ranking de candidatos</h1><p>Prioriza el talento con mayor afinidad para cada vacante.</p></header>

      {/* ========================================================
          CONTROLES
      ======================================================== */}

      <div
        className="ranking-filters panel"
        style={{
          marginTop: "30px",
          padding: "20px",
          border: "1px solid #ddd",
          borderRadius: "12px",
          background: "#fff",
        }}
      >
        <div
          className="ranking-filter-grid"
          style={{
            display: "flex",
            gap: "15px",
            flexWrap: "wrap",
            alignItems: "end",
          }}
        >
          {/* VACANTE */}

          <div>
            <label
              style={{
                display: "block",
                marginBottom: "6px",
                fontWeight: "600",
              }}
            >
              Vacante
            </label>

            <select
              value={selectedJob}
              onChange={(e) => setSelectedJob(e.target.value)}
              style={{
                padding: "10px",
                minWidth: "250px",
              }}
            >
              <option value="">Seleccione vacante</option>

              {jobs.map((job) => (
                <option key={job.job_id} value={job.job_id}>
                  {job.title}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label style={{ display: "block", marginBottom: "6px", fontWeight: "600" }}>
              Fuente de candidatos
            </label>
            <select value={rankingScope} onChange={(e) => setRankingScope(e.target.value)} style={{ padding: "10px", minWidth: "220px" }}>
              <option value="assigned">Solo esta vacante</option>
              <option value="all">Todos mis candidatos</option>
            </select>
          </div>

          {/* MIN SCORE */}

          <div>
            <label
              style={{
                display: "block",
                marginBottom: "6px",
                fontWeight: "600",
              }}
            >
              Puntaje mínimo
            </label>

            <input
              type="number"
              min="0"
              max="100"
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              style={{
                padding: "10px",
                width: "120px",
              }}
            />
          </div>

          {/* MAX SCORE */}

          <div>
            <label
              style={{
                display: "block",
                marginBottom: "6px",
                fontWeight: "600",
              }}
            >
              Puntaje máximo
            </label>

            <input
              type="number"
              min="0"
              max="100"
              value={maxScore}
              onChange={(e) => setMaxScore(Number(e.target.value))}
              style={{
                padding: "10px",
                width: "120px",
              }}
            />
          </div>

          {/* RECOMMENDATION */}

          <div>
            <label
              style={{
                display: "block",
                marginBottom: "6px",
                fontWeight: "600",
              }}
            >
              Clasificación
            </label>

            <select
              value={recommendationFilter}
              onChange={(e) => setRecommendationFilter(e.target.value)}
              style={{
                padding: "10px",
                minWidth: "190px",
              }}
            >
              <option value="">Todas</option>

              <option value="STRONG_MATCH">Excelente coincidencia</option>

              <option value="GOOD_MATCH">Buena coincidencia</option>

              <option value="PARTIAL_MATCH">Coincidencia parcial</option>

              <option value="LOW_MATCH">Baja coincidencia</option>
            </select>
          </div>

          <button
            className="btn btn-secondary"
            onClick={applyFilters}
            disabled={
              !hasRanking ||
              loading ||
              isRecalculating
            }
            style={{
              padding: "10px 18px",
            }}
          >
            Aplicar filtros
          </button>

          <button
            className="btn btn-secondary"
            onClick={evaluateRanking}
            disabled={
              !selectedJob ||
              loading ||
              isRecalculating
            }
            style={{
              padding: "10px 18px",
              cursor:
                !selectedJob ||
                loading ||
                isRecalculating
                  ? "not-allowed"
                  : "pointer",
            }}
          >
            {isRecalculating
              ? "Evaluando..."
              : "Evaluar ranking"}
          </button>

          {/* BUTTON */}

          <button
            className="btn btn-primary"
            onClick={
              hasRanking
                ? () => setShowModeModal(true)
                : viewRanking
            }
            disabled={
              !selectedJob ||
              loading ||
              isRecalculating
            }
            style={{
              padding: "10px 18px",
              cursor:
                !selectedJob ||
                loading ||
                isRecalculating
                  ? "not-allowed"
                  : "pointer",
            }}
          >
            {loading
              ? "Cargando..."
              : isRecalculating
                ? hasRanking
                  ? "Recalculando..."
                  : "Generando ranking..."
                : hasRanking
                  ? "Actualizar ranking"
                  : "Ver ranking"}
          </button>
        </div>
      </div>

      {selectedJob && rankingInfo.pending > 0 && (
        <p className="muted" style={{ marginTop: "16px" }}>
          {rankingInfo.pending} candidato{rankingInfo.pending === 1 ? "" : "s"} pendiente{rankingInfo.pending === 1 ? "" : "s"} de evaluación.
        </p>
      )}

      {hasRanking && rankingGeneratedAt && (
        <p className="muted" style={{ marginTop: "8px", fontSize: "13px", color: "#64748b" }}>
          Último ranking: v{rankingVersion} — {new Date(rankingGeneratedAt).toLocaleString("es-ES")}
        </p>
      )}

      {/* ========================================================
          SUMMARY
      ======================================================== */}

      {ranking.length > 0 && (
        <div
          className="summary-grid"
          style={{
            display: "flex",
            gap: "20px",
            flexWrap: "wrap",
            marginTop: "25px",
            justifyContent: "center",
          }}
        >
          <SummaryCard title="Candidatos" value={rankingInfo.total} />

          <SummaryCard
            title="Puntaje mínimo"
            value={rankingInfo.minimum != null ? `${rankingInfo.minimum}%` : "—"}
          />

          <SummaryCard
            title="Puntaje máximo"
            value={rankingInfo.maximum != null ? `${rankingInfo.maximum}%` : "—"}
          />
        </div>
      )}

      {/* ========================================================
          RANKING
      ======================================================== */}

      <div
        className="ranking-results"
        style={{
          marginTop: "30px",
        }}
      >
        {!loading && selectedJob && ranking.length === 0 && (
          <div
            className="empty-state"
            style={{
              padding: "25px",
              border: "1px solid #ddd",
              borderRadius: "12px",
            }}
          >
            <p>
              {rankingMessage ||
                (rankingInfo.pending > 0
                  ? "No hay candidatos evaluados para esta vacante."
                  : "No hay candidatos que cumplan con los filtros seleccionados.")}
            </p>
          </div>
        )}

        {ranking.map((candidate, index) => (
          <div
            key={candidate.candidate_id}
            className="ranking-card"
            style={{
              border: "1px solid #ddd",

              padding: "25px",

              marginBottom: "20px",

              borderRadius: "12px",

              boxShadow: "0 2px 8px rgba(0,0,0,0.08)",

              background: "#fff",
            }}
          >
            <h2>
              #{candidate.position ??
                ((page - 1) * pageSize + index + 1)}{" "}
              {candidate.candidate_name}
            </h2>

            <strong>Puntaje de coincidencia</strong>

            {candidate.status === "FAILED" || candidate.status === "PENDING" ? (
              <div style={{ marginTop: "10px" }}>
                <h1 style={{ color: "#991b1b", fontSize: "24px" }}>
                  {candidate.status === "FAILED" ? "Evaluación fallida" : "Evaluación pendiente"}
                </h1>
                {candidate.error_message && (
                  <p style={{ color: "#64748b", fontSize: "13px", marginTop: "5px" }}>
                    {candidate.error_message}
                  </p>
                )}
              </div>
            ) : (
              <>
                <h1>{candidate.match_score}%</h1>

                {/* SCORE BAR */}

                <div
                  className="ranking-score-bar"
                  style={{
                    height: "12px",
                    background: "#eee",
                    borderRadius: "10px",
                    overflow: "hidden",
                  }}
                >
                  <div
                    className="ranking-score-fill"
                    style={{
                      width: `${candidate.match_score}%`,
                      height: "100%",
                      background: "#4f46e5",
                    }}
                  />
                </div>
              </>
            )}

            {/* RECOMMENDATION */}

            <div
              className="ranking-columns"
              style={{
                display: "inline-block",

                marginTop: "20px",

                padding: "8px 15px",

                borderRadius: "20px",

                fontWeight: "bold",

                ...badgeStyle(candidate.recommendation),
              }}
            >
              {getRecommendationLabel(candidate.recommendation)}
            </div>

            {/* STRENGTHS / GAPS */}

            <div
              style={{
                display: "flex",
                gap: "40px",
                marginTop: "25px",
                flexWrap: "wrap",
              }}
            >
              <div
                style={{
                  flex: 1,
                }}
              >
                <h3>✅ Fortalezas</h3>

                {candidate.strengths?.length ? (
                  <ul>
                    {candidate.strengths.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p>Sin datos</p>
                )}
              </div>

              <div
                style={{
                  flex: 1,
                }}
              >
                <h3>❌ Brechas</h3>

                {candidate.gaps?.length ? (
                  <ul>
                    {candidate.gaps.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p>Sin brechas</p>
                )}
              </div>
            </div>

            <button
              className="btn btn-secondary"
              onClick={() => openAnalysis(candidate)}
              style={{
                marginTop: "20px",
                padding: "10px 15px",
                cursor: "pointer",
              }}
            >
              Ver análisis completo
            </button>
          </div>
        ))}
      </div>

      {rankingInfo.total > 0 && (
        <div
          className="ranking-pagination"
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "16px",
            flexWrap: "wrap",
            marginTop: "24px",
            padding: "16px 0",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
            }}
          >
            <span>Mostrar</span>

            <select
              value={pageSize}
              onChange={changePageSize}
              style={{
                padding: "8px 10px",
              }}
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>

            <span>por página</span>
          </div>

          <span className="muted">
            Mostrando{" "}
            {(page - 1) * pageSize + 1}
            –
            {Math.min(
              page * pageSize,
              rankingInfo.total,
            )}{" "}
            de {rankingInfo.total}
          </span>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
            }}
          >
            <button
              className="btn btn-secondary"
              onClick={() =>
                changePage(page - 1)
              }
              disabled={
                page <= 1 ||
                loading
              }
            >
              Anterior
            </button>

            <span>
              Página {page} de{" "}
              {Math.max(totalPages, 1)}
            </span>

            <button
              className="btn btn-secondary"
              onClick={() =>
                changePage(page + 1)
              }
              disabled={
                page >= totalPages ||
                loading
              }
            >
              Siguiente
            </button>
          </div>
        </div>
      )}

      {/* ========================================================
          MODE MODAL
      ======================================================== */}

      {showModeModal && (
        <div
          className="modal-overlay"
          onClick={() => setShowModeModal(false)}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
        >
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "white",
              padding: "30px",
              borderRadius: "15px",
              width: "400px",
              maxWidth: "100%",
              boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
            }}
          >
            <h2 style={{ marginTop: 0, marginBottom: "10px" }}>Actualizar ranking</h2>
            <p style={{ marginBottom: "20px", color: "#64748b" }}>
              ¿Cómo quieres actualizar el ranking?
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <button
                className="btn btn-primary"
                onClick={() => recalculateRanking("incremental")}
                disabled={isRecalculating}
                style={{
                  padding: "12px 18px",
                  cursor: isRecalculating ? "not-allowed" : "pointer",
                  textAlign: "left",
                }}
              >
                <strong>Solo nuevos candidatos</strong>
                <br />
                <span style={{ fontSize: "13px", fontWeight: "normal", opacity: 0.8 }}>
                  Evalúa solo candidatos asignados desde el último ranking
                </span>
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => recalculateRanking("full")}
                disabled={isRecalculating}
                style={{
                  padding: "12px 18px",
                  cursor: isRecalculating ? "not-allowed" : "pointer",
                  textAlign: "left",
                }}
              >
                <strong>Recalcular todo</strong>
                <br />
                <span style={{ fontSize: "13px", fontWeight: "normal", opacity: 0.8 }}>
                  Re-evalúa todos los candidatos (más lento)
                </span>
              </button>
            </div>
            <button
              className="btn btn-close"
              onClick={() => setShowModeModal(false)}
              disabled={isRecalculating}
              style={{
                marginTop: "16px",
                padding: "10px 20px",
                cursor: "pointer",
                width: "100%",
              }}
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* ========================================================
          MODAL
      ======================================================== */}

      {selectedCandidate && (
        <div
          className="modal-overlay"
          onClick={closeModal}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
        >
          <div
            className="modal ranking-modal"
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "white",
              padding: "30px",
              borderRadius: "15px",
              width: "700px",
              maxWidth: "100%",
              maxHeight: "85vh",
              overflowY: "auto",
            }}
          >
            <h2>{selectedCandidate.candidate_name}</h2>

            {selectedCandidate.status === "FAILED" || selectedCandidate.status === "PENDING" ? (
              <div style={{ marginTop: "10px" }}>
                <h1 style={{ color: "#991b1b", fontSize: "28px" }}>
                  {selectedCandidate.status === "FAILED" ? "Evaluación fallida" : "Evaluación pendiente"}
                </h1>
                {selectedCandidate.error_message && (
                  <p style={{ color: "#64748b", fontSize: "14px", marginTop: "10px" }}>
                    {selectedCandidate.error_message}
                  </p>
                )}
              </div>
            ) : (
              <>
                <h1>{selectedCandidate.match_score}%</h1>

                <div
                  style={{
                    display: "inline-block",
                    padding: "8px 15px",
                    borderRadius: "20px",
                    fontWeight: "bold",
                    ...badgeStyle(selectedCandidate.recommendation),
                  }}
                >
                  {getRecommendationLabel(selectedCandidate.recommendation)}
                </div>
              </>
            )}

            <hr />

            <h3>✅ Fortalezas</h3>

            {selectedCandidate.strengths?.length ? (
              <ul>
                {selectedCandidate.strengths.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>Sin datos</p>
            )}

            <h3>❌ Brechas</h3>

            {selectedCandidate.gaps?.length ? (
              <ul>
                {selectedCandidate.gaps.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>Sin brechas</p>
            )}

            <hr />

            <h3>📋 Requisitos evaluados</h3>

            {requirementsLoading && <p>Cargando requisitos...</p>}

            {!requirementsLoading && requirements.length === 0 && (
              <p>No hay requisitos disponibles.</p>
            )}

            {requirements.map((req, i) => (
              <div
                key={i}
                className="requirement"
                style={{
                  border: "1px solid #ddd",
                  padding: "12px",
                  marginBottom: "10px",
                  borderRadius: "8px",
                }}
              >
                <strong>{req.requirement}</strong>

                <div
                  style={{
                    marginTop: "8px",
                    display: "inline-block",
                    padding: "5px 10px",
                    borderRadius: "15px",
                    fontSize: "13px",
                    fontWeight: "bold",
                    ...getRequirementStyle(req.status),
                  }}
                >
                  {getRequirementLabel(req.status)}
                </div>

                {req.evidence && (
                  <p>
                    <strong>Evidencia:</strong> {req.evidence}
                  </p>
                )}
              </div>
            ))}

            <hr />

            <h3>🤖 Análisis IA</h3>

            {analysisLoading && <p>Generando análisis...</p>}

            {analysis && (
              <p
                style={{
                  lineHeight: "1.6",
                }}
              >
                {analysis.explanation || analysis.summary || analysis.analysis}
              </p>
            )}

            <button
              className="btn btn-close"
              onClick={closeModal}
              style={{
                marginTop: "20px",
                padding: "10px 20px",
                cursor: "pointer",
              }}
            >
              Cerrar
            </button>
            <Link
              className="btn btn-primary"
              to={`/candidates/${selectedCandidate.candidate_id}?job_id=${selectedJob}`}
              style={{ marginTop: "20px", marginLeft: "10px" }}
            >
              Abrir ficha de esta vacante
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ title, value }) {
  return (
    <div
      className="summary-card"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        border: "1px solid #ddd",
        padding: "20px",
        borderRadius: "10px",
        minWidth: "180px",
        background: "#fff",
      }}
    >
      <p
        style={{
          margin: 0,
          color: "#64748b",
          fontSize: "14px",
        }}
      >
        {title}
      </p>

      <h2
        style={{
          marginTop: "8px",
          marginBottom: 0,
        }}
      >
        {value}
      </h2>
    </div>
  );
}

export default Ranking;
