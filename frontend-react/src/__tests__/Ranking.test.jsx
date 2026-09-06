// eslint-disable-next-line no-unused-vars
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Ranking from "../pages/Ranking";

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
    vi.stubGlobal("alert", vi.fn());
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

  it('shows "Generar ranking" button when no ranking exists', async () => {
    renderRanking();
    await waitFor(() => {
      expect(screen.getByText("Generar ranking")).toBeInTheDocument();
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
            candidates: [{ candidate_id: "c1", candidate_name: "Ana", score: 85, position: 1, status: "COMPLETED", match_score: 85, recommendation: "GOOD_MATCH", strengths: [], gaps: [] }],
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
            candidates: [{ candidate_id: "c1", candidate_name: "Ana", score: 85, position: 1, status: "COMPLETED", match_score: 85, recommendation: "GOOD_MATCH", strengths: [], gaps: [] }],
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
      expect(screen.getByText(/Último ranking/)).toBeInTheDocument();
    });
  });

  it("automatically recalculates before showing a new ranking", async () => {
    let rankingRequests = 0;
    api.get.mockImplementation((url) => {
      if (url === "/jobs") {
        return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      }
      if (url.includes("/ranking")) {
        rankingRequests += 1;
        if (rankingRequests <= 1) {
          return Promise.resolve({
            data: {
              candidates: [], ranking_generated_at: null, ranking_version: null,
              ranking_scope: "assigned", ranking_total: 0, total: 0, total_pages: 0, page: 1, page_size: 10, pending_candidates: 0,
            },
          });
        }
        return Promise.resolve({
          data: {
            candidates: [{ candidate_id: "candidate-1", candidate_name: "Ana Test", position: 1, status: "COMPLETED", match_score: 85, recommendation: "GOOD_MATCH", strengths: [], gaps: [] }],
            ranking_generated_at: "2026-09-06T12:00:00Z", ranking_version: 1, ranking_scope: "assigned", ranking_total: 1, total: 1, total_pages: 1, page: 1, page_size: 10, pending_candidates: 0, score_min: 85, score_max: 85,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValueOnce({
      data: { job_id: "job-1", mode: "full", scope: "assigned", total_candidates: 1, evaluated: 1, failed: 0, ranking_version: 1 },
    });
    renderRanking();
    const viewBtn = await screen.findByRole("button", { name: "Generar ranking" });
    fireEvent.click(viewBtn);
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/job-1/ranking/recalculate",
        null,
        { params: { mode: "incremental", scope: "assigned" } },
      );
    });
    await waitFor(() => {
      expect(screen.getAllByText("85%").length).toBeGreaterThan(0);
    });
  });

  it("requests the next ranking page from the backend", async () => {
    api.get.mockImplementation((url, config = {}) => {
      if (url === "/jobs") {
        return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      }
      if (url.includes("/ranking")) {
        const rp = config.params?.page || 1;
        return Promise.resolve({
          data: {
            candidates: [{ candidate_id: `candidate-${rp}`, candidate_name: `Page ${rp}`, position: rp === 1 ? 1 : 11, status: "COMPLETED", match_score: rp === 1 ? 90 : 80, recommendation: "GOOD_MATCH", strengths: [], gaps: [] }],
            ranking_generated_at: "2026-09-06T12:00:00Z", ranking_version: 2, ranking_scope: "assigned", ranking_total: 25, total: 25, total_pages: 3, page: rp, page_size: 10, pending_candidates: 0, score_min: 10, score_max: 90,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
    renderRanking();
    await waitFor(() => { expect(screen.getByText("Siguiente")).toBeInTheDocument(); });
    fireEvent.click(screen.getByText("Siguiente"));
    await waitFor(() => {
      expect(api.get.mock.calls.some(([url, config]) => url === "/jobs/job-1/ranking" && config?.params?.page === 2)).toBe(true);
    });
  });

  // ============================================================
  // CALCULAR EVALUACIONES TESTS
  // ============================================================

  it('shows "Calcular evaluaciones" button', async () => {
    renderRanking();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Calcular evaluaciones" })).toBeInTheDocument();
    });
  });

  it("sends correct POST when clicking Calcular evaluaciones", async () => {
    api.post.mockResolvedValueOnce({ data: { job_id: "job-1", mode: "incremental", scope: "assigned", total_candidates: 2, evaluated: 2, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Calcular evaluaciones" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Calcular evaluaciones" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/job-1/ranking/recalculate",
        null,
        { params: { mode: "incremental", scope: "assigned" } },
      );
    });
  });

  it("refreshes ranking page 1 after successful evaluation", async () => {
    let rankingCalls = 0;
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) {
        rankingCalls += 1;
        if (rankingCalls === 1) {
          return Promise.resolve({ data: { candidates: [], ranking_generated_at: null, ranking_version: null, ranking_scope: "assigned", ranking_total: 0, total: 0, total_pages: 0, page: 1, page_size: 10, pending_candidates: 2 } });
        }
        return Promise.resolve({
          data: {
            candidates: [{ candidate_id: "c1", candidate_name: "Ana", position: 1, status: "COMPLETED", match_score: 85, recommendation: "GOOD_MATCH", strengths: [], gaps: [] }],
            ranking_generated_at: "2026-09-06T12:00:00Z", ranking_version: 1, ranking_scope: "assigned", ranking_total: 1, total: 1, total_pages: 1, page: 1, page_size: 10, pending_candidates: 0, score_min: 85, score_max: 85,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValueOnce({ data: { total_candidates: 1, evaluated: 1, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Calcular evaluaciones" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Calcular evaluaciones" }));
    await waitFor(() => { expect(api.get.mock.calls.length).toBeGreaterThanOrEqual(3); });
    const lastRankingCall = api.get.mock.calls.find(([url]) => url === "/jobs/job-1/ranking");
    expect(lastRankingCall[1].params.page).toBe(1);
  });

  it("shows loading text and disables button while evaluating", async () => {
    let resolvePost;
    api.post.mockImplementation(() => new Promise((resolve) => { resolvePost = resolve; }));
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve({ data: { candidates: [], ranking_generated_at: null, ranking_version: null, ranking_scope: "assigned", ranking_total: 0, total: 0, total_pages: 0, page: 1, page_size: 10, pending_candidates: 0 } });
      return Promise.resolve({ data: [] });
    });
    renderRanking();
    const calcBtn = await screen.findByRole("button", { name: "Calcular evaluaciones" });
    expect(calcBtn).not.toBeDisabled();
    fireEvent.click(calcBtn);
    await waitFor(() => {
      const loadingBtn = screen.getByRole("button", { name: "Calculando evaluaciones..." });
      expect(loadingBtn).toBeDisabled();
    });
    resolvePost({ data: { total_candidates: 0, evaluated: 0, failed: 0 } });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Calcular evaluaciones" })).not.toBeDisabled();
    });
  });

  it("always uses scope=assigned regardless of rankingScope", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve({ data: { candidates: [], ranking_generated_at: null, ranking_version: null, ranking_scope: "all", ranking_total: 0, total: 0, total_pages: 0, page: 1, page_size: 10, pending_candidates: 0 } });
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValueOnce({ data: { total_candidates: 3, evaluated: 3, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Calcular evaluaciones" })).not.toBeDisabled(); });
    fireEvent.change(screen.getByDisplayValue("Solo esta vacante"), { target: { value: "all" } });
    await waitFor(() => { expect(screen.getByDisplayValue("Todos mis candidatos")).toBeInTheDocument(); });
    fireEvent.click(screen.getByRole("button", { name: "Calcular evaluaciones" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/job-1/ranking/recalculate",
        null,
        { params: { mode: "incremental", scope: "assigned" } },
      );
    });
  });

  it("shows pending badge when pending_candidates > 0", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve({ data: { candidates: [], ranking_generated_at: null, ranking_version: null, ranking_scope: "assigned", ranking_total: 0, total: 3, total_pages: 0, page: 1, page_size: 10, pending_candidates: 3 } });
      return Promise.resolve({ data: [] });
    });
    renderRanking();
    await waitFor(() => { expect(screen.getByText("3 pendientes")).toBeInTheDocument(); });
  });

  it("shows success feedback when no pending evaluations", async () => {
    api.post.mockResolvedValueOnce({ data: { total_candidates: 0, evaluated: 0, failed: 0 } });
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve({ data: { candidates: [], ranking_generated_at: null, ranking_version: null, ranking_scope: "assigned", ranking_total: 0, total: 0, total_pages: 0, page: 1, page_size: 10, pending_candidates: 0 } });
      return Promise.resolve({ data: [] });
    });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Calcular evaluaciones" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Calcular evaluaciones" }));
    await waitFor(() => { expect(screen.getByText("No hay evaluaciones pendientes para esta vacante.")).toBeInTheDocument(); });
  });
});
