// eslint-disable-next-line no-unused-vars
import React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import api from "../api/client";


function employeeName(employee) {
  return [employee?.first_name, employee?.last_name].filter(Boolean).join(" ")
    || employee?.email
    || "Empleado";
}


function EmployeeScores() {
  const [employees, setEmployees] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState(null);
  const [query, setQuery] = useState("");
  const [points, setPoints] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const loadEmployees = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = query.trim() ? { q: query.trim() } : {};
      const { data } = await api.get("/direction/employee-scores", { params });
      const items = Array.isArray(data?.items) ? data.items : [];
      setEmployees(items);
      setSelectedId((current) => {
        if (current && items.some((item) => item.id === current)) return current;
        return items[0]?.id || "";
      });
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cargar las calificaciones.");
    } finally {
      setLoading(false);
    }
  }, [query]);

  const loadDetail = useCallback(async (employeeId) => {
    if (!employeeId) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    setError("");
    try {
      const { data } = await api.get(`/direction/employee-scores/${employeeId}`);
      setDetail(data);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cargar el historial.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadEmployees();
    }, 200);
    return () => window.clearTimeout(timeoutId);
  }, [loadEmployees]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadDetail(selectedId);
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadDetail, selectedId]);

  const selectedEmployee = useMemo(
    () => employees.find((employee) => employee.id === selectedId) || detail?.employee,
    [detail, employees, selectedId],
  );

  async function createEvent(event) {
    event.preventDefault();
    const numericPoints = Number(points);
    if (!Number.isInteger(numericPoints) || numericPoints === 0) {
      setError("Ingresa una cantidad de puntos distinta de cero.");
      return;
    }
    if (!description.trim()) {
      setError("Describe el motivo de la calificación.");
      return;
    }

    setSaving(true);
    setError("");
    try {
      await api.post(`/direction/employee-scores/${selectedId}/events`, {
        points: numericPoints,
        description: description.trim(),
      });
      setPoints("");
      setDescription("");
      await Promise.all([loadEmployees(), loadDetail(selectedId)]);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible guardar la calificación.");
    } finally {
      setSaving(false);
    }
  }

  async function voidEvent(scoreEvent) {
    const reason = window.prompt(
      "Motivo de la anulación. El movimiento seguirá visible en el historial:",
      "",
    );
    if (!reason?.trim()) return;

    setError("");
    try {
      await api.post(`/direction/employee-scores/events/${scoreEvent.id}/void`, {
        reason: reason.trim(),
      });
      await Promise.all([loadEmployees(), loadDetail(selectedId)]);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible anular el movimiento.");
    }
  }

  return (
    <div className="page direction-score-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Dirección · Privado</span>
          <h1>Calificación de empleados</h1>
          <p>Registra reconocimientos o descuentos con su justificación y conserva el historial completo.</p>
        </div>
      </header>

      <div className="direction-privacy-note">
        <strong>Información privada de Dirección</strong>
        <span>Esta sección y sus movimientos no están disponibles para administradores ni empleados.</span>
      </div>

      {error && <div className="alert" role="alert">{error}</div>}

      <div className="score-workspace">
        <aside className="panel score-employee-panel">
          <div className="score-employee-heading">
            <div>
              <span className="eyebrow">Equipo</span>
              <h2>Empleados</h2>
            </div>
            <span>{employees.length}</span>
          </div>

          <input
            className="score-search"
            type="search"
            placeholder="Buscar empleado…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Buscar empleado para calificar"
          />

          {loading ? (
            <div className="page-loading compact-loading"><span /> Cargando…</div>
          ) : employees.length === 0 ? (
            <div className="empty-state compact">
              <strong>Sin resultados</strong>
              <p>No encontramos empleados con ese filtro.</p>
            </div>
          ) : (
            <div className="score-employee-list">
              {employees.map((employee) => (
                <button
                  key={employee.id}
                  type="button"
                  className={`score-employee-row ${employee.id === selectedId ? "active" : ""}`}
                  onClick={() => setSelectedId(employee.id)}
                >
                  <span className="employee-avatar" aria-hidden="true">
                    {(employee.first_name?.[0] || employee.email?.[0] || "?").toUpperCase()}
                  </span>
                  <span>
                    <strong>{employeeName(employee)}</strong>
                    <small>{employee.job_title || employee.department || employee.email}</small>
                  </span>
                  <b className={employee.score_total < 0 ? "score-negative" : "score-positive"}>
                    {employee.score_total > 0 ? "+" : ""}{employee.score_total}
                  </b>
                </button>
              ))}
            </div>
          )}
        </aside>

        <section className="score-detail-column">
          {!selectedEmployee ? (
            <section className="panel empty-state">
              <strong>Selecciona un empleado</strong>
              <p>Elige un perfil para consultar su historial y registrar una calificación.</p>
            </section>
          ) : (
            <>
              <section className="panel score-summary-panel">
                <div>
                  <span className="eyebrow">Puntuación actual</span>
                  <h2>{employeeName(selectedEmployee)}</h2>
                  <p>{selectedEmployee.job_title || "Sin cargo"} · {selectedEmployee.department || "Sin área"}</p>
                </div>
                <strong className={`direction-score-total ${(detail?.employee?.score_total ?? selectedEmployee.score_total) < 0 ? "score-negative" : "score-positive"}`}>
                  {(detail?.employee?.score_total ?? selectedEmployee.score_total) > 0 ? "+" : ""}
                  {detail?.employee?.score_total ?? selectedEmployee.score_total ?? 0}
                  <small> pts</small>
                </strong>
              </section>

              <section className="panel score-entry-panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">Nuevo movimiento</span>
                    <h2>Agregar calificación</h2>
                  </div>
                </div>

                <form onSubmit={createEvent}>
                  <div className="score-entry-grid">
                    <div className="form-group">
                      <label htmlFor="score-points">Puntos</label>
                      <input
                        id="score-points"
                        type="number"
                        step="1"
                        value={points}
                        onChange={(event) => setPoints(event.target.value)}
                        placeholder="+30 o -5"
                        required
                      />
                      <small>Usa un valor positivo para reconocer y negativo para descontar.</small>
                    </div>
                    <div className="form-group">
                      <label htmlFor="score-description">Descripción</label>
                      <textarea
                        id="score-description"
                        rows="4"
                        value={description}
                        onChange={(event) => setDescription(event.target.value)}
                        placeholder="Ej. Completó exitosamente el proyecto de integración."
                        required
                      />
                    </div>
                  </div>
                  <div className="form-actions">
                    <button className="btn btn-primary" type="submit" disabled={saving || !selectedId}>
                      {saving ? "Guardando…" : "Guardar calificación"}
                    </button>
                  </div>
                </form>
              </section>

              <section className="panel score-history-panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">Trazabilidad</span>
                    <h2>Historial de calificaciones</h2>
                  </div>
                </div>

                {detailLoading ? (
                  <div className="page-loading compact-loading"><span /> Cargando historial…</div>
                ) : !detail?.history?.length ? (
                  <div className="empty-state compact">
                    <strong>Aún no hay movimientos</strong>
                    <p>La primera calificación aparecerá aquí.</p>
                  </div>
                ) : (
                  <div className="score-history-list">
                    {detail.history.map((scoreEvent) => (
                      <article key={scoreEvent.id} className={`score-history-row ${scoreEvent.status === "VOIDED" ? "is-voided" : ""}`}>
                        <div className={`score-history-points ${scoreEvent.points < 0 ? "score-negative" : "score-positive"}`}>
                          {scoreEvent.points > 0 ? "+" : ""}{scoreEvent.points}
                        </div>
                        <div className="score-history-copy">
                          <strong>{scoreEvent.description}</strong>
                          <small>
                            {scoreEvent.event_date ? new Date(scoreEvent.event_date).toLocaleString("es-CO") : "Sin fecha"}
                            {scoreEvent.status === "VOIDED" ? " · ANULADO" : ""}
                          </small>
                          {scoreEvent.void_reason && <p>Motivo de anulación: {scoreEvent.void_reason}</p>}
                        </div>
                        {scoreEvent.status === "ACTIVE" && (
                          <button className="btn btn-ghost" type="button" onClick={() => voidEvent(scoreEvent)}>
                            Anular
                          </button>
                        )}
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

export default EmployeeScores;
