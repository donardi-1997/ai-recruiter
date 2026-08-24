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

    console.log("=================================");
    console.log("🚀 INICIO LOGIN");
    console.log("Email:", email);
    console.log("Password:", password);
    console.log("=================================");

    try {
      console.log("📡 Enviando POST /auth/login");

      const response = await api.post("/auth/login", {
        email,
        password,
      });

      console.log("✅ LOGIN RESPONSE STATUS:");
      console.log(response.status);

      console.log("✅ LOGIN RESPONSE DATA:");
      console.log(response.data);

      console.log("🔑 ACCESS TOKEN:");
      console.log(response.data.access_token);

      localStorage.setItem("access_token", response.data.access_token);

      localStorage.setItem("id_token", response.data.id_token);

      localStorage.setItem("refresh_token", response.data.refresh_token);

      console.log("💾 TOKENS GUARDADOS EN LOCALSTORAGE");

      console.log(
        "ACCESS TOKEN STORAGE:",
        localStorage.getItem("access_token"),
      );

      console.log("➡️ Navegando a dashboard");

      navigate("/dashboard");
    } catch (err) {
      console.error("❌ ERROR LOGIN");
      console.error(err);

      console.log("STATUS ERROR:");
      console.log(err.response?.status);

      console.log("DATA ERROR:");
      console.log(err.response?.data);

      console.log("URL ERROR:");
      console.log(err.config?.url);

      console.log("BODY ENVIADO:");
      console.log(err.config?.data);

      setError(
        Array.isArray(err.response?.data?.detail)
          ? err.response.data.detail.map((e) => e.msg).join(", ")
          : err.response?.data?.detail || "Correo o contraseña incorrectos.",
      );
    } finally {
      console.log("🏁 FIN LOGIN");

      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">AI</div>

        <div className="login-header">
          <h1>Welcome back</h1>

          <p>Inicia sesión en AI Recruiter</p>
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
              autoComplete="current-password"
              required
            />
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="login-button" disabled={loading}>
            {loading ? "Iniciando sesión..." : "Iniciar sesión"}
          </button>
        </form>

        <div className="login-register">
          <span>¿No tienes una cuenta?</span>

          <Link to="/register">Crear cuenta</Link>
        </div>

        <div className="login-footer">
          <span>AI Recruiter · Talent Intelligence</span>

          <div className="login-author">
            Built & designed by
            <strong>Adrián Felipe Guerra</strong>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Login;
