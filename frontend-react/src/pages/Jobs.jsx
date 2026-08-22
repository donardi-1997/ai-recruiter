import { useEffect, useState } from "react";
import api from "../api/client";

function Jobs() {
  const [jobs, setJobs] = useState([]);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const [editingJob, setEditingJob] = useState(null);

  const [showForm, setShowForm] = useState(false);

  const [error, setError] = useState("");

  const [saving, setSaving] = useState(false);

  async function loadJobs() {
    try {
      const response = await api.get("/jobs");

      console.log("API JOBS:", response.data);

      const data = response.data;

      if (Array.isArray(data)) {
        setJobs(data);
      } else if (Array.isArray(data.jobs)) {
        setJobs(data.jobs);
      } else {
        setJobs([]);
      }
    } catch (error) {
      console.error("ERROR CARGANDO JOBS:", error);

      console.error("STATUS:", error.response?.status);

      console.error("DATA:", error.response?.data);

      setJobs([]);

      setError(
        error.response?.data?.detail ||
          error.response?.data?.error ||
          "Error cargando vacantes",
      );
    }
  }

  useEffect(() => {
    loadJobs();
  }, []);

  async function saveJob(e) {
    e.preventDefault();

    setError("");
    setSaving(true);

    try {
      let response;

      if (editingJob) {
        console.log("ACTUALIZANDO JOB:", editingJob);

        response = await api.put(`/jobs/${editingJob}`, {
          title,
          description,
        });
      } else {
        console.log("CREANDO JOB:", {
          title,
          description,
        });

        response = await api.post("/jobs", {
          title,
          description,
        });
      }

      console.log("JOB SAVE RESPONSE:", response.data);

      setTitle("");
      setDescription("");
      setEditingJob(null);
      setShowForm(false);

      await loadJobs();
    } catch (err) {
      console.error("=================================");

      console.error("ERROR GUARDANDO JOB");

      console.error("=================================");

      console.error("STATUS:", err.response?.status);

      console.error("DATA:", err.response?.data);

      console.error("HEADERS:", err.response?.headers);

      console.error("MESSAGE:", err.message);

      console.error("FULL ERROR:", err);

      setError(
        err.response?.data?.detail ||
          err.response?.data?.error ||
          `Error guardando vacante (${err.response?.status || "sin respuesta"})`,
      );
    } finally {
      setSaving(false);
    }
  }

  async function deleteJob(id) {
    try {
      setError("");

      await api.delete(`/jobs/${id}`);

      await loadJobs();
    } catch (err) {
      console.error("ERROR ELIMINANDO JOB:", err);

      console.error("STATUS:", err.response?.status);

      console.error("DATA:", err.response?.data);

      setError(
        err.response?.data?.detail ||
          err.response?.data?.error ||
          "Error eliminando vacante",
      );
    }
  }

  function editJob(job) {
    setEditingJob(job.job_id);

    setTitle(job.title);

    setDescription(job.description);

    setError("");

    setShowForm(true);
  }

  function cancelForm() {
    setTitle("");

    setDescription("");

    setEditingJob(null);

    setShowForm(false);

    setError("");
  }

  return (
    <div
      style={{
        padding: "40px",
      }}
    >
      <h1>Vacantes</h1>

      {error && (
        <div
          style={{
            color: "#991b1b",
            background: "#fee2e2",
            border: "1px solid #fecaca",
            padding: "12px",
            borderRadius: "8px",
            marginBottom: "20px",
          }}
        >
          <strong>Error:</strong> {error}
        </div>
      )}

      <button
        onClick={() => {
          if (showForm) {
            cancelForm();
          } else {
            setEditingJob(null);

            setTitle("");

            setDescription("");

            setError("");

            setShowForm(true);
          }
        }}
      >
        {showForm ? "Cancelar" : "Nueva vacante"}
      </button>

      {showForm && (
        <form
          onSubmit={saveJob}
          style={{
            marginTop: "20px",
            marginBottom: "30px",
          }}
        >
          <input
            placeholder="Título"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />

          <br />
          <br />

          <textarea
            placeholder="Descripción"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />

          <br />
          <br />

          <button type="submit" disabled={saving}>
            {saving ? "Guardando..." : editingJob ? "Actualizar" : "Crear"}
          </button>
        </form>
      )}

      <hr />

      {jobs.map((job) => (
        <div
          key={job.job_id}
          style={{
            border: "1px solid #ddd",
            padding: "15px",
            margin: "15px 0",
            borderRadius: "8px",
          }}
        >
          <h3>{job.title}</h3>
          <p>{job.description}</p>
          <button onClick={() => editJob(job)}>Editar</button>{" "}
          <button onClick={() => deleteJob(job.job_id)}>Eliminar</button>
        </div>
      ))}
    </div>
  );
}

export default Jobs;
