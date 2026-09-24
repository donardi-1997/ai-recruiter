// eslint-disable-next-line no-unused-vars
import React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import api from "../api/client";
import { useSession } from "../context/SessionContext";

function todayInputValue() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function emptyEmployeeForm() {
  return {
    first_name: "",
    last_name: "",
    email: "",
    job_title: "",
    department: "",
    hire_date: todayInputValue(),
    role: "EMPLOYEE",
  };
}

function Employees() {
  const { principal, hasRole } = useSession();
  const isSuperAdmin = hasRole("SUPER_ADMIN");
  const [employees, setEmployees] = useState([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(() => emptyEmployeeForm());

  const loadEmployees = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = {};
      if (query.trim()) params.q = query.trim();
      if (statusFilter) params.status = statusFilter;
      const { data } = await api.get("/employees", { params });
      setEmployees(Array.isArray(data?.items) ? data.items : []);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cargar los empleados.");
    } finally {
      setLoading(false);
    }
  }, [query, statusFilter]);

  useEffect(() => {
    const timeoutId = window.setTimeout(loadEmployees, 250);
    return () => window.clearTimeout(timeoutId);
  }, [loadEmployees]);

  const stats = useMemo(() => {
    const active = employees.filter((employee) => employee.status === "ACTIVE").length;
    const admins = employees.filter((employee) =>
      employee.roles?.some((role) => role === "ADMIN" || role === "SUPER_ADMIN")
    ).length;
    return { active, admins };
  }, [employees]);

  async function createEmployee(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.post("/employees", form);
      setForm(emptyEmployeeForm());
      setFormOpen(false);
      await loadEmployees();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible crear el empleado.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(employee) {
    const nextStatus = employee.status === "ACTIVE" ? "DISABLED" : "ACTIVE";
    setError("");
    try {
      await api.put(`/employees/${employee.id}/status`, { status: nextStatus });
      await loadEmployees();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cambiar el estado.");
    }
  }

  async function changeRole(employee, role) {
    setError("");
    try {
      await api.put(`/employees/${employee.id}/role`, { role });
      await loadEmployees();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cambiar el rol.");
    }
  }

  return (
    <div className="page employees-page">
      <header className="page-header split-header">
        <div>
          <span className="eyebrow">Gestión interna</span>
          <h1>Empleados</h1>
          <p>Administra accesos, perfiles y roles del equipo ASIATI.</p>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => setFormOpen(true)}>
          + Crear empleado
        </button>
      </header>

      {error && <div className="alert" role="alert">{error}</div>}

      <section className="metrics-grid employees-metrics" aria-label="Resumen de empleados">
        <article className="metric-card metric-blue">
          <span className="metric-label">Empleados visibles</span>
          <strong className="metric-value">{employees.length}</strong>
          <small>Perfiles encontrados</small>
        </article>
        <article className="metric-card metric-cyan">
          <span className="metric-label">Activos</span>
          <strong className="metric-value">{stats.active}</strong>
          <small>Con acceso habilitado</small>
        </article>
        <article className="metric-card metric-violet">
          <span className="metric-label">Administrativos</span>
          <strong className="metric-value">{stats.admins}</strong>
          <small>ADMIN o SUPER_ADMIN</small>
        </article>
      </section>

      <section className="panel employee-list-panel">
        <div className="employee-toolbar">
          <div>
            <span className="eyebrow">Directorio</span>
            <h2>Equipo ASIATI</h2>
          </div>
          <div className="employee-filters">
            <input
              type="search"
              placeholder="Buscar por nombre, correo, cargo…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="Buscar empleados"
            />
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              aria-label="Filtrar por estado"
            >
              <option value="">Todos los estados</option>
              <option value="ACTIVE">Activos</option>
              <option value="DISABLED">Deshabilitados</option>
            </select>
          </div>
        </div>

        {loading ? (
          <div className="page-loading"><span /> Cargando empleados…</div>
        ) : employees.length === 0 ? (
          <div className="empty-state compact">
            <strong>No hay empleados para mostrar</strong>
            <p>Crea el primer perfil o modifica los filtros.</p>
          </div>
        ) : (
          <div className="employee-table-wrap">
            <table className="employee-table">
              <thead>
                <tr>
                  <th>Empleado</th>
                  <th>Cargo / área</th>
                  <th>Rol</th>
                  <th>Onboarding</th>
                  <th>Estado</th>
                  <th aria-label="Acciones" />
                </tr>
              </thead>
              <tbody>
                {employees.map((employee) => {
                  const role = employee.roles?.[0] || "EMPLOYEE";
                  const administrative = role === "ADMIN" || role === "SUPER_ADMIN";
                  const isSelf = employee.id === principal?.profile?.id;
                  const canManageTarget = !isSelf && (isSuperAdmin || !administrative);
                  return (
                    <tr key={employee.id}>
                      <td>
                        <div className="employee-person">
                          <span className="employee-avatar" aria-hidden="true">
                            {(employee.first_name?.[0] || employee.email?.[0] || "?").toUpperCase()}
                          </span>
                          <div>
                            <strong>{[employee.first_name, employee.last_name].filter(Boolean).join(" ") || "Sin nombre"}</strong>
                            <small>{employee.email}</small>
                          </div>
                        </div>
                      </td>
                      <td>
                        <strong className="employee-secondary">{employee.job_title || "Sin cargo"}</strong>
                        <small>{employee.department || "Sin área"}</small>
                      </td>
                      <td>
                        {isSuperAdmin && canManageTarget ? (
                          <select
                            className="employee-role-select"
                            value={role}
                            onChange={(event) => changeRole(employee, event.target.value)}
                          >
                            <option value="EMPLOYEE">Empleado</option>
                            <option value="ADMIN">Administrador</option>
                            <option value="SUPER_ADMIN">Super administrador</option>
                          </select>
                        ) : (
                          <span className={`role-pill role-${role.toLowerCase()}`}>
                            {role === "SUPER_ADMIN" ? "Super admin" : role === "ADMIN" ? "Administrador" : "Empleado"}
                          </span>
                        )}
                      </td>
                      <td>
                        <span className={`onboarding-pill onboarding-${String(employee.onboarding_status || "NOT_REQUIRED").toLowerCase()}`}>
                          {employee.onboarding_status === "COMPLETED"
                            ? "Completado"
                            : employee.onboarding_status === "IN_PROGRESS"
                              ? "En progreso"
                              : employee.onboarding_status === "PENDING"
                                ? "Pendiente"
                                : "No requerido"}
                        </span>
                        {employee.hire_date && <small>Ingreso: {employee.hire_date}</small>}
                      </td>
                      <td>
                        <span className={`status-pill ${employee.status === "ACTIVE" ? "" : "status-disabled"}`}>
                          <i /> {employee.status === "ACTIVE" ? "Activo" : "Deshabilitado"}
                        </span>
                      </td>
                      <td>
                        {canManageTarget && (
                          <button
                            className="btn btn-ghost employee-status-button"
                            type="button"
                            onClick={() => toggleStatus(employee)}
                          >
                            {employee.status === "ACTIVE" ? "Deshabilitar" : "Activar"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {formOpen && (
        <div className="modal-overlay" role="presentation" onMouseDown={() => setFormOpen(false)}>
          <section className="modal employee-modal" role="dialog" aria-modal="true" aria-labelledby="employee-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <span className="eyebrow">Nuevo acceso</span>
                <h2 id="employee-modal-title">Crear empleado</h2>
                <p>La cuenta se creará en Cognito y recibirá la invitación de acceso por correo.</p>
              </div>
              <button className="btn-close" type="button" aria-label="Cerrar" onClick={() => setFormOpen(false)}>×</button>
            </div>

            <form className="employee-form" onSubmit={createEmployee}>
              <div className="employee-form-grid">
                <div className="form-group">
                  <label htmlFor="employee-first-name">Nombre</label>
                  <input id="employee-first-name" value={form.first_name} onChange={(event) => setForm({ ...form, first_name: event.target.value })} required />
                </div>
                <div className="form-group">
                  <label htmlFor="employee-last-name">Apellido</label>
                  <input id="employee-last-name" value={form.last_name} onChange={(event) => setForm({ ...form, last_name: event.target.value })} required />
                </div>
              </div>
              <div className="form-group">
                <label htmlFor="employee-email">Correo corporativo</label>
                <input id="employee-email" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required />
              </div>
              <div className="employee-form-grid">
                <div className="form-group">
                  <label htmlFor="employee-job-title">Cargo</label>
                  <input id="employee-job-title" value={form.job_title} onChange={(event) => setForm({ ...form, job_title: event.target.value })} />
                </div>
                <div className="form-group">
                  <label htmlFor="employee-department">Área</label>
                  <input id="employee-department" value={form.department} onChange={(event) => setForm({ ...form, department: event.target.value })} />
                </div>
              </div>
              <div className="form-group">
                <label htmlFor="employee-hire-date">Fecha de ingreso</label>
                <input
                  id="employee-hire-date"
                  type="date"
                  value={form.hire_date}
                  onChange={(event) => setForm({ ...form, hire_date: event.target.value })}
                />
              </div>
              {isSuperAdmin && (
                <div className="form-group">
                  <label htmlFor="employee-role">Rol inicial</label>
                  <select id="employee-role" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
                    <option value="EMPLOYEE">Empleado</option>
                    <option value="ADMIN">Administrador</option>
                    <option value="SUPER_ADMIN">Super administrador</option>
                  </select>
                </div>
              )}
              <div className="form-actions">
                <button className="btn btn-secondary" type="button" onClick={() => setFormOpen(false)}>Cancelar</button>
                <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? "Creando…" : "Crear empleado"}</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

export default Employees;
