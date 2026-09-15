import { useTheme } from "../context/ThemeContext";

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={toggleTheme}
      aria-label={theme === "light" ? "Cambiar a modo oscuro" : "Cambiar a modo claro"}
      title={theme === "light" ? "Modo oscuro" : "Modo claro"}
    >
      <span className="theme-toggle-icon" aria-hidden="true">
        {theme === "light" ? "◐" : "◑"}
      </span>
    </button>
  );
}

export default ThemeToggle;
