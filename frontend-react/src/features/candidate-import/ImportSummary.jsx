// eslint-disable-next-line no-unused-vars
import React from "react";
import { Link } from "react-router-dom";

import "./candidate-import.css";

function Metric({ value, label }) {
  return (
    <div className="candidate-import-summary-metric">
      <strong>{value ?? 0}</strong>
      <span>{label}</span>
    </div>
  );
}

export default function ImportSummary({ batch }) {
  if (!batch) return null;

  const failed = batch.status === "FAILED";
  const withErrors = batch.status === "COMPLETED_WITH_ERRORS";
  const title = failed
    ? "La importación no pudo completarse"
    : withErrors
      ? "Importación completada con novedades"
      : "Importación completada";
  const message = failed
    ? batch.last_error_message || "No fue posible completar el procesamiento de los candidatos."
    : withErrors
      ? "El ranking está disponible, aunque algunos archivos o evaluaciones requieren revisión."
      : "Los candidatos fueron procesados y el ranking quedó actualizado.";

  return (
    <section
      className={`candidate-import-summary ${failed ? "is-failed" : "is-complete"}`}
      aria-live="polite"
    >
      <div className="candidate-import-summary-icon" aria-hidden="true">
        {failed ? "!" : "✓"}
      </div>
      <div className="candidate-import-summary-content">
        <span className="candidate-import-kicker">Resultado del lote</span>
        <h3>{title}</h3>
        <p>{message}</p>

        {!failed && (
          <div className="candidate-import-summary-grid">
            <Metric value={batch.successful_items} label="procesados" />
            <Metric value={batch.reused_items} label="reutilizados" />
            <Metric value={batch.failed_items} label="archivos con error" />
            <Metric value={batch.evaluation_failed_items} label="evaluaciones con error" />
          </div>
        )}

        {!failed && batch.ranking_ready && batch.job_id && (
          <Link
            className="btn btn-primary candidate-import-ranking-link"
            to={`/ranking?job_id=${encodeURIComponent(batch.job_id)}`}
          >
            Ver ranking
          </Link>
        )}
      </div>
    </section>
  );
}
