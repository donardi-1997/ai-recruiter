import { useNavigate } from "react-router-dom";

function LogoutButton() {
  const navigate = useNavigate();

  function handleLogout() {
    // Eliminar tokens Cognito
    localStorage.removeItem("access_token");
    localStorage.removeItem("id_token");
    localStorage.removeItem("refresh_token");

    // Redirigir al login
    navigate("/login", { replace: true });
  }

  return (
    <button
      onClick={handleLogout}
      style={{
        padding: "8px 16px",
        cursor: "pointer",
      }}
    >
      Cerrar sesión
    </button>
  );
}

export default LogoutButton;
