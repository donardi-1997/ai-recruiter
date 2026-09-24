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

const JOB = {
  job_id: "job-1",
  title: "Country Manager Chile",
  description: "Lead Asiati operations across Chile and grow the local business.",
  country_code: "CL",
  city: "Santiago",
  employment_type: "FULL_TIME",
  public_slug: "country-manager-chile",
  candidate_count: 1,
  created_at: "2026-09-15T10:00:00Z",
};

const CANDIDATE = {
  candidate_id: "candidate-1",
  name: "Ana Perez",
  email: "ana@example.com",
  filename: null,
  metadata: {
    source: "Indeed",
    source_name: "Indeed Smart Sourcing",
    resume_name: "ana-perez.pdf",
  },
};

function renderJobs() {
  return render(
    <MemoryRouter>
      <Jobs />
    </MemoryRouter>
  );
}

describe("Jobs Indeed integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/jobs/page") return Promise.resolve({
        data: {
          items: [JOB],
          page: 1,
          page_size: 12,
          total: 1,
          total_pages: 1,
        },
      });
      if (url === "/integrations/indeed/status") {
        return Promise.resolve({
          data: {
            enabled: true,
            configured: true,
            candidate_sync_available: true,
            disposition_sync_available: true,
          },
        });
      }
      if (url === "/jobs/job-1/candidates") return Promise.resolve({ data: [CANDIDATE] });
      if (url === "/jobs/job-1/integrations/indeed/status") {
        return Promise.reject({ response: { status: 404, data: { detail: "not published" } } });
      }
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValue({ data: {} });
    api.put.mockResolvedValue({ data: {} });
    api.delete.mockResolvedValue({ data: {} });
  });

  it("saves provider-neutral publication fields with a job", async () => {
    renderJobs();
    await screen.findByText("Country Manager Chile");

    fireEvent.click(screen.getByRole("button", { name: /nueva vacante/i }));
    fireEvent.change(screen.getByLabelText("Título de la vacante"), { target: { value: "KAM Colombia" } });
    fireEvent.change(screen.getByLabelText("Descripción y requisitos"), {
      target: { value: "Lead strategic accounts in Colombia with strong commercial ownership." },
    });
    fireEvent.change(screen.getByLabelText("País (ISO)"), { target: { value: "co" } });
    fireEvent.change(screen.getByLabelText("Ciudad"), { target: { value: "Bogotá" } });
    fireEvent.change(screen.getByLabelText("Tipo de empleo"), { target: { value: "FULL_TIME" } });
    fireEvent.change(screen.getByLabelText("URL pública"), { target: { value: "kam-colombia" } });
    fireEvent.click(screen.getByRole("button", { name: /crear vacante/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/jobs", {
        title: "KAM Colombia",
        description: "Lead strategic accounts in Colombia with strong commercial ownership.",
        indeed_description: "Lead strategic accounts in Colombia with strong commercial ownership.",
        ai_description: "",
        active_description_source: "indeed",
        country_code: "CO",
        city: "Bogotá",
        employment_type: "FULL_TIME",
        public_slug: "kam-colombia",
        evaluation_profile: null,
      });
    });
  });

  it("shows Indeed controls when the integration is configured", async () => {
    renderJobs();
    await screen.findByText("Country Manager Chile");
    fireEvent.click(screen.getByRole("button", { name: /^ver$/i }));

    await screen.findByText("Indeed Employers");
    expect(screen.getByText("Conectado")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /publicar en indeed/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sincronizar candidatos/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sincronizar estados/i })).toBeInTheDocument();
  });

  it("publishes the selected job through the Indeed endpoint", async () => {
    api.post.mockImplementation((url) => {
      if (url === "/jobs/job-1/integrations/indeed/publish") {
        return Promise.resolve({ data: { sourced_posting_id: "sourced-1", employer_job_id: "employer-job-1" } });
      }
      return Promise.resolve({ data: {} });
    });

    renderJobs();
    await screen.findByText("Country Manager Chile");
    fireEvent.click(screen.getByRole("button", { name: /^ver$/i }));
    await screen.findByRole("button", { name: /publicar en indeed/i });
    fireEvent.click(screen.getByRole("button", { name: /publicar en indeed/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/jobs/job-1/integrations/indeed/publish");
    });
  });

  it("manually synchronizes Indeed candidates and dispositions", async () => {
    api.post.mockImplementation((url) => {
      if (url === "/integrations/indeed/candidates/sync") {
        return Promise.resolve({ data: { fetched: 1, created: 1, reused: 0, skipped: 0 } });
      }
      if (url === "/integrations/indeed/dispositions/sync") {
        return Promise.resolve({ data: { selected: 1, sent: 1, failed: 0 } });
      }
      return Promise.resolve({ data: {} });
    });

    renderJobs();
    await screen.findByText("Country Manager Chile");
    fireEvent.click(screen.getByRole("button", { name: /^ver$/i }));

    const candidateSync = await screen.findByRole("button", { name: /sincronizar candidatos/i });
    fireEvent.click(candidateSync);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/integrations/indeed/candidates/sync");
    });

    const dispositionSync = await screen.findByRole("button", { name: /sincronizar estados/i });
    fireEvent.click(dispositionSync);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/integrations/indeed/dispositions/sync");
    });
  });

  it("keeps controls unavailable while Indeed is disabled", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs/page") return Promise.resolve({
        data: {
          items: [JOB],
          page: 1,
          page_size: 12,
          total: 1,
          total_pages: 1,
        },
      });
      if (url === "/integrations/indeed/status") {
        return Promise.resolve({ data: { enabled: false, configured: false } });
      }
      if (url === "/jobs/job-1/candidates") return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });

    renderJobs();
    await screen.findByText("Country Manager Chile");
    fireEvent.click(screen.getByRole("button", { name: /^ver$/i }));

    await screen.findByText("Indeed Employers");
    expect(screen.getByText("No configurado")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /publicar en indeed/i })).not.toBeInTheDocument();
  });
});
