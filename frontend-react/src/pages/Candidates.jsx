import { useEffect, useState } from "react";

import api from "../api/client";

function Candidates() {
  const [candidates, setCandidates] = useState([]);

  const [jobs, setJobs] = useState([]);

  const [selectedJob, setSelectedJob] = useState({});

  const [evaluations, setEvaluations] = useState({});

  const [loading, setLoading] = useState(false);

  const [selectedEvaluation, setSelectedEvaluation] = useState(null);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [candidateName, setCandidateName] = useState("");
  const [candidateFile, setCandidateFile] = useState(null);
  const [creatingCandidate, setCreatingCandidate] = useState(false);

  async function loadData() {
    try {
      const candidatesResponse = await api.get("/candidates");

      const jobsResponse = await api.get("/jobs");

      const candidatesData = candidatesResponse.data;

      const jobsData = jobsResponse.data;

      setCandidates(
        Array.isArray(candidatesData)
          ? candidatesData
          : candidatesData.candidates || [],
      );

      setJobs(Array.isArray(jobsData) ? jobsData : jobsData.jobs || []);
    } catch (error) {
      console.error("ERROR LOADING DATA:", error);
    }
  }

  async function createCandidate(e) {
    e.preventDefault();

    if (!candidateName.trim()) {
      alert("Ingrese el nombre del candidato");
      return;
    }

    if (!candidateFile) {
      alert("Seleccione el CV en PDF");
      return;
    }

    try {
      setCreatingCandidate(true);

      const formData = new FormData();

      formData.append("name", candidateName.trim());
      formData.append("file", candidateFile);

      await api.post("/candidates", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setCandidateName("");
      setCandidateFile(null);
      setShowCreateModal(false);

      await loadData();
    } catch (error) {
      console.error("CREATE CANDIDATE ERROR:", error.response?.data || error);

      alert(
        error.response?.data?.detail || "No fue posible agregar el candidato",
      );
    } finally {
      setCreatingCandidate(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function evaluate(candidateId) {
    const jobId = selectedJob[candidateId];

    if (!jobId) {
      alert("Seleccione una vacante");

      return;
    }

    try {
      setLoading(true);

      const response = await api.post(
        `/candidates/${candidateId}/evaluate-job`,
        {
          job_id: jobId,
        },
      );

      console.log("EVALUATION RESPONSE:", response.data);

      setEvaluations((prev) => ({
        ...prev,
        [candidateId]: response.data,
      }));

      setSelectedEvaluation({
        candidateId,
        evaluation: response.data,
      });
    } catch (error) {
      console.error("EVALUATION ERROR:", error.response?.data || error);

      alert("Error evaluando candidato");
    } finally {
      setLoading(false);
    }
  }

  async function downloadCV(candidate) {
    try {
      const response = await api.get(
        `/candidates/${candidate.candidate_id}/download`,
      );

      const downloadUrl = response.data.download_url;

      if (!downloadUrl) {
        throw new Error("No se recibió URL de descarga");
      }

      window.location.href = downloadUrl;
    } catch (error) {
      console.error("DOWNLOAD ERROR:", error.response?.data || error);

      alert("No fue posible descargar el CV");
    }
  }

  async function deleteCandidate(candidate) {
    const confirmed = window.confirm(
      `¿Seguro que deseas eliminar al candidato "${candidate.name}"?\n\nTambién se eliminarán sus evaluaciones y el CV almacenado.`,
    );

    if (!confirmed) {
      return;
    }

    try {
      await api.delete(`/candidates/${candidate.candidate_id}`);

      // Eliminarlo inmediatamente de la pantalla
      setCandidates((prev) =>
        prev.filter((item) => item.candidate_id !== candidate.candidate_id),
      );

      // Limpiar evaluación seleccionada si corresponde
      if (selectedEvaluation?.candidateId === candidate.candidate_id) {
        setSelectedEvaluation(null);
      }

      // Limpiar estado de selección
      setSelectedJob((prev) => {
        const updated = { ...prev };

        delete updated[candidate.candidate_id];

        return updated;
      });

      // Limpiar evaluación
      setEvaluations((prev) => {
        const updated = { ...prev };

        delete updated[candidate.candidate_id];

        return updated;
      });
    } catch (error) {
      console.error("DELETE CANDIDATE ERROR:", error.response?.data || error);

      alert(
        error.response?.data?.detail || "No fue posible eliminar el candidato",
      );
    }
  }

  function getDisplayFilename(candidate) {
    if (candidate.name) {
      const cleanName = candidate.name
        .trim()
        .replace(/\s+/g, "_")
        .replace(/[^\wáéíóúÁÉÍÓÚñÑ-]/g, "");

      return `${cleanName}_CV.pdf`;
    }

    return candidate.filename || "CV.pdf";
  }

  function closeModal() {
    setSelectedEvaluation(null);
  }

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

  return (
    <div className="page">
      <div
        className="page-header"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "20px",
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1>Candidatos</h1>

          <p>Gestión de CVs con Inteligencia Artificial</p>
        </div>

        <button
          className="btn btn-primary"
          onClick={() => setShowCreateModal(true)}
        >
          + Agregar candidato
        </button>
      </div>

      <h2 style={{ marginBottom: "20px" }}>Candidatos registrados</h2>

      {candidates.length === 0 ? (
        <div className="card">
          <p className="muted">No hay candidatos registrados.</p>
        </div>
      ) : (
        candidates.map((candidate) => (
          <div className="card" key={candidate.candidate_id}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: "20px",
                flexWrap: "wrap",
              }}
            >
              <div>
                <h2>{candidate.name}</h2>

                <p
                  className="muted"
                  style={{
                    marginTop: "6px",
                    fontSize: "14px",
                  }}
                >
                  Candidato registrado
                </p>
              </div>

              <div
                style={{
                  display: "flex",
                  gap: "10px",
                  flexWrap: "wrap",
                }}
              >
                <button
                  className="btn btn-secondary"
                  onClick={() => downloadCV(candidate)}
                >
                  📄 Descargar CV
                </button>

                <button
                  className="btn btn-danger"
                  onClick={() => deleteCandidate(candidate)}
                >
                  🗑 Eliminar
                </button>
              </div>
            </div>

            <div
              style={{
                marginTop: "20px",
                padding: "14px 16px",
                background: "#f8fafc",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              <span
                style={{
                  fontSize: "13px",
                  color: "var(--text-muted)",
                  display: "block",
                  marginBottom: "4px",
                }}
              >
                Archivo
              </span>

              <strong>{getDisplayFilename(candidate)}</strong>
            </div>

            <div
              className="controls"
              style={{
                marginTop: "20px",
              }}
            >
              <select
                className="select"
                value={selectedJob[candidate.candidate_id] || ""}
                onChange={(e) =>
                  setSelectedJob((prev) => ({
                    ...prev,
                    [candidate.candidate_id]: e.target.value,
                  }))
                }
              >
                <option value="">Seleccione vacante</option>

                {jobs.map((job) => (
                  <option key={job.job_id} value={job.job_id}>
                    {job.title}
                  </option>
                ))}
              </select>

              <button
                className="btn btn-primary"
                onClick={() => evaluate(candidate.candidate_id)}
                disabled={loading}
              >
                {loading ? "Evaluando..." : "Evaluar candidato"}
              </button>
            </div>
          </div>
        ))
      )}

      {/* =====================================================
       MODAL CREAR CANDIDATO
       ===================================================== */}

      {showCreateModal && (
        <div
          className="modal-overlay"
          onClick={() => {
            if (!creatingCandidate) {
              setShowCreateModal(false);
            }
          }}
        >
          <div
            className="modal"
            onClick={(e) => e.stopPropagation()}
            style={{
              maxWidth: "520px",
            }}
          >
            <div className="modal-header">
              <div>
                <h2>Agregar candidato</h2>

                <p
                  className="muted"
                  style={{
                    marginTop: "6px",
                  }}
                >
                  Sube el CV del candidato para analizarlo con IA.
                </p>
              </div>

              <button
                className="btn btn-close"
                onClick={() => setShowCreateModal(false)}
                disabled={creatingCandidate}
              >
                ✕
              </button>
            </div>

            <form onSubmit={createCandidate}>
              <div style={{ marginBottom: "20px" }}>
                <label
                  style={{
                    display: "block",
                    marginBottom: "8px",
                    fontSize: "14px",
                    fontWeight: "600",
                  }}
                >
                  Nombre del candidato
                </label>

                <input
                  type="text"
                  value={candidateName}
                  onChange={(e) => setCandidateName(e.target.value)}
                  placeholder="Ej. Nicolas Felipe Castro"
                  style={{
                    width: "100%",
                    padding: "12px 14px",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    fontSize: "14px",
                    color: "var(--text)",
                    background: "white",
                    outline: "none",
                  }}
                />
              </div>

              <div style={{ marginBottom: "24px" }}>
                <label
                  style={{
                    display: "block",
                    marginBottom: "8px",
                    fontSize: "14px",
                    fontWeight: "600",
                  }}
                >
                  CV en PDF
                </label>

                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={(e) =>
                    setCandidateFile(e.target.files?.[0] || null)
                  }
                  style={{
                    width: "100%",
                    padding: "12px",
                    border: "1px dashed var(--border)",
                    borderRadius: "var(--radius-sm)",
                    background: "#f8fafc",
                    fontSize: "14px",
                    cursor: "pointer",
                  }}
                />

                {candidateFile && (
                  <p
                    className="muted"
                    style={{
                      marginTop: "8px",
                      fontSize: "13px",
                    }}
                  >
                    📄 {candidateFile.name}
                  </p>
                )}
              </div>

              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: "10px",
                }}
              >
                <button
                  type="button"
                  className="btn btn-close"
                  onClick={() => setShowCreateModal(false)}
                  disabled={creatingCandidate}
                >
                  Cancelar
                </button>

                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={creatingCandidate}
                >
                  {creatingCandidate ? "Subiendo CV..." : "Agregar candidato"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* =====================================================
          MODAL EVALUACIÓN
      ===================================================== */}

      {selectedEvaluation && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h2>Resultado de evaluación IA</h2>

                <p
                  className="muted"
                  style={{
                    marginTop: "6px",
                  }}
                >
                  Evaluación del candidato
                </p>
              </div>

              <button className="btn btn-close" onClick={closeModal}>
                ✕
              </button>
            </div>

            <div
              style={{
                textAlign: "center",
                padding: "20px 0",
              }}
            >
              <div className="score">
                {selectedEvaluation.evaluation.match_score}%
              </div>

              <div
                className="score-bar"
                style={{
                  maxWidth: "400px",
                  margin: "0 auto",
                }}
              >
                <div
                  className="score-fill"
                  style={{
                    width: `${selectedEvaluation.evaluation.match_score}%`,
                  }}
                />
              </div>

              <div
                className="badge"
                style={{
                  marginTop: "18px",
                  ...badgeStyle(selectedEvaluation.evaluation.recommendation),
                }}
              >
                {getRecommendationLabel(
                  selectedEvaluation.evaluation.recommendation,
                )}
              </div>
            </div>

            <div className="result">
              <h3>Resumen</h3>

              <p
                style={{
                  marginTop: "10px",
                  lineHeight: "1.6",
                }}
              >
                {selectedEvaluation.evaluation.summary}
              </p>
            </div>

            <div className="columns">
              <div>
                <h3 className="section-title">✅ Fortalezas</h3>

                {selectedEvaluation.evaluation.strengths?.length ? (
                  <ul className="list">
                    {selectedEvaluation.evaluation.strengths.map(
                      (item, index) => (
                        <li key={index}>{item}</li>
                      ),
                    )}
                  </ul>
                ) : (
                  <p className="muted">Sin datos</p>
                )}
              </div>

              <div>
                <h3 className="section-title">❌ Gaps</h3>

                {selectedEvaluation.evaluation.gaps?.length ? (
                  <ul className="list">
                    {selectedEvaluation.evaluation.gaps.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">Sin datos</p>
                )}
              </div>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                marginTop: "25px",
                gap: "10px",
              }}
            >
              <button className="btn btn-close" onClick={closeModal}>
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Candidates;
