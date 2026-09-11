// eslint-disable-next-line no-unused-vars
import React, { useRef, useState } from "react";

import ImportProgress from "./ImportProgress.jsx";
import ImportSummary from "./ImportSummary.jsx";
import { useCandidateImport } from "./useCandidateImport.js";
import { validateSelectedFiles } from "./validation.js";
import "./candidate-import.css";

function displaySize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const kib = bytes / 1024;
  if (kib < 1024) return `${Math.round(kib)} KB`;
  return `${(kib / 1024).toFixed(1)} MB`;
}

function ImportItemRows({ items }) {
  if (!items?.length) return null;
  return (
    <div className="candidate-import-file-list" aria-label="Estado de candidatos del lote">
      {items.slice(0, 20).map((item) => (
        <div className="candidate-import-file-row" key={item.id || item.item_id}>
          <span aria-hidden="true">{item.status === "FAILED" ? "!" : "✓"}</span>
          <span title={item.original_filename || item.filename}>
            {item.original_filename || item.filename || "CV"}
          </span>
          <small>{item.outcome || item.current_stage || item.status}</small>
          <span aria-hidden="true" />
        </div>
      ))}
      {items.length > 20 && (
        <small className="muted">Y {items.length - 20} candidatos más en este lote.</small>
      )}
    </div>
  );
}

