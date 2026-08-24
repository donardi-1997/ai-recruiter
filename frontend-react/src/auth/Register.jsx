import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import api from "../api/client";

function Register() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const accountCreated = searchParams.get("created") === "true";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/register", null, { params: { email, password } });
      navigate("/login", { replace: true });
    } catch (err) {
      setError(err.response?.data?.detail || err.response?.data?.error || "No fue posible crear la cuenta.");
    } finally {
      setLoading(false);
    }
  }

  if (accountCreated) {
    return (
      <main className="auth-page auth-page-simple">
        <section className="auth-panel">
          <div className="auth-card auth-success-card">
            <span className="success-mark" aria-hidden="true">✓</span>
            <span className="eyebrow">Registro completo</span>
            <h1>Tu cuenta está lista</h1>
            <p>Ya puedes acceder a AI Recruiter y comenzar a organizar tu proceso de selección.</p>
            <button type="button" className="login-button" onClick={() => navigate("/login")}>Iniciar sesión <span>→</span></button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-page auth-register-page">
      <section className="auth-story auth-register-story">
        <div className="auth-brand">
          <span className="auth-logo" aria-hidden="true">AI</span>
          <span><strong>AI Recruiter</strong><small>Talent intelligence</small></span>
        </div>
        <div className="auth-story-content">
          <span className="eyebrow eyebrow-dark"><i /> Empieza en minutos</span>
          <h1>Una forma más inteligente de <em>encontrar talento.</em></h1>
          <ul className="auth-benefits">
            <li><span>01</span><div><strong>Evaluación consistente</strong><small>Compara perfiles con criterios claros.</small></div></li>
            <li><span>02</span><div><strong>Ranking accionable</strong><small>Prioriza a los candidatos con mejor ajuste.</small></div></li>
            <li><span>03</span><div><strong>Infraestructura segura</strong><small>Construido sobre servicios administrados de AWS.</small></div></li>
          </ul>
        </div>
        <p className="auth-story-footer">AI Recruiter · Talent intelligence</p>
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <div className="auth-heading">
            <span className="eyebrow">Nuevo workspace</span>
            <h2>Crea tu cuenta</h2>
            <p>Configura tu acceso para comenzar.</p>
          </div>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="register-email">Correo electrónico</label>
              <input id="register-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="nombre@empresa.com" autoComplete="email" required />
            </div>
            <div className="form-group">
              <label htmlFor="register-password">Contraseña</label>
              <input id="register-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Mínimo 8 caracteres" autoComplete="new-password" required />
            </div>
            <div className="form-group">
              <label htmlFor="confirm-password">Confirmar contraseña</label>
              <input id="confirm-password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Repite tu contraseña" autoComplete="new-password" required />
            </div>
            {error && <div className="login-error" role="alert">{error}</div>}
            <button type="submit" className="login-button" disabled={loading}>{loading ? "Creando cuenta…" : "Crear cuenta"}<span aria-hidden="true">→</span></button>
          </form>
          <p className="login-register">¿Ya tienes una cuenta? <Link to="/login">Iniciar sesión</Link></p>
        </div>
      </section>
    </main>
  );
}

export default Register;
