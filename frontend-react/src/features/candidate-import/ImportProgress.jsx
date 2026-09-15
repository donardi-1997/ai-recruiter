// eslint-disable-next-line no-unused-vars
import React from "react";

import "./candidate-import.css";

const STAGE_COPY = {
  UPLOADING: ["Subiendo CVs", "Transferencia directa y segura al almacenamiento temporal."],
  VALIDATING: ["Validando archivos", "Comprobando formato, tamaño e integridad de cada CV."],
  DEDUPLICATING: ["Identificando candidatos", "Reutilizando perfiles existentes sin crear duplicados."],
  INGESTING: ["Actualizando conocimiento", "Bedrock está indexando los CVs que cambiaron."],
  EVALUATING: ["Evaluando candidatos", "Contrastando cada perfil con los requisitos de la vacante."],
  RANKING: ["Construyendo ranking", "Ordenando los resultados persistidos para esta vacante."],
  COMPLETED: ["Importación completada", "Los resultados ya están disponibles."],
};

function formatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${bytes} B`;
  const kib = bytes / 1024;
  if (kib < 1024) return `${kib.toFixed(kib >= 10 ? 0 : 1)} KB`;
  const mib = kib / 1024;
  return `${mib.toFixed(mib >= 10 ? 0 : 1)} MB`;
}

function EvaluatingProgress({ batch }) {
  const total = Math.max(
    Number(batch?.successful_items) || 0,
    Number(batch?.evaluated_items) || 0,
  );
  const completed = Math.min(Number(batch?.evaluated_items) || 0, total);

  return (
    <div className="candidate-import-measured" aria-live="polite">
      <div className="candidate-import-measured-row">
        <strong>{completed} / {total}</strong>
        <span>evaluaciones completadas</span>
      </div>
      {total > 0 && (
        <progress value={completed} max={total} aria-label="Evaluaciones completadas" />
      )}
    </div>
  );
}

export default function ImportProgress({ batch, uploadProgress }) {
  if (!batch && !uploadProgress) return null;

  const stage = batch?.current_stage || "UPLOADING";
  const [title, description] = STAGE_COPY[stage] || [
    "Procesando candidatos",
    "El proceso continúa en segundo plano.",
  ];
  const showMeasuredUpload = stage === "UPLOADING" && uploadProgress;
  const showEvaluationCount = stage === "EVALUATING";
  const showIndeterminate = !showMeasuredUpload && !showEvaluationCount;

  return (
    <section className="candidate-import-progress" aria-live="polite" aria-busy="true">
      <div className="candidate-import-progress-heading">
        <span className="candidate-import-pulse" aria-hidden="true" />
        <div>
          <span className="candidate-import-kicker">AI Recruiter · proceso activo</span>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
      </div>

      {showMeasuredUpload && (
        <div className="candidate-import-measured">
          <div className="candidate-import-measured-row">
            <strong>{uploadProgress.percent}%</strong>
            <span>
              {formatBytes(uploadProgress.loadedBytes)} de {formatBytes(uploadProgress.totalBytes)}
            </span>
          </div>
          <progress
            value={uploadProgress.loadedBytes}
            max={Math.max(uploadProgress.totalBytes, 1)}
            aria-label="Progreso de subida de CVs"
          />
        </div>
      )}

      {showEvaluationCount && <EvaluatingProgress batch={batch} />}

      {showIndeterminate && (
        <div className="candidate-import-indeterminate" data-testid="indeterminate-progress">
          <span aria-hidden="true" />
        </div>
      )}

      {batch?.total_items > 0 && stage !== "UPLOADING" && (
        <div className="candidate-import-counters">
          <span><strong>{batch.processed_items || 0}</strong> procesados</span>
          <span><strong>{batch.reused_items || 0}</strong> reutilizados</span>
          <span><strong>{batch.failed_items || 0}</strong> con error</span>
        </div>
      )}
    </section>
  );
}
