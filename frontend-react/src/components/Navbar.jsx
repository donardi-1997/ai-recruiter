import { NavLink, useNavigate } from "react-router-dom";

function Navbar() {
  const navigate = useNavigate();

  function logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("id_token");
    localStorage.removeItem("refresh_token");

    navigate("/login");
  }

  const navItems = [
    {
      to: "/dashboard",
      label: "Dashboard",
      icon: "▦",
    },
    {
      to: "/jobs",
      label: "Vacantes",
      icon: "▤",
    },
    {
      to: "/candidates",
      label: "Candidatos",
      icon: "♙",
    },
    {
      to: "/ranking",
      label: "Ranking",
      icon: "↗",
    },
  ];

  return (
    <header className="navbar">
      <div className="navbar-inner">

        <NavLink to="/dashboard" className="navbar-brand">
          <div className="navbar-logo">
            AI
          </div>

          <div className="navbar-brand-text">
            <strong>AI Recruiter</strong>
            <span>Talent Intelligence</span>
          </div>
        </NavLink>

        <nav className="navbar-links">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `navbar-link ${isActive ? "active" : ""}`
              }
            >
              <span className="navbar-icon">
                {item.icon}
              </span>

              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <button
          className="navbar-logout"
          onClick={logout}
          title="Cerrar sesión"
        >
          <span>↪</span>
          <span>Cerrar sesión</span>
        </button>

      </div>
    </header>
  );
}

export default Navbar;
