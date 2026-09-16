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

const PROPOSAL = {
  improved_description: "Diseña y opera plataformas cloud seguras y medibles.",
  required_technologies: ["AWS"],
  preferred_technologies: ["Terraform"],
  required_certifications: [],
  preferred_certifications: ["AWS Solutions Architect"],
  minimum_years_experience: 3,
  specific_experience: ["Infraestructura como código"],
  responsibilities: ["Operar infraestructura cloud"],
  domain_knowledge: ["Cloud operations"],
  education: [],
  languages: ["Inglés deseable"],
  technical_competencies: ["Observabilidad"],
  assumptions_to_validate: ["Confirmar si EKS forma parte del stack"],
};

function renderJobs() {
  return render(
    <MemoryRouter>
      <Jobs />
    </MemoryRouter>
  );
}

describe("Jobs AI enrichment", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/jobs") {
        return Promise.resolve({
          data: [
            {
              job_id: "job-1",
              title: "Existing Cloud Engineer",
              description: "Existing description",
              candidate_count: 2,
              evaluation_version: 1,
              evaluation_profile: {},
              created_at: "2026-09-01T10:00:00Z",
            },
          ],
        });
      }
      return Promise.resolve({ data: [] });
    });
    api.post.mockImplementation((url) => {
      if (url === "/jobs/enrich") {
        return Promise.resolve({
          data: { company_context_version: 1, proposal: PROPOSAL },
        });
      }
      if (url === "/jobs") return Promise.resolve({ data: { job_id: "job-new" } });
      return Promise.resolve({ data: {} });
    });
    api.put.mockResolvedValue({ data: {} });
  });

  it("shows optional enrichment only when creating a vacancy", async () => {
    renderJobs();
    await screen.findByText("Existing Cloud Engineer");

    fireEvent.click(screen.getByRole("button", { name: /nueva vacante/i }));
    expect(screen.getByRole("button", { name: /enriquecer con ia/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /cerrar formulario/i }));
    fireEvent.click(screen.getByText("Editar"));
    expect(screen.queryByRole("button", { name: /enriquecer con ia/i })).not.toBeInTheDocument();
  });

  it("enriches the current draft and previews before applying", async () => {
    renderJobs();
    await screen.findByText("Existing Cloud Engineer");
    fireEvent.click(screen.getByRole("button", { name: /nueva vacante/i }));

    fireEvent.change(screen.getByLabelText("Título de la vacante"), {
      target: { value: "Cloud Engineer" },
    });
    fireEvent.change(screen.getByLabelText("Descripción y requisitos"), {
      target: { value: "Necesitamos apoyo con AWS." },
    });
    fireEvent.change(screen.getByLabelText("País (ISO)"), { target: { value: "CO" } });
    fireEvent.change(screen.getByLabelText("Ciudad"), { target: { value: "Bogotá" } });

    fireEvent.click(screen.getByRole("button", { name: /enriquecer con ia/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/jobs/enrich", {
        title: "Cloud Engineer",
        description: "Necesitamos apoyo con AWS.",
        country_code: "CO",
        city: "Bogotá",
        employment_type: null,
        evaluation_profile: null,
      });
    });
    expect(await screen.findByText("Propuesta de IA")).toBeInTheDocument();
    expect(screen.getByText("AWS")).toBeInTheDocument();
    expect(screen.getByText("Confirmar si EKS forma parte del stack")).toBeInTheDocument();
    expect(screen.getByLabelText("Descripción y requisitos")).toHaveValue("Necesitamos apoyo con AWS.");
    expect(api.post).not.toHaveBeenCalledWith("/jobs", expect.anything());
  });

  it("applies proposal locally and persists only when Crear vacante is clicked", async () => {
    renderJobs();
    await screen.findByText("Existing Cloud Engineer");
    fireEvent.click(screen.getByRole("button", { name: /nueva vacante/i }));
    fireEvent.change(screen.getByLabelText("Título de la vacante"), {
      target: { value: "Cloud Engineer" },
    });

    fireEvent.click(screen.getByRole("button", { name: /enriquecer con ia/i }));
    await screen.findByText("Propuesta de IA");
    fireEvent.click(screen.getByRole("button", { name: /aplicar propuesta/i }));

    expect(screen.getByLabelText("Descripción y requisitos")).toHaveValue(PROPOSAL.improved_description);
    expect(api.post).not.toHaveBeenCalledWith("/jobs", expect.anything());

    fireEvent.click(screen.getByRole("button", { name: /crear vacante/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs",
        expect.objectContaining({
          title: "Cloud Engineer",
          description: PROPOSAL.improved_description,
          evaluation_profile: expect.objectContaining({
            required_technologies: ["AWS"],
            preferred_technologies: ["Terraform"],
            assumptions_to_validate: ["Confirmar si EKS forma parte del stack"],
          }),
        })
      );
    });
  });

  it("enrichment failure preserves recruiter draft", async () => {
    api.post.mockImplementation((url) => {
      if (url === "/jobs/enrich") {
        return Promise.reject({ response: { data: { detail: "No fue posible enriquecer." } } });
      }
      return Promise.resolve({ data: {} });
    });

    renderJobs();
    await screen.findByText("Existing Cloud Engineer");
    fireEvent.click(screen.getByRole("button", { name: /nueva vacante/i }));
    fireEvent.change(screen.getByLabelText("Título de la vacante"), {
      target: { value: "Operations Manager" },
    });
    fireEvent.change(screen.getByLabelText("Descripción y requisitos"), {
      target: { value: "Mi borrador original" },
    });

    fireEvent.click(screen.getByRole("button", { name: /enriquecer con ia/i }));

    expect(await screen.findByText("No fue posible enriquecer.")).toBeInTheDocument();
    expect(screen.getByLabelText("Descripción y requisitos")).toHaveValue("Mi borrador original");
  });

  it("shows a non-blocking reevaluation notice when editing a job with candidates", async () => {
    renderJobs();
    await screen.findByText("Existing Cloud Engineer");

    fireEvent.click(screen.getByText("Editar"));

    expect(screen.getByRole("note")).toHaveTextContent("Esta vacante tiene candidatos evaluados.");
    expect(screen.getByRole("note")).toHaveTextContent(
      "Los cambios en el perfil harán que sus evaluaciones se actualicen automáticamente."
    );
    expect(screen.getByRole("button", { name: /guardar cambios/i })).toBeEnabled();
  });

  it("shows pending reevaluation feedback after an evaluation-relevant edit", async () => {
    api.put.mockResolvedValueOnce({
      data: {
        evaluation_changed: true,
        reevaluation_scheduled: true,
        reevaluation_candidate_count: 2,
      },
    });
    renderJobs();
    await screen.findByText("Existing Cloud Engineer");

    fireEvent.click(screen.getByText("Editar"));
    fireEvent.change(screen.getByLabelText("Descripción y requisitos"), {
      target: { value: "Updated AWS platform requirements" },
    });
    fireEvent.click(screen.getByRole("button", { name: /guardar cambios/i }));

    expect(await screen.findByText("Perfil actualizado · reevaluación de 2 candidatos pendiente")).toBeInTheDocument();
  });
});
