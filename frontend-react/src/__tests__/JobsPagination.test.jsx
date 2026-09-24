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

const PAGE = {
  items: [
    {
      job_id: "job-1",
      title: "Backend Developer",
      description: "Python APIs",
      candidate_count: 8,
      created_at: "2026-09-22T10:00:00Z",
    },
  ],
  page: 1,
  page_size: 12,
  total: 25,
  total_pages: 3,
};

function renderJobs(initialEntry = "/jobs") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Jobs />
    </MemoryRouter>
  );
}

describe("Jobs pagination and sorting", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/jobs/page") return Promise.resolve({ data: PAGE });
      if (url === "/integrations/indeed/status") {
        return Promise.resolve({ data: { enabled: false, configured: false } });
      }
      return Promise.resolve({ data: [] });
    });
  });

  it("loads the default first page from the paginated jobs endpoint", async () => {
    renderJobs();

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/jobs/page", {
        params: {
          page: 1,
          page_size: 12,
          sort: "created_desc",
          q: "",
        },
      });
    });
    expect(await screen.findByText("Backend Developer")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 1–12 de 25 vacantes")).toBeInTheDocument();
  });

  it("reads page, page size, sort and search from the URL", async () => {
    renderJobs("/jobs?page=2&page_size=24&sort=created_asc&q=backend");

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/jobs/page", {
        params: {
          page: 2,
          page_size: 24,
          sort: "created_asc",
          q: "backend",
        },
      });
    });
    expect(screen.getByLabelText("Buscar vacante")).toHaveValue("backend");
    expect(screen.getByLabelText("Ordenar por")).toHaveValue("created_asc");
    expect(screen.getByLabelText("Vacantes por página")).toHaveValue("24");
  });

  it("changing sort to most candidates resets to page one and requests global candidate ordering", async () => {
    renderJobs("/jobs?page=3");
    await screen.findByText("Backend Developer");

    fireEvent.change(screen.getByLabelText("Ordenar por"), {
      target: { value: "candidates_desc" },
    });

    await waitFor(() => {
      expect(api.get).toHaveBeenLastCalledWith("/jobs/page", {
        params: {
          page: 1,
          page_size: 12,
          sort: "candidates_desc",
          q: "",
        },
      });
    });
  });

  it("next page preserves filters and requests the following page", async () => {
    renderJobs("/jobs?sort=candidates_desc&q=developer");
    await screen.findByText("Backend Developer");

    fireEvent.click(screen.getByRole("button", { name: /siguiente/i }));

    await waitFor(() => {
      expect(api.get).toHaveBeenLastCalledWith("/jobs/page", {
        params: {
          page: 2,
          page_size: 12,
          sort: "candidates_desc",
          q: "developer",
        },
      });
    });
  });
});
