import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../api/client";

function AuthBrand() {
  return (
    <div className="auth-brand">
      <span className="auth-logo" aria-hidden="true">AI</span>
      <span><strong>AI Recruiter</strong><small>Talent intelligence</small></span>
    </div>
  );
}

function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const { data } = await api.post("/auth/login", { email, password });
      localStorage.setItem("access_token", data.access_token);
      localStorage.setItem("id_token", data.id_token);
      localStorage.setItem("refresh_token", data.refresh_token);
      navigate("/dashboard");
    } catch (err) {
      setError(
        Array.isArray(err.response?.data?.detail)
          ? err.response.data.detail.map((item) => item.msg).join(", ")
          : err.response?.data?.detail || "Correo o contraseña incorrectos.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-story" aria-label="Presentación de AI Recruiter">
        <AuthBrand />
        <div className="auth-story-content">
          <span className="eyebrow eyebrow-dark"><i /> Inteligencia para tu proceso de selección</span>
          <h1>Convierte cada CV en una <em>decisión clara.</em></h1>
          <p>Centraliza candidatos, evalúa afinidad con IA y prioriza el talento que realmente encaja con cada vacante.</p>

          <div className="auth-proof">
            <div><strong>01</strong><span>Sube perfiles</span></div>
            <div><strong>02</strong><span>Evalúa con IA</span></div>
            <div><strong>03</strong><span>Decide mejor</span></div>
          </div>
        </div>
        <div className="auth-signal" aria-hidden="true">
          <span className="signal-ring signal-ring-one" />
          <span className="signal-ring signal-ring-two" />
          <span className="signal-core">94<small>% match</small></span>
        </div>
        <p className="auth-story-footer">Powered by AWS · Amazon Bedrock</p>
      </section>

      <section className="auth-panel">
        <div className="auth-mobile-brand"><AuthBrand /></div>
        <div className="auth-card">
          <div className="auth-heading">
            <span className="eyebrow">Acceso seguro</span>
            <h2>Bienvenido de nuevo</h2>
            <p>Ingresa a tu espacio de selección.</p>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="email">Correo electrónico</label>
              <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="nombre@empresa.com" autoComplete="email" required />
            </div>
            <div className="form-group">
              <label htmlFor="password">Contraseña</label>
              <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Ingresa tu contraseña" autoComplete="current-password" required />
            </div>

            {error && <div className="login-error" role="alert">{error}</div>}

            <button type="submit" className="login-button" disabled={loading}>
              {loading ? "Verificando acceso…" : "Iniciar sesión"}
              {!loading && <span aria-hidden="true">→</span>}
            </button>
          </form>

          <p className="login-register">¿Aún no tienes una cuenta? <Link to="/register">Crear cuenta</Link></p>
          <p className="auth-security"><span aria-hidden="true">●</span> Tus datos están protegidos por AWS Cognito</p>
        </div>
      </section>
    </main>
  );
}

export default Login;
