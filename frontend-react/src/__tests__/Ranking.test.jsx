// eslint-disable-next-line no-unused-vars
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Ranking from "../pages/Ranking";

// Mock api client
vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import api from "../api/client";

function renderRanking() {
  return render(
    <MemoryRouter>
      <Ranking />
    </MemoryRouter>,
  );
}

describe("Ranking page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock loadJobs
    api.get.mockImplementation((url) => {
      if (url === "/jobs") {
        return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      }
      if (url.includes("/ranking")) {
        return Promise.resolve({
          data: {
            candidates: [],
            ranking_generated_at: null,
            ranking_version: null,
            total: 0,
            pending_candidates: 0,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
  });

  it('shows "Ver ranking" button when no ranking exists', async () => {
    renderRanking();

    await waitFor(() => {
      expect(screen.getByText("Ver ranking")).toBeInTheDocument();
    });
  });

  it('shows "Actualizar ranking" button when ranking has metadata', async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs") {
        return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      }
      if (url.includes("/ranking")) {
        return Promise.resolve({
          data: {
            candidates: [{ candidate_id: "c1", score: 85, position: 1 }],
            ranking_generated_at: "2026-09-05T12:00:00Z",
            ranking_version: 3,
            total: 1,
            pending_candidates: 0,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });

    renderRanking();

    await waitFor(() => {
      expect(screen.getByText("Actualizar ranking")).toBeInTheDocument();
    });
  });

  it('shows ranking metadata text "Último ranking: vX"', async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs") {
        return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      }
      if (url.includes("/ranking")) {
        return Promise.resolve({
          data: {
            candidates: [{ candidate_id: "c1", score: 85, position: 1 }],
            ranking_generated_at: "2026-09-05T12:00:00Z",
            ranking_version: 3,
            total: 1,
            pending_candidates: 0,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });

    renderRanking();

    await waitFor(() => {
      expect(screen.getByText(/Último ranking: v3/)).toBeInTheDocument();
    });
  });
});