export default function CandidateImportModal({
  open = true,
  jobs = [],
  initialJobId = "",
  onClose,
}) {
  const [selectedJobId, setSelectedJobId] = useState(initialJobId);
  const [files, setFiles] = useState([]);
  const [localError, setLocalError] = useState("");
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const {
    phase,
    batch,
    items,
    uploadProgress,
    error,
    startImport,
    reset,
  } = useCandidateImport(selectedJobId || null);

  if (!open) return null;

  const uploading = phase === "uploading";
  const processing = phase === "processing";
  const terminal = phase === "completed" || phase === "failed";
  const locked = uploading || processing;

  const close = () => {
    if (uploading) return;
    onClose?.();
  };

  const addFiles = (incoming) => {
    if (locked) return;
    const additions = Array.from(incoming || []);
    const existing = new Set(files.map((file) => `${file.name}:${file.size}`));
    const unique = additions.filter((file) => {
      const key = `${file.name}:${file.size}`;
      if (existing.has(key)) return false;
      existing.add(key);
      return true;
    });
    const next = [...files, ...unique];
    const validationError = validateSelectedFiles(next);
    if (validationError) {
      setLocalError(validationError);
      return;
    }
    setLocalError("");
    setFiles(next);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!selectedJobId) {
      setLocalError("Selecciona la vacante que recibirá estos candidatos.");
      return;
    }
    const validationError = validateSelectedFiles(files);
    if (validationError) {
      setLocalError(validationError);
      return;
    }
    if (!files.length) {
      setLocalError("Selecciona al menos un CV o un archivo ZIP.");
      return;
    }
    setLocalError("");
    try {
      await startImport(selectedJobId, files);
      setFiles([]);
    } catch {
      // The hook exposes the public-safe error to the modal.
    }
  };

  const startAnother = () => {
    reset();
    setFiles([]);
    setLocalError("");
  };

  return (
    <div
      className="modal-overlay"
      role="presentation"
      onClick={close}
      onKeyDown={(event) => {
        if (event.key === "Escape") close();
      }}
    >
      <div
        className="modal candidate-import-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="candidate-import-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="candidate-import-kicker">Importación inteligente</span>
            <h2 id="candidate-import-title">Agregar candidatos</h2>
            <p className="muted" style={{ marginTop: 6 }}>
              Sube PDF, DOCX o ZIP. AI Recruiter identifica duplicados, actualiza el conocimiento,
              evalúa y recalcula el ranking automáticamente.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-close"
            onClick={close}
            disabled={uploading}
            aria-label="Cerrar importación"
          >
            ✕
          </button>
        </div>

        {!terminal && !processing && (
          <form onSubmit={handleSubmit}>
            <div className="form-group" style={{ marginTop: 18 }}>
              <label htmlFor="candidate-import-job">Vacante de destino</label>
              <select
                id="candidate-import-job"
                className="select"
                value={selectedJobId}
                onChange={(event) => setSelectedJobId(event.target.value)}
                disabled={uploading}
              >
                <option value="">Selecciona una vacante</option>
                {jobs.map((job) => (
                  <option key={job.job_id} value={job.job_id}>{job.title}</option>
                ))}
              </select>
            </div>

            {!uploading && (
              <div
                className={`candidate-import-dropzone ${dragging ? "is-dragging" : ""}`}
                role="button"
                tabIndex={0}
                aria-label="Seleccionar CVs PDF DOCX o ZIP"
                onClick={() => inputRef.current?.click()}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    inputRef.current?.click();
                  }
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragging(false);
                  addFiles(event.dataTransfer.files);
                }}
              >
                <span className="candidate-import-dropzone-icon" aria-hidden="true">↑</span>
                <strong>Arrastra los CVs aquí</strong>
                <span>o selecciónalos desde tu equipo</span>
                <small>PDF/DOCX hasta 15 MB · ZIP hasta 500 MB · máximo 500 CVs</small>
                <input
                  ref={inputRef}
                  className="visually-hidden-input"
                  type="file"
                  accept=".pdf,.docx,.zip,application/pdf,application/zip,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  multiple
                  onChange={(event) => {
                    addFiles(event.target.files);
                    event.target.value = "";
                  }}
                />
              </div>
            )}

            {!uploading && files.length > 0 && (
              <div className="candidate-import-file-list">
                <strong>{files.length} {files.length === 1 ? "archivo seleccionado" : "archivos seleccionados"}</strong>
                {files.slice(0, 12).map((file, index) => (
                  <div className="candidate-import-file-row" key={`${file.name}:${file.size}`}>
                    <span aria-hidden="true">✓</span>
                    <span title={file.name}>{file.name}</span>
                    <small>{displaySize(file.size)}</small>
                    <button
                      type="button"
                      aria-label={`Quitar ${file.name}`}
                      onClick={() => setFiles((current) => current.filter((_, position) => position !== index))}
                    >
                      ×
                    </button>
                  </div>
                ))}
                {files.length > 12 && <small className="muted">Y {files.length - 12} archivos más.</small>}
              </div>
            )}

            {(localError || error) && (
              <p className="candidate-import-error" role="alert">{localError || error}</p>
            )}

            {uploading && <ImportProgress batch={batch} uploadProgress={uploadProgress} />}

            <div className="candidate-import-actions">
              <button type="button" className="btn btn-close" onClick={close} disabled={uploading}>
                Cancelar
              </button>
              <button type="submit" className="btn btn-primary" disabled={uploading || !files.length}>
                {uploading ? "Subiendo CVs..." : `Importar ${files.length || ""} ${files.length === 1 ? "candidato" : "candidatos"}`}
              </button>
            </div>
          </form>
        )}

        {processing && (
          <>
            <ImportProgress batch={batch} uploadProgress={null} />
            <ImportItemRows items={items} />
            <p className="candidate-import-processing-note">
              Puedes cerrar esta ventana. El proceso seguirá en segundo plano y se recuperará al volver.
            </p>
            {(localError || error) && (
              <p className="candidate-import-error" role="alert">{localError || error}</p>
            )}
            <div className="candidate-import-actions">
              <button type="button" className="btn btn-secondary" onClick={close}>
                Cerrar y continuar en segundo plano
              </button>
            </div>
          </>
        )}

        {terminal && (
          <>
            <ImportSummary batch={batch} />
            <ImportItemRows items={items} />
            <div className="candidate-import-actions">
              <button type="button" className="btn btn-secondary" onClick={close}>Cerrar</button>
              <button type="button" className="btn btn-primary" onClick={startAnother}>Importar otro lote</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
