import { useState } from "react";
import { useNavigate, Link, useSearchParams } from "react-router-dom";
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

  async function handleSubmit(e) {
    e.preventDefault();

    setError("");

    if (password !== confirmPassword) {
      setError("Las contraseñas no coinciden.");
      return;
    }

    setLoading(true);

    try {
      const response = await api.post("/auth/register", null, {
        params: {
          email,
          password,
        },
      });

      console.log("REGISTER RESPONSE:", response.data);

      // ======================================================
      // CUENTA CREADA
      // IR AUTOMÁTICAMENTE AL LOGIN
      // ======================================================

      navigate("/login", {
        replace: true,
      });
    } catch (err) {
      console.error("REGISTER ERROR:", err);

      setError(
        err.response?.data?.detail ||
          err.response?.data?.error ||
          "No fue posible crear la cuenta.",
      );
    } finally {
      setLoading(false);
    }
  }

  // ==========================================================
  // CUENTA CREADA
  // ==========================================================

  if (accountCreated) {
    return (
      <div className="login-page">
        <div className="login-card">
          <div className="login-logo">AI</div>

          <div className="login-header">
            <div
              style={{
                fontSize: "64px",
                marginBottom: "10px",
              }}
            >
              ✓
            </div>

            <h1>¡Cuenta creada!</h1>

            <p>Tu cuenta de AI Recruiter fue creada correctamente.</p>
          </div>

          {/* ==================================================
              LOGIN BUTTON
          ================================================== */}

          <button
            type="button"
            className="login-button"
            style={{
              marginTop: "24px",
            }}
            onClick={() => navigate("/login")}
          >
            Iniciar sesión
          </button>

          <div
            className="login-register"
            style={{
              marginTop: "18px",
            }}
          >
            <span>¿Quieres usar otro correo?</span>

            <Link to="/register">Crear otra cuenta</Link>
          </div>

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

  // ==========================================================
  // REGISTER FORM
  // ==========================================================

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">AI</div>

        <div className="login-header">
          <h1>Crear cuenta</h1>

          <p>Regístrate en AI Recruiter</p>
        </div>

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
            <label>Contraseña</label>

            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
              required
            />
          </div>

          <div className="form-group">
            <label>Confirmar contraseña</label>

            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
              required
            />
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="login-button" disabled={loading}>
            {loading ? "Creando cuenta..." : "Crear cuenta"}
          </button>
        </form>

        <div className="login-register">
          <span>¿Ya tienes una cuenta?</span>

          <Link to="/login">Iniciar sesión</Link>
        </div>

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

export default Register;
