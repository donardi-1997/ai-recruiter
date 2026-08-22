import { useEffect, useState } from "react";

import api from "../api/client";

function Dashboard() {
  const [jobs, setJobs] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const jobsResponse = await api.get("/jobs");
        const candidatesResponse = await api.get("/candidates");

        const jobsData = jobsResponse.data;
        const candidatesData = candidatesResponse.data;

        setJobs(Array.isArray(jobsData) ? jobsData : jobsData.jobs || []);

        setCandidates(
          Array.isArray(candidatesData)
            ? candidatesData
            : candidatesData.candidates || [],
        );
      } catch (error) {
        console.error("ERROR LOADING DASHBOARD:", error);
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  if (loading) {
    return <h2>Cargando dashboard...</h2>;
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>AI Recruiter Dashboard</h1>

        <p>Gestión inteligente de talento con IA</p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "20px",
          marginTop: "30px",
        }}
      >
        <Card title="Vacantes" value={jobs.length} />

        <Card title="Candidatos" value={candidates.length} />

        <Card title="Evaluaciones IA" value="0" />
      </div>

      <h2
        style={{
          marginTop: "40px",
          marginBottom: "20px",
          textAlign: "center",
        }}
      >
        Últimas vacantes
      </h2>

      {jobs.length === 0 ? (
        <p className="muted">No hay vacantes registradas.</p>
      ) : (
        jobs.map((job) => (
          <div key={job.job_id} className="card">
            <h3>{job.title}</h3>

            <p className="muted">{job.description}</p>
          </div>
        ))
      )}
    </div>
  );
}

function Card({ title, value }) {
  return (
    <div className="card">
      <h3>{title}</h3>

      <h1>{value}</h1>
    </div>
  );
}

export default Dashboard;
