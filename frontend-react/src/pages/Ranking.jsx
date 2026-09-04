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

  const [rankingInfo, setRankingInfo] = useState({
    total: 0,
    pending: 0,
    minimum: 0,
    maximum: 0,
  });

  const hasRanking = rankingInfo.total > 0;

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

  async function loadRanking() {
    if (!selectedJob) {
      alert("Seleccione una vacante");
      return;
    }

    if (minScore < 0 || minScore > 100) {
      alert("El puntaje mínimo debe estar entre 0 y 100");
      return;
    }

    if (maxScore < 0 || maxScore > 100) {
      alert("El puntaje máximo debe estar entre 0 y 100");
      return;
    }

    if (minScore > maxScore) {
      alert("El puntaje mínimo no puede ser mayor que el puntaje máximo");
      return;
    }

    try {
      setLoading(true);

      const params = {
        min_score: minScore,
        max_score: maxScore,
        page: 1,
        page_size: 100,
      };

      if (recommendationFilter) {
        params.recommendation = recommendationFilter;
      }

      const response = await api.get(`/jobs/${selectedJob}/ranking`, {
        params,
      });

      console.log("RANKING RESPONSE:", response.data);

      const data = response.data;

      const candidates = data.candidates || data.ranking || data.items || [];

      setRanking(candidates);

      const allScores = candidates.map((candidate) =>
        Number(candidate.match_score || 0),
      );

      setRankingInfo({
        total: data.total ?? candidates.length,
        pending: data.pending_candidates ?? 0,

        minimum: allScores.length > 0 ? Math.min(...allScores) : 0,

        maximum: allScores.length > 0 ? Math.max(...allScores) : 0,
      });
    } catch (error) {
      console.error("ERROR LOADING RANKING:", error.response?.data || error);

      alert(error.response?.data?.detail || "No fue posible cargar el ranking");
    } finally {
      setLoading(false);
    }

  }

  async function recalculateRanking() {
    if (!selectedJob) {
      alert("Seleccione una vacante");
      return;
    }

    if (!window.confirm("¿Recalcular el ranking de todos los candidatos para esta vacante?")) {
      return;
    }

    try {
      setLoading(true);
      const response = await api.post(`/jobs/${selectedJob}/ranking/recalculate`);
      const totalCandidates = response.data.total_candidates || 0;
      const failed = response.data.failed || 0;

      if (failed > 0) {
        alert(`Se procesaron ${totalCandidates} candidatos actuales, incluidos los nuevos. ${failed} no pudo${failed === 1 ? "" : "ieron"} evaluarse.`);
      }

      await loadRanking();
    } catch (error) {
      alert(error.response?.data?.detail || "No fue posible recalcular el ranking");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (selectedJob) {
      // Load the selected vacancy ranking when the page initializes.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      loadRanking();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedJob]);

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

    if (recommendation === "LOW_MATCH") {
      return "Baja coincidencia";
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

    if (recommendation === "GOOD_MATCH") {
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

              <option value="LOW_MATCH">Baja coincidencia</option>
            </select>
          </div>

          {/* BUTTON */}

          <button
            className="btn btn-primary"
            onClick={hasRanking ? recalculateRanking : loadRanking}
            disabled={loading}
            style={{
              padding: "10px 18px",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Analizando..." : hasRanking ? "Recalcular ranking" : "Ver ranking"}
          </button>
        </div>
      </div>

      {selectedJob && rankingInfo.pending > 0 && (
        <p className="muted" style={{ marginTop: "16px" }}>
          {rankingInfo.pending} candidato{rankingInfo.pending === 1 ? "" : "s"} pendiente{rankingInfo.pending === 1 ? "" : "s"} de evaluación.
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
            value={`${rankingInfo.minimum}%`}
          />

          <SummaryCard
            title="Puntaje máximo"
            value={`${rankingInfo.maximum}%`}
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
            <p>{rankingInfo.pending > 0
              ? "No hay candidatos evaluados para esta vacante."
              : "No hay candidatos que cumplan con los filtros seleccionados."}</p>
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
              #{index + 1} {candidate.candidate_name}
            </h2>

            <strong>Puntaje de coincidencia</strong>

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
