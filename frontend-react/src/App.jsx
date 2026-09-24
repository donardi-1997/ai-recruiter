import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import Login from "./auth/Login";
import Layout from "./components/Layout";
import { ThemeProvider } from "./context/ThemeContext";
import { SessionProvider, useSession } from "./context/SessionContext";

import Dashboard from "./pages/Dashboard";
import Jobs from "./pages/Jobs";
import Candidates from "./pages/Candidates";
import Ranking from "./pages/Ranking";
import CandidateDetail from "./pages/CandidateDetail";
import Integrations from "./pages/Integrations";
import Employees from "./pages/Employees";
import Training from "./pages/Training";
import EmployeeScores from "./pages/EmployeeScores";


function ProtectedRoute({ children, permission }) {
  const { status, hasPermission } = useSession();

  if (status === "loading") {
    return <div className="session-loading"><span aria-hidden="true" />Validando acceso seguro…</div>;
  }

  if (status !== "authenticated") {
    return <Navigate to="/login" replace />;
  }

  if (permission && !hasPermission(permission)) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}


function ProtectedPage({ children, permission }) {
  return (
    <ProtectedRoute permission={permission}>
      <Layout>{children}</Layout>
    </ProtectedRoute>
  );
}


function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route path="/dashboard" element={<ProtectedPage><Dashboard /></ProtectedPage>} />
      <Route path="/training" element={<ProtectedPage permission="training.read"><Training /></ProtectedPage>} />
      <Route path="/employees" element={<ProtectedPage permission="employees.read"><Employees /></ProtectedPage>} />
      <Route path="/direction/scores" element={<ProtectedPage permission="employee_scores.read"><EmployeeScores /></ProtectedPage>} />
      <Route path="/jobs" element={<ProtectedPage permission="jobs.read"><Jobs /></ProtectedPage>} />
      <Route path="/candidates" element={<ProtectedPage permission="candidates.read"><Candidates /></ProtectedPage>} />
      <Route path="/ranking" element={<ProtectedPage permission="ranking.read"><Ranking /></ProtectedPage>} />
      <Route path="/integrations" element={<ProtectedPage permission="integrations.manage"><Integrations /></ProtectedPage>} />
      <Route
        path="/candidates/:candidate_id"
        element={<ProtectedPage permission="candidates.read"><CandidateDetail /></ProtectedPage>}
      />

      <Route path="/register" element={<Navigate to="/login" replace />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}


function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <SessionProvider>
          <AppRoutes />
        </SessionProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
