import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import api from "../api/client";

function Login() {
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();

    setError("");
    setLoading(true);

    try {
      const response = await api.post("/auth/login", null, {
        params: {
          email,
          password,
        },
      });

      localStorage.setItem("access_token", response.data.access_token);

      localStorage.setItem("id_token", response.data.id_token);

      localStorage.setItem("refresh_token", response.data.refresh_token);

      navigate("/dashboard");
    } catch (err) {
      console.error(err);

      setError(
        err.response?.data?.detail ||
          err.response?.data?.error ||
          "Correo o contraseña incorrectos.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        {/* LOGO */}

        <div className="login-logo">AI</div>

        {/* HEADER */}

        <div className="login-header">
          <h1>Welcome back</h1>

          <p>Inicia sesión en AI Recruiter</p>
        </div>

        {/* FORM */}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Email</label>

            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="tu@email.com"
              autoComplete="email"
              required
            />
          </div>

          <div className="form-group">
            <div className="password-label">
              <label>Contraseña</label>
            </div>

            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="login-button" disabled={loading}>
            {loading ? "Iniciando sesión..." : "Iniciar sesión"}
          </button>
        </form>

        {/* REGISTER */}

        <div className="login-register">
          <span>¿No tienes una cuenta?</span>

          <Link to="/register">Crear cuenta</Link>
        </div>

        {/* FOOTER */}

        <div className="login-footer">
          <span>AI Recruiter · Talent Intelligence</span>

          <div className="login-author">
            Built & designed by <strong>Adrián Felipe Guerra</strong>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Login;
