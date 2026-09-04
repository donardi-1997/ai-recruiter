import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import api from "../api/client";

const navItems = [
  { to: "/dashboard", label: "Resumen", icon: "⌁" },
  { to: "/jobs", label: "Vacantes", icon: "▤" },
  { to: "/candidates", label: "Candidatos", icon: "◎" },
  { to: "/ranking", label: "Ranking IA", icon: "↗" },
];

function Brand() {
  return (
    <NavLink to="/dashboard" className="navbar-brand" aria-label="AI Recruiter, inicio">
      <span className="navbar-logo" aria-hidden="true">AI</span>
      <span className="navbar-brand-text">
        <strong>AI Recruiter</strong>
        <span>Talent intelligence</span>
      </span>
    </NavLink>
  );
}

function Navbar() {
  const navigate = useNavigate();
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
    localStorage.removeItem("access_token");
    localStorage.removeItem("id_token");
    localStorage.removeItem("refresh_token");

    navigate("/login");
  }

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
            <span className="nav-context-label">Workspace</span>
            <strong>Selección de talento</strong>
          </div>

          <nav id="primary-navigation" className="navbar-links" aria-label="Navegación principal">
          {navItems.map((item) => (
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
              <strong>IA operativa</strong>
              <span>Evaluación con Amazon Bedrock</span>
            </div>
          </div>

          <button className="navbar-logout" onClick={logout}>
            <span aria-hidden="true">↪</span>
            <span>Cerrar sesión</span>
          </button>
        </div>
      </aside>
    </>
  );
}

export default Navbar;
