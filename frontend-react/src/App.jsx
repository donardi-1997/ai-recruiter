import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";

import Login from "./auth/Login";

import Dashboard from "./pages/Dashboard";
import Jobs from "./pages/Jobs";
import Candidates from "./pages/Candidates";
import Ranking from "./pages/Ranking";
import CandidateDetail from "./pages/CandidateDetail";
import Integrations from "./pages/Integrations";

import Layout from "./components/Layout";
import Register from "./auth/Register";

import api, { clearAccessToken, getAccessToken, refreshAccessToken } from "./api/client";
import { ThemeProvider } from "./context/ThemeContext";

function ProtectedRoute({ children }) {
  const [checking, setChecking] = useState(true);
  const [valid, setValid] = useState(false);

  useEffect(() => {
    async function checkAuth() {
      let token = getAccessToken();

      if (!token) {
        try {
          token = await refreshAccessToken();
        } catch {
          setValid(false);
          setChecking(false);
          return;
        }
      }

      try {
        await api.get("/auth/me");
        setValid(true);
      } catch {
        clearAccessToken();
        setValid(false);
      } finally {
        setChecking(false);
      }
    }

    checkAuth();
  }, []);

  if (checking) {
    return <div className="session-loading"><span aria-hidden="true" />Validando acceso seguro…</div>;
  }

  if (!valid) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

function ProtectedPage({ children }) {
  return (
    <ProtectedRoute>
      <Layout>{children}</Layout>
    </ProtectedRoute>
  );
}

function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />

          <Route path="/dashboard" element={<ProtectedPage><Dashboard /></ProtectedPage>} />
          <Route path="/jobs" element={<ProtectedPage><Jobs /></ProtectedPage>} />
          <Route path="/candidates" element={<ProtectedPage><Candidates /></ProtectedPage>} />
          <Route path="/ranking" element={<ProtectedPage><Ranking /></ProtectedPage>} />
          <Route path="/integrations" element={<ProtectedPage><Integrations /></ProtectedPage>} />
          <Route
            path="/candidates/:candidate_id"
            element={<ProtectedPage><CandidateDetail /></ProtectedPage>}
          />

          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
