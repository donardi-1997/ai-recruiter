// eslint-disable-next-line no-unused-vars
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Jobs from "../pages/Jobs";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from "../api/client";

const JOBS = [
  { job_id: "job-1", title: "Backend Developer", description: "Python APIs REST", candidate_count: 2, created_at: "2026-09-01T10:00:00Z" },
  { job_id: "job-2", title: "Frontend Developer", description: "React y TypeScript", candidate_count: 0, created_at: "2026-09-02T12:00:00Z" },
];

const CANDIDATES = [
  { candidate_id: "c-1", name: "Ana Pérez", email: "ana@test.com", filename: "Ana-Perez.pdf" },
  { candidate_id: "c-2", name: "Carlos Gómez", email: null, filename: null },
];

function renderJobs() {
  return render(
    <MemoryRouter>
      <Jobs />
    </MemoryRouter>
  );
}

describe("Jobs page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: JOBS });
      if (url === "/jobs/job-1/candidates") return Promise.resolve({ data: CANDIDATES });
      return Promise.resolve({ data: [] });
    });
    api.delete.mockResolvedValue({ data: { detail: "Vacante eliminada." } });
    api.post.mockResolvedValue({ data: {} });
    api.put.mockResolvedValue({ data: {} });
  });

  it("renders vacantes", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");
    expect(screen.getByText("Frontend Developer")).toBeInTheDocument();
  });

  it("each vacante has Ver, Agregar candidatos, Editar, Eliminar buttons", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");
    expect(screen.getByRole("button", { name: /ver/i })).toBeInTheDocument();
    expect(screen.getAllByText("Agregar candidatos").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Editar").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Eliminar").length).toBeGreaterThanOrEqual(1);
  });

  it("click Ver opens dialog with full job info", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Ver")[0]);

    await waitFor(() => {
      expect(screen.getByText("Información de la vacante")).toBeInTheDocument();
    });
    expect(screen.getByText("Descripción y requisitos")).toBeInTheDocument();
    expect(screen.getByText("Python APIs REST")).toBeInTheDocument();
    expect(screen.getByText("Candidatos asignados")).toBeInTheDocument();
  });

  it("Ver calls GET /jobs/job-1/candidates with page=1 page_size=100", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Ver")[0]);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/jobs/job-1/candidates", {
        params: { page: 1, page_size: 100 },
      });
    });
  });

  it("modal lists candidates Ana and Carlos", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Ver")[0]);

    await waitFor(() => {
      expect(screen.getByText("Ana Pérez")).toBeInTheDocument();
    });
    expect(screen.getByText("Carlos Gómez")).toBeInTheDocument();
  });

  it("vacante sin candidatos shows empty message", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: JOBS });
      if (url === "/jobs/job-2/candidates") return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });

    renderJobs();
    await screen.findByText("Frontend Developer");

    const verButtons = screen.getAllByText("Ver");
    fireEvent.click(verButtons[1]);

    await waitFor(() => {
      expect(screen.getByText("No hay candidatos asignados a esta vacante.")).toBeInTheDocument();
    });
  });

  it("candidates request failed shows error and Reintentar", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: JOBS });
      if (url === "/jobs/job-1/candidates") return Promise.reject(new Error("Network error"));
      return Promise.resolve({ data: [] });
    });

    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Ver")[0]);

    await waitFor(() => {
      expect(screen.getByText("No fue posible cargar los candidatos de esta vacante.")).toBeInTheDocument();
    });
    expect(screen.getByText("Reintentar")).toBeInTheDocument();
  });

  it("click Eliminar opens modal, does NOT call api.delete immediately", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);

    await waitFor(() => {
      expect(screen.getByText("¿qué deseas eliminar?")).toBeInTheDocument();
    });
    expect(api.delete).not.toHaveBeenCalled();
  });

  it("delete modal has exactly three options", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);

    await waitFor(() => {
      expect(screen.getByText("¿qué deseas eliminar?")).toBeInTheDocument();
    });
    expect(screen.getByText("Borrar solo la vacante")).toBeInTheDocument();
    expect(screen.getByText("Borrar vacante y candidatos")).toBeInTheDocument();
    expect(screen.getByText("Cancelar")).toBeInTheDocument();
  });

  it("Borrar solo la vacante calls api.delete with delete_candidates=false", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);

    await waitFor(() => {
      expect(screen.getByText("Borrar solo la vacante")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Borrar solo la vacante"));

    await waitFor(() => {
      expect(api.delete).toHaveBeenCalledWith("/jobs/job-1", { params: { delete_candidates: false } });
    });
  });

  it("Borrar vacante y candidatos calls api.delete with delete_candidates=true", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);

    await waitFor(() => {
      expect(screen.getByText("Borrar vacante y candidatos")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Borrar vacante y candidatos"));

    await waitFor(() => {
      expect(api.delete).toHaveBeenCalledWith("/jobs/job-1", { params: { delete_candidates: true } });
    });
  });

  it("Cancelar closes modal and does NOT call api.delete", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);

    await waitFor(() => {
      expect(screen.getByText("Cancelar")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Cancelar"));

    await waitFor(() => {
      expect(screen.queryByText("¿qué deseas eliminar?")).not.toBeInTheDocument();
    });
    expect(api.delete).not.toHaveBeenCalled();
  });

  it("during deleting, actions are disabled", async () => {
    let resolveDelete;
    api.delete.mockReturnValueOnce(new Promise((r) => { resolveDelete = r; }));

    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);
    await waitFor(() => { expect(screen.getByText("Borrar solo la vacante")).toBeInTheDocument(); });

    fireEvent.click(screen.getByText("Borrar solo la vacante"));

    await waitFor(() => {
      expect(screen.getByText("Eliminando…")).toBeInTheDocument();
    });
    expect(screen.getByText("Borrar solo la vacante")).toBeDisabled();
    expect(screen.getByText("Borrar vacante y candidatos")).toBeDisabled();
    expect(screen.getByText("Cancelar")).toBeDisabled();

    resolveDelete({ data: { detail: "Vacante eliminada." } });
  });

  it("error delete shows error in modal", async () => {
    api.delete.mockRejectedValueOnce({ response: { data: { detail: "Error al eliminar." } } });

    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);
    await waitFor(() => { expect(screen.getByText("Borrar solo la vacante")).toBeInTheDocument(); });

    fireEvent.click(screen.getByText("Borrar solo la vacante"));

    await waitFor(() => {
      expect(screen.getByText("Error al eliminar.")).toBeInTheDocument();
    });
    expect(screen.getByText("¿qué deseas eliminar?")).toBeInTheDocument();
  });

  it("success delete solo vacante: closes modal, refreshes list, shows message", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);
    await waitFor(() => { expect(screen.getByText("Borrar solo la vacante")).toBeInTheDocument(); });

    fireEvent.click(screen.getByText("Borrar solo la vacante"));

    await waitFor(() => {
      expect(screen.getByText("Vacante eliminada. Los candidatos se conservaron.")).toBeInTheDocument();
    });
    expect(screen.queryByText("¿qué deseas eliminar?")).not.toBeInTheDocument();
  });

  it("success delete con candidatos shows correct message", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);
    await waitFor(() => { expect(screen.getByText("Borrar vacante y candidatos")).toBeInTheDocument(); });

    fireEvent.click(screen.getByText("Borrar vacante y candidatos"));

    await waitFor(() => {
      expect(screen.getByText("Vacante y 2 candidatos eliminados.")).toBeInTheDocument();
    });
  });

  it("does not use window.confirm for job deletion", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Eliminar")[0]);
    await waitFor(() => {
      expect(screen.getByText("¿qué deseas eliminar?")).toBeInTheDocument();
    });

    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("detail modal closes with X button", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Ver")[0]);
    await waitFor(() => {
      expect(screen.getByText("Información de la vacante")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText("Cerrar detalle de vacante"));

    await waitFor(() => {
      expect(screen.queryByText("Información de la vacante")).not.toBeInTheDocument();
    });
  });

  it("detail modal has role=dialog and aria-modal=true", async () => {
    renderJobs();
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getAllByText("Ver")[0]);

    await waitFor(() => {
      const dialog = screen.getByRole("dialog", { name: /Backend Developer/i });
      expect(dialog).toBeInTheDocument();
      expect(dialog).toHaveAttribute("aria-modal", "true");
    });
  });
});
