import { useEffect, useRef, useState } from "react";

import api from "../api/client";

function Candidates() {
  const [candidates, setCandidates] = useState([]);

  const [jobs, setJobs] = useState([]);

  const [selectedJob, setSelectedJob] = useState({});
  const [uploadJob, setUploadJob] = useState("");

  const [loading, setLoading] = useState(false);

  const [selectedEvaluation, setSelectedEvaluation] = useState(null);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [candidateFiles, setCandidateFiles] = useState([]);
  const [creatingCandidate, setCreatingCandidate] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [uploadSummary, setUploadSummary] = useState(null);
  const [fileError, setFileError] = useState("");
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const [showAllFiles, setShowAllFiles] = useState(false);
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const UPLOAD_BATCH_SIZE = 25;

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
    if (!candidateFiles.length) {
      setFileError("Selecciona al menos un archivo PDF.");
      return;
    }

    try {
      setCreatingCandidate(true);
      const summary = {
        processed: 0,
        successful: 0,
        failed: 0,
        total: candidateFiles.length,
        created: 0,
        candidates: [],
        errors: [],
      };
      for (let start = 0; start < candidateFiles.length; start += UPLOAD_BATCH_SIZE) {
        const batch = candidateFiles.slice(start, start + UPLOAD_BATCH_SIZE);
        const formData = new FormData();
        batch.forEach((file) => formData.append("files", file, file.name));
        const response = await api.post("/candidates/bulk", formData, {
          headers: { "Content-Type": undefined },
        });
        const result = response.data;
        summary.processed += result.processed ?? result.total ?? batch.length;
        summary.successful += result.successful ?? result.created ?? 0;
        summary.failed += result.failed ?? result.errors?.length ?? 0;
        summary.created = summary.successful;
        summary.candidates.push(...(result.candidates || []));
        summary.errors.push(...(result.errors || []));
        setUploadProgress({
          current: Math.min(summary.processed, candidateFiles.length),
          total: candidateFiles.length,
        });
      }
      if (uploadJob && summary.candidates.length > 0) {
        await api.post(`/jobs/${uploadJob}/candidates`, {
          candidate_ids: summary.candidates.map((candidate) => candidate.candidate_id),
        });
      }
      setUploadSummary(summary);
      setCandidateFiles([]);
      setShowCreateModal(false);
      setUploadJob("");
      await loadData();
    } catch (error) {
      console.error("CREATE CANDIDATE ERROR:", error.response?.data || error);

      const detail = error.response?.data?.detail;
      const message = Array.isArray(detail)
        ? detail.map((item) => item.msg).join(" ")
        : detail || "No fue posible agregar los candidatos.";
      setFileError(
        `${error.response?.status ? `${error.response.status}: ` : ""}${message}`,
      );
    } finally {
      setCreatingCandidate(false);
    }
  }

  function handleCandidateFilesChange(event) {
    addCandidateFiles(Array.from(event.target.files || []));
    event.target.value = "";
  }

  function addCandidateFiles(selectedFiles) {
    const invalidFile = selectedFiles.find(
      (file) => !file.name.toLowerCase().endsWith(".pdf"),
    );
    if (invalidFile) {
      setFileError(`${invalidFile.name} no es un archivo PDF.`);
    }
    const validFiles = selectedFiles.filter(
      (file) =>
        file.name.toLowerCase().endsWith(".pdf") &&
        file.size > 0 &&
        file.size <= 15 * 1024 * 1024,
    );
    const existing = new Set(candidateFiles.map((file) => `${file.name}:${file.size}`));
    const uniqueFiles = validFiles.filter((file) => {
      const key = `${file.name}:${file.size}`;
      if (existing.has(key)) return false;
      existing.add(key);
      return true;
    });
    if (selectedFiles.some((file) => file.size === 0)) {
      setFileError("Los archivos vacíos no pueden procesarse.");
    } else if (selectedFiles.some((file) => file.size > 15 * 1024 * 1024)) {
      setFileError("Cada archivo debe pesar máximo 15 MB.");
    } else if (!invalidFile) {
      setFileError("");
    }
    setCandidateFiles((current) => [...current, ...uniqueFiles]);
  }

  function removeCandidateFile(index) {
    setCandidateFiles((current) => current.filter((_, fileIndex) => fileIndex !== index));
  }

  function handleDrop(event) {
    event.preventDefault();
    setIsDraggingFiles(false);
    if (!creatingCandidate) addCandidateFiles(Array.from(event.dataTransfer.files || []));
  }

  useEffect(() => {
    // The initial request synchronizes this view with the API.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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

  async function assignCandidate(candidateId) {
    const jobId = selectedJob[candidateId];
    if (!jobId) {
      alert("Seleccione una vacante");
      return;
    }
    try {
      setLoading(true);
      await api.post(`/jobs/${jobId}/candidates`, { candidate_ids: [candidateId] });
      alert("Candidato asignado a la vacante.");
      await loadData();
    } catch (error) {
      alert(error.response?.data?.detail || "No fue posible asignar el candidato.");
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

      window.location.assign(downloadUrl);
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

    } catch (error) {
      console.error("DELETE CANDIDATE ERROR:", error.response?.data || error);

      alert(
        error.response?.data?.detail || "No fue posible eliminar el candidato",
      );
    }
  }

  async function deleteAllCandidates() {
    const confirmed = window.confirm(
      `¿Seguro que deseas eliminar los ${candidates.length} candidatos? Esta acción no se puede deshacer. También se eliminarán sus evaluaciones y CVs.`,
    );
    if (!confirmed) return;

    try {
      setLoading(true);
      const response = await api.delete("/candidates");
      const result = response.data;
      await loadData();
      setSelectedJob({});
      setSelectedEvaluation(null);
      if (result.failed) {
        window.alert(`${result.deleted} candidatos eliminados. ${result.failed} no pudieron eliminarse.`);
      }
    } catch (error) {
      console.error("DELETE ALL CANDIDATES ERROR:", error.response?.data || error);
      window.alert(error.response?.data?.detail || "No fue posible eliminar los candidatos.");
    } finally {
      setLoading(false);
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

      <div className="section-heading candidate-section-heading">
        <div>
          <h2>Candidatos registrados</h2>
          <p>{candidates.length} {candidates.length === 1 ? "perfil disponible" : "perfiles disponibles"}</p>
        </div>
        {candidates.length > 0 && (
          <button className="btn btn-danger" onClick={deleteAllCandidates} disabled={loading}>
            🗑 Eliminar todos
          </button>
        )}
      </div>

      {candidates.length === 0 ? (
        <div className="card">
          <p className="muted">No hay candidatos registrados.</p>
        </div>
      ) : (
        candidates.map((candidate) => (
          <div className="card candidate-card" key={candidate.candidate_id}>
            <div
              className="candidate-header"
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
                className="candidate-actions"
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
              className="candidate-file"
              style={{
                marginTop: "20px",
                padding: "14px 16px",
                background: "#f8fafc",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
              }}
            >
              <span
                className="candidate-file-label"
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
                onClick={() => assignCandidate(candidate.candidate_id)}
                disabled={loading}
              >
                {loading ? "Asignando..." : "Asignar a vacante"}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => evaluate(candidate.candidate_id)}
                disabled={loading}
              >
                Evaluar candidato
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
          onKeyDown={(event) => {
            if (event.key === "Escape" && !creatingCandidate) setShowCreateModal(false);
          }}
          onClick={() => {
            if (!creatingCandidate) {
              setShowCreateModal(false);
            }
          }}
        >
          <div
            className="modal candidate-upload-modal"
            onClick={(e) => e.stopPropagation()}
            style={{
              maxWidth: "520px",
            }}
          >
            <div className="modal-header">
              <div>
                <h2>Agregar candidatos</h2>

                <p
                  className="muted"
                  style={{
                    marginTop: "6px",
                  }}
                >
                  Sube uno o varios CVs. AI Recruiter identificará automáticamente a cada candidato y extraerá su información.
                </p>
              </div>

              <button
                className="btn btn-close"
                onClick={() => setShowCreateModal(false)}
                disabled={creatingCandidate}
              >
                <span aria-hidden="true">✕</span>
              </button>
            </div>

            <form onSubmit={createCandidate}>
              <div className="form-group" style={{ marginBottom: "16px" }}>
                <label htmlFor="upload-job">Asignar estos candidatos a una vacante (opcional)</label>
                <select id="upload-job" className="select" value={uploadJob} onChange={(event) => setUploadJob(event.target.value)} disabled={creatingCandidate}>
                  <option value="">Solo pool global</option>
                  {jobs.map((job) => <option key={job.job_id} value={job.job_id}>{job.title}</option>)}
                </select>
                <small className="muted">Solo los candidatos asignados aparecen en el ranking de esa vacante.</small>
              </div>
              <div className={`candidate-dropzone ${isDraggingFiles ? "is-dragging" : ""} ${creatingCandidate ? "is-disabled" : ""}`}
                role="button"
                tabIndex={0}
                aria-label="Agregar archivos PDF"
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={(event) => {
                  if ((event.key === "Enter" || event.key === " ") && !creatingCandidate) {
                    event.preventDefault();
                    fileInputRef.current?.click();
                  }
                }}
                onDragOver={(event) => { event.preventDefault(); setIsDraggingFiles(true); }}
                onDragLeave={() => setIsDraggingFiles(false)}
                onDrop={handleDrop}
              >
                <span className="candidate-dropzone-icon" aria-hidden="true">↑</span>
                <strong>Arrastra tus CVs aquí</strong>
                <span>o selecciona archivos desde tu equipo</span>
                <button type="button" className="btn btn-primary" onClick={(event) => {
                  event.stopPropagation();
                  fileInputRef.current?.click();
                }} disabled={creatingCandidate}>Seleccionar PDFs</button>
                <small>Solo archivos PDF · Puedes seleccionar varios</small>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/pdf,.pdf"
                  multiple
                  onChange={handleCandidateFilesChange}
                  className="visually-hidden-input"
                />
              </div>
              <div className="candidate-folder-action">
                <span>¿Tienes muchos CVs?</span>
                <button type="button" className="btn-link" onClick={() => folderInputRef.current?.click()} disabled={creatingCandidate}>
                  Seleccionar carpeta
                </button>
                <input
                  ref={folderInputRef}
                  type="file"
                  accept="application/pdf,.pdf"
                  multiple
                  webkitdirectory=""
                  directory=""
                  onChange={handleCandidateFilesChange}
                  aria-label="Seleccionar carpeta con CVs"
                  className="visually-hidden-input"
                />
              </div>
              {fileError && <p className="candidate-upload-error" role="alert">{fileError}</p>}
              {candidateFiles.length > 0 && (
                <div className="candidate-file-list">
                  <strong>{candidateFiles.length} archivos seleccionados</strong>
                  {(showAllFiles ? candidateFiles : candidateFiles.slice(0, 5)).map((file, index) => (
                    <div className="candidate-file-row" key={`${file.name}:${file.size}`}>
                      <span aria-hidden="true">✓</span>
                      <span title={file.name}>{file.name}</span>
                      <small>{Math.round(file.size / 1024)} KB</small>
                      <button type="button" aria-label={`Quitar ${file.name}`} onClick={() => removeCandidateFile(index)} disabled={creatingCandidate}>×</button>
                    </div>
                  ))}
                  {candidateFiles.length > 5 && <button type="button" className="btn-link" onClick={() => setShowAllFiles((value) => !value)}>
                    {showAllFiles ? "Contraer lista" : `Ver los ${candidateFiles.length - 5} restantes`}
                  </button>}
                </div>
              )}
                {uploadProgress && (
                  <div className="candidate-upload-progress" aria-live="polite">
                    <strong>Procesando candidatos</strong>
                    <span>{uploadProgress.current} de {uploadProgress.total}</span>
                    <progress value={uploadProgress.current} max={uploadProgress.total} />
                  </div>
                )}

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
                  disabled={creatingCandidate || !candidateFiles.length}
                >
                  {creatingCandidate ? "Procesando CVs..." : candidateFiles.length === 1 ? "Subir candidato" : `Subir ${candidateFiles.length || ""} candidatos`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {uploadSummary && (
        <div className="card" style={{ marginTop: "20px" }}>
          <h3>{uploadSummary.total} archivos seleccionados</h3>
          <p>{uploadSummary.created} candidatos creados · {uploadSummary.failed} errores</p>
          {uploadSummary.candidates?.map((candidate) => (
            <p key={candidate.candidate_id}>
              ✅ {candidate.name} · {candidate.original_filename} · {candidate.ingestion_status || "STARTING"}
            </p>
          ))}
          {uploadSummary.errors?.map((error) => (
            <p key={error.original_filename} style={{ color: "#b91c1c" }}>
              ❌ {error.original_filename} — {error.error}
            </p>
          ))}
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
