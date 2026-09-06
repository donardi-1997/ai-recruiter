// eslint-disable-next-line no-unused-vars
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    vi.stubGlobal("alert", vi.fn());
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

  it("automatically recalculates before showing a new ranking", async () => {
    let rankingRequests = 0;

    api.get.mockImplementation((url) => {
      if (url === "/jobs") {
        return Promise.resolve({
          data: [
            {
              job_id: "job-1",
              title: "Dev Python",
            },
          ],
        });
      }

      if (url.includes("/ranking")) {
        rankingRequests += 1;

        if (rankingRequests === 1) {
          return Promise.resolve({
            data: {
              candidates: [],
              ranking_generated_at: null,
              ranking_version: null,
              ranking_scope: "assigned",
              ranking_total: 0,
              total: 0,
              total_pages: 0,
              page: 1,
              page_size: 10,
              pending_candidates: 0,
            },
          });
        }

        return Promise.resolve({
          data: {
            candidates: [
              {
                candidate_id: "candidate-1",
                candidate_name: "Ana Test",
                position: 1,
                status: "COMPLETED",
                match_score: 85,
                recommendation: "GOOD_MATCH",
                strengths: [],
                gaps: [],
              },
            ],
            ranking_generated_at:
              "2026-09-06T12:00:00Z",
            ranking_version: 1,
            ranking_scope: "assigned",
            ranking_total: 1,
            total: 1,
            total_pages: 1,
            page: 1,
            page_size: 10,
            pending_candidates: 0,
            score_min: 85,
            score_max: 85,
          },
        });
      }

      return Promise.resolve({ data: [] });
    });

    api.post.mockResolvedValueOnce({
      data: {
        job_id: "job-1",
        mode: "full",
        scope: "assigned",
        total_candidates: 1,
        evaluated: 1,
        failed: 0,
        ranking_version: 1,
      },
    });

    renderRanking();

    const viewRankingButton =
      screen.getByRole(
        "button",
        { name: "Ver ranking" },
      );

    await waitFor(() => {
      expect(
        viewRankingButton,
      ).not.toBeDisabled();
    });

    fireEvent.click(
      viewRankingButton,
    );

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/job-1/ranking/recalculate",
        null,
        {
          params: {
            mode: "incremental",
            scope: "assigned",
          },
        },
      );
    });

    await waitFor(() => {
      const scores = screen.getAllByText("85%");
      expect(scores.length).toBeGreaterThan(0);
    });
  });


  it("requests the next ranking page from the backend", async () => {
    api.get.mockImplementation(
      (url, config = {}) => {
        if (url === "/jobs") {
          return Promise.resolve({
            data: [
              {
                job_id: "job-1",
                title: "Dev Python",
              },
            ],
          });
        }

        if (url.includes("/ranking")) {
          const requestedPage =
            config.params?.page || 1;

          return Promise.resolve({
            data: {
              candidates: [
                {
                  candidate_id:
                    `candidate-${requestedPage}`,
                  candidate_name:
                    `Page ${requestedPage}`,
                  position:
                    requestedPage === 1
                      ? 1
                      : 11,
                  status: "COMPLETED",
                  match_score:
                    requestedPage === 1
                      ? 90
                      : 80,
                  recommendation:
                    "GOOD_MATCH",
                  strengths: [],
                  gaps: [],
                },
              ],
              ranking_generated_at:
                "2026-09-06T12:00:00Z",
              ranking_version: 2,
              ranking_scope: "assigned",
              ranking_total: 25,
              total: 25,
              total_pages: 3,
              page: requestedPage,
              page_size: 10,
              pending_candidates: 0,
              score_min: 10,
              score_max: 90,
            },
          });
        }

        return Promise.resolve({
          data: [],
        });
      },
    );

    renderRanking();

    await waitFor(() => {
      expect(
        screen.getByText("Siguiente"),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByText("Siguiente"),
    );

    await waitFor(() => {
      expect(
        api.get.mock.calls.some(
          ([url, config]) =>
            url ===
              "/jobs/job-1/ranking" &&
            config?.params?.page === 2,
        ),
      ).toBe(true);
    });
  });

});
