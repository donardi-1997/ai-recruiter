// eslint-disable-next-line no-unused-vars
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Candidates from "../pages/Candidates";

vi.mock("../context/SessionContext", () => ({
  useSession: () => ({
    hasPermission: (permission) => permission === "candidates.restrict",
  }),
}));

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("../features/candidate-import/CandidateImportModal.jsx", () => ({
  default: () => null,
}));

import api from "../api/client";

function candidate(id, name) {
  return { candidate_id: id, name };
}

function renderCandidates() {
  return render(
    <MemoryRouter>
      <Candidates />
    </MemoryRouter>,
  );
}

describe("Candidates pagination", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [] });
      if (url === "/candidates") {
        return Promise.resolve({ data: [candidate("legacy-1", "Legacy Candidate")] });
      }
      if (url === "/candidates?page=1&page_size=20") {
        return Promise.resolve({
          data: {
            items: [candidate("candidate-1", "Candidate 01")],
            total: 41,
            page: 1,
            page_size: 20,
            pages: 3,
          },
        });
      }
      if (url === "/candidates?page=2&page_size=20") {
        return Promise.resolve({
          data: {
            items: [candidate("candidate-21", "Candidate 21")],
            total: 41,
            page: 2,
            page_size: 20,
            pages: 3,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
  });

  it("loads 20-candidate server pages and navigates to the next page", async () => {
    renderCandidates();

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/candidates?page=1&page_size=20");
    });
    expect(await screen.findByText("Candidate 01")).toBeInTheDocument();
    expect(screen.getByText("41 perfiles disponibles")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 1–20")).toBeInTheDocument();
    expect(screen.getByText("Página 1 de 3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/candidates?page=2&page_size=20");
    });
    expect(await screen.findByText("Candidate 21")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 21–40")).toBeInTheDocument();
    expect(screen.getByText("Página 2 de 3")).toBeInTheDocument();
  });
});
