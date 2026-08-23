import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import api from "../api/client";

function Register() {
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();

    setError("");
    setSuccess("");

    if (password !== confirmPassword) {
      setError("Las contraseñas no coinciden.");
      return;
    }

    if (password.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres.");
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

      setSuccess(
        response.data?.message ||
          "Cuenta creada correctamente. Revisa tu correo para confirmar la cuenta.",
      );

      setTimeout(() => {
        navigate("/login");
      }, 2500);
    } catch (err) {
      console.error(err);

      setError(
        err.response?.data?.detail ||
          err.response?.data?.error ||
          "No fue posible crear la cuenta.",
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
          <h1>Create account</h1>

          <p>Crea tu cuenta en AI Recruiter</p>
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

          {success && <div className="login-success">{success}</div>}

          <button type="submit" className="login-button" disabled={loading}>
            {loading ? "Creando cuenta..." : "Crear cuenta"}
          </button>
        </form>

        {/* LOGIN */}

        <div className="login-register">
          <span>¿Ya tienes una cuenta?</span>

          <Link to="/login">Iniciar sesión</Link>
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

export default Register;
