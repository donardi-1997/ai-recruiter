// eslint-disable-next-line no-unused-vars
import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CandidateDetail from "../pages/CandidateDetail";

vi.mock("../api/client", () => ({
  default: { get: vi.fn() },
}));

import api from "../api/client";

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={["/candidates/candidate-1"]}>
      <Routes>
        <Route path="/candidates/:candidate_id" element={<CandidateDetail />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("CandidateDetail Indeed attribution", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/candidates/candidate-1") {
        return Promise.resolve({
          data: {
            candidate_id: "candidate-1",
            name: "Ana Perez",
            email: "ana@example.com",
            filename: null,
            metadata: {
              source: "Indeed",
              source_name: "Indeed Smart Sourcing",
              resume_name: "ana-perez.pdf",
              indeed_staged_test: true,
            },
          },
        });
      }
      if (url === "/candidates/candidate-1/evaluations") {
        return Promise.resolve({ data: { evaluations: [] } });
      }
      return Promise.reject(new Error(`Unexpected URL ${url}`));
    });
  });

  it("shows the Indeed source and remote resume name without exposing the remote URL", async () => {
    renderDetail();

    await screen.findByText("Ana Perez");
    expect(screen.getByText("ana-perez.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Indeed Smart Sourcing/i)).toBeInTheDocument();
    expect(screen.getByText(/Candidato de prueba de Indeed/i)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("example.invalid/private-resume");
  });
});
