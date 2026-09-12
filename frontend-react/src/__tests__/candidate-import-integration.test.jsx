// eslint-disable-next-line no-unused-vars
import React from "react";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Candidates from "../pages/Candidates.jsx";
import Ranking from "../pages/Ranking.jsx";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("../features/candidate-import/api.js", () => ({
  createImportBatch: vi.fn(),
  uploadToPresignedPost: vi.fn(),
  completeImportBatch: vi.fn(),
  getImportBatch: vi.fn(),
  getImportItems: vi.fn(),
  getRecentImports: vi.fn().mockResolvedValue({ items: [] }),
}));

import api from "../api/client";

const jobs = [
  { job_id: "job-1", title: "Backend Engineer", candidate_count: 0 },
  { job_id: "job-2", title: "Data Engineer", candidate_count: 0 },
];

function emptyRanking(scope = "assigned") {
  return {
    data: {
      candidates: [],
      ranking_generated_at: null,
      ranking_version: null,
      ranking_scope: scope,
      ranking_total: 0,
      total: 0,
      total_pages: 0,
      page: 1,
      page_size: 10,
      pending_candidates: 0,
    },
  };
}

describe("candidate import page integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/candidates") return Promise.resolve({ data: [] });
      if (url === "/jobs") return Promise.resolve({ data: jobs });
      if (url.includes("/ranking")) return Promise.resolve(emptyRanking());
      return Promise.resolve({ data: [] });
    });
  });

  it("opens the durable PDF DOCX ZIP import modal from Candidates", async () => {
    render(
      <MemoryRouter initialEntries={["/candidates"]}>
        <Candidates />
      </MemoryRouter>,
    );

    const button = await screen.findByRole("button", { name: /agregar candidato/i });
    fireEvent.click(button);

    expect(await screen.findByText(/importación inteligente/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF, DOCX o ZIP/i)).toBeInTheDocument();
    expect(screen.queryByText(/seleccionar carpeta/i)).not.toBeInTheDocument();
  });

  it("Ranking honors the job_id deep link produced by an import summary", async () => {
    render(
      <MemoryRouter initialEntries={["/ranking?job_id=job-2"]}>
        <Ranking />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        api.get.mock.calls.some(
          ([url, config]) =>
            url === "/jobs/job-2/ranking" &&
            config?.params?.scope === "assigned",
        ),
      ).toBe(true);
    });

    expect(screen.getByDisplayValue("Data Engineer")).toBeInTheDocument();
  });
});
