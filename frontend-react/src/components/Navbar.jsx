import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import api from "../api/client";
import { useSession } from "../context/SessionContext";
import BrandMark from "./BrandMark";
import ThemeToggle from "./ThemeToggle";


const navItems = [
  { to: "/dashboard", label: "Inicio", icon: "⌁" },
  { to: "/jobs", label: "Vacantes", icon: "▤", permission: "jobs.read" },
  { to: "/candidates", label: "Candidatos", icon: "◎", permission: "candidates.read" },
  { to: "/ranking", label: "Ranking IA", icon: "↗", permission: "ranking.read" },
  { to: "/employees", label: "Empleados", icon: "◫", permission: "employees.read" },
  { to: "/direction/scores", label: "Calificación", icon: "★", permission: "employee_scores.read" },
  { to: "/training", label: "Capacitación", icon: "▶", permission: "training.read" },
  { to: "/integrations", label: "Integraciones", icon: "◇", permission: "integrations.manage" },
];


function Brand() {
  return (
    <NavLink to="/dashboard" className="navbar-brand" aria-label="ASIATI Talent Intelligence, inicio">
      <BrandMark />
    </NavLink>
  );
}


function roleLabel(roles = []) {
  if (roles.includes("SUPER_ADMIN")) return "Dirección";
  if (roles.includes("ADMIN")) return "Administración";
  return "Empleado";
}


function Navbar() {
  const navigate = useNavigate();
  const { principal, hasPermission, clearSession } = useSession();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function closeOnEscape(event) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  async function logout() {
    await api.post("/auth/logout").catch(() => {});
    clearSession();
    navigate("/login");
  }

  const visibleItems = navItems.filter(
    (item) => !item.permission || hasPermission(item.permission),
  );
  const profile = principal?.profile || {};
  const displayName = [profile.first_name, profile.last_name].filter(Boolean).join(" ")
    || principal?.email
    || "Usuario ASIATI";

  return (
    <>
      <header className="mobile-header">
        <Brand />
        <button
          className="menu-toggle"
          type="button"
          aria-expanded={open}
          aria-controls="primary-navigation"
          aria-label={open ? "Cerrar menú" : "Abrir menú"}
          onClick={() => setOpen((value) => !value)}
        >
          <span />
          <span />
        </button>
      </header>

      {open && <button className="nav-backdrop" aria-label="Cerrar menú" onClick={() => setOpen(false)} />}

      <aside className={`navbar ${open ? "is-open" : ""}`}>
        <div className="navbar-inner">
          <Brand />

          <div className="nav-context">
            <span className="nav-context-label">{roleLabel(principal?.roles)}</span>
            <strong>{displayName}</strong>
          </div>

          <nav id="primary-navigation" className="navbar-links" aria-label="Navegación principal">
            {visibleItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setOpen(false)}
                className={({ isActive }) => `navbar-link ${isActive ? "active" : ""}`}
              >
                <span className="navbar-icon" aria-hidden="true">{item.icon}</span>
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="nav-insight">
            <span className="nav-insight-dot" aria-hidden="true" />
            <div>
              <strong>{hasPermission("jobs.read") ? "Gestión de talento" : "Tu espacio ASIATI"}</strong>
              <span>{hasPermission("jobs.read") ? "Selección y capacitación" : "Capacitación y progreso"}</span>
            </div>
          </div>

          <div className="navbar-bottom-actions">
            <ThemeToggle />
            <button className="navbar-logout" onClick={logout}>
              <span aria-hidden="true">↪</span>
              <span>Cerrar sesión</span>
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

export default Navbar;
