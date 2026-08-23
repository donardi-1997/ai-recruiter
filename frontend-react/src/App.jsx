import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Login from "./auth/Login";

import Dashboard from "./pages/Dashboard";
import Jobs from "./pages/Jobs";
import Candidates from "./pages/Candidates";
import Ranking from "./pages/Ranking";
import CandidateDetail from "./pages/CandidateDetail";

import Layout from "./components/Layout";
import Register from "./auth/Register";

// ============================================================
// PROTECTED ROUTE
// ============================================================

function ProtectedRoute({ children }) {
  const token = localStorage.getItem("access_token");

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  return children;
}

// ============================================================
// APP
// ============================================================

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* ================================================== */}
        {/* PUBLIC */}
        {/* ================================================== */}

        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        {/* ================================================== */}
        {/* PROTECTED */}
        {/* ================================================== */}

        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <Layout>
                <Dashboard />
              </Layout>
            </ProtectedRoute>
          }
        />

        <Route
          path="/jobs"
          element={
            <ProtectedRoute>
              <Layout>
                <Jobs />
              </Layout>
            </ProtectedRoute>
          }
        />

        <Route
          path="/candidates"
          element={
            <ProtectedRoute>
              <Layout>
                <Candidates />
              </Layout>
            </ProtectedRoute>
          }
        />

        <Route
          path="/ranking"
          element={
            <ProtectedRoute>
              <Layout>
                <Ranking />
              </Layout>
            </ProtectedRoute>
          }
        />

        <Route
          path="/candidates/:candidate_id"
          element={
            <ProtectedRoute>
              <Layout>
                <CandidateDetail />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* ================================================== */}
        {/* FALLBACK */}
        {/* ================================================== */}

        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
