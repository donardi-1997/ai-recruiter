// eslint-disable-next-line no-unused-vars
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CandidateDetail from "../pages/CandidateDetail";

vi.mock("../api/client", () => ({
  default: { get: vi.fn() },
}));

import api from "../api/client";

function renderDetail(initialEntry = "/candidates/candidate-1?job_id=job-1") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/candidates/:candidate_id" element={<CandidateDetail />} />
      </Routes>
    </MemoryRouter>
  );
}

function candidateResponse() {
  return {
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
  };
}

function evaluationResponse() {
  return {
    data: {
      match_score: 88,
      recommendation: "STRONG_MATCH",
      summary: "Perfil compatible con la vacante seleccionada.",
      strengths: ["Liderazgo"],
      gaps: [],
    },
  };
}

describe("CandidateDetail Indeed canonical resume", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "open").mockImplementation(() => null);
  });

  it("keeps the profile visible when the job evaluation does not exist yet", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/candidates/candidate-1") return Promise.resolve(candidateResponse());
      if (url === "/jobs/job-1/candidates/candidate-1") {
        return Promise.reject({ response: { status: 404 } });
      }
      if (url === "/jobs/job-1/candidates/candidate-1/integrations/indeed") {
        return Promise.reject({ response: { status: 404 } });
      }
      return Promise.reject(new Error(`Unexpected URL ${url}`));
    });

    renderDetail();

    await screen.findByText("Ana Perez");
    expect(screen.getByText(/Perfil pendiente de evaluación/i)).toBeInTheDocument();
    expect(screen.getByText(/Pendiente de evaluación para la vacante seleccionada/i)).toBeInTheDocument();
  });

  it("never renders a null score for a failed evaluation", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/candidates/candidate-1") return Promise.resolve(candidateResponse());
      if (url === "/jobs/job-1/candidates/candidate-1") {
        return Promise.resolve({
          data: {
            status: "FAILED",
            match_score: null,
            recommendation: "EVALUATION_FAILED",
            summary: "No fue posible completar la evaluación.",
            strengths: [],
            gaps: [],
          },
        });
      }
      if (url === "/jobs/job-1/candidates/candidate-1/integrations/indeed") {
        return Promise.reject({ response: { status: 404 } });
      }
      return Promise.reject(new Error(`Unexpected URL ${url}`));
    });

    renderDetail();

    await screen.findByText("Ana Perez");
    expect(screen.getByText(/La evaluación no pudo completarse/i)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("null%");
  });

  it("shows processing state without exposing the temporary Indeed URL", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/candidates/candidate-1") return Promise.resolve(candidateResponse());
      if (url === "/jobs/job-1/candidates/candidate-1") return Promise.resolve(evaluationResponse());
      if (url === "/jobs/job-1/candidates/candidate-1/integrations/indeed") {
        return Promise.resolve({
          data: {
            source_name: "Indeed Smart Sourcing",
            staged_test: true,
            resume: {
              name: "ana-perez.pdf",
              status: "INGESTING",
              available: false,
              sha256: null,
              last_error_code: null,
            },
          },
        });
      }
      return Promise.reject(new Error(`Unexpected URL ${url}`));
    });

    renderDetail();

    await screen.findByText("Ana Perez");
    expect(screen.getByText(/Indeed Smart Sourcing/i)).toBeInTheDocument();
    expect(screen.getByText(/Procesando CV/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ver CV/i })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("X-Amz-Signature");
  });

  it("opens only the canonical short-lived CV URL when processing is complete", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/candidates/candidate-1") return Promise.resolve(candidateResponse());
      if (url === "/jobs/job-1/candidates/candidate-1") return Promise.resolve(evaluationResponse());
      if (url === "/jobs/job-1/candidates/candidate-1/integrations/indeed") {
        return Promise.resolve({
          data: {
            source_name: "Indeed Smart Sourcing",
            staged_test: false,
            resume: {
              name: "ana-perez.pdf",
              status: "COMPLETED",
              available: true,
              sha256: "a".repeat(64),
              last_error_code: null,
            },
          },
        });
      }
      if (url === "/candidates/candidate-1/download") {
        return Promise.resolve({
          data: {
            download_url: "https://canonical.invalid/download",
            expires_in: 300,
          },
        });
      }
      return Promise.reject(new Error(`Unexpected URL ${url}`));
    });

    renderDetail();
    const button = await screen.findByRole("button", { name: /Ver CV/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/candidates/candidate-1/download");
      expect(window.open).toHaveBeenCalledWith(
        "https://canonical.invalid/download",
        "_blank",
        "noopener,noreferrer"
      );
    });
  });

  it("opens the canonical CV for candidates that do not come from Indeed", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/candidates/candidate-1") return Promise.resolve(candidateResponse());
      if (url === "/candidates/candidate-1/evaluations") {
        return Promise.resolve({ data: { evaluations: [] } });
      }
      if (url === "/candidates/candidate-1/download") {
        return Promise.resolve({
          data: {
            download_url: "https://canonical.invalid/manual-cv",
            expires_in: 300,
          },
        });
      }
      return Promise.reject(new Error(`Unexpected URL ${url}`));
    });

    renderDetail("/candidates/candidate-1");
    const button = await screen.findByRole("button", { name: /Ver CV/i });
    fireEvent.click(button);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/candidates/candidate-1/download");
      expect(window.open).toHaveBeenCalledWith(
        "https://canonical.invalid/manual-cv",
        "_blank",
        "noopener,noreferrer"
      );
    });
  });

  it("shows a safe failure state when resume processing failed", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/candidates/candidate-1") return Promise.resolve(candidateResponse());
      if (url === "/jobs/job-1/candidates/candidate-1") return Promise.resolve(evaluationResponse());
      if (url === "/jobs/job-1/candidates/candidate-1/integrations/indeed") {
        return Promise.resolve({
          data: {
            source_name: "Indeed Smart Sourcing",
            resume: {
              name: "ana-perez.pdf",
              status: "FAILED",
              available: false,
              sha256: null,
              last_error_code: "RESUME_NOT_PDF",
            },
          },
        });
      }
      return Promise.reject(new Error(`Unexpected URL ${url}`));
    });

    renderDetail();

    await screen.findByText(/No fue posible procesar el CV/i);
    expect(document.body).not.toHaveTextContent("resume.invalid");
  });
});
