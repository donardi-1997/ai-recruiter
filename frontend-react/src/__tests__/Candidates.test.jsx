// eslint-disable-next-line no-unused-vars
import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import Candidates from "../pages/Candidates";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from "../api/client";

function renderCandidates() {
  return render(
    <MemoryRouter>
      <Candidates />
    </MemoryRouter>,
  );
}

describe("Candidates evaluation", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    api.get.mockImplementation((url) => {
      if (url === "/candidates") {
        return Promise.resolve({
          data: [
            {
              candidate_id: "candidate-1",
              name: "Ana Test",
            },
          ],
        });
      }

      if (url === "/jobs") {
        return Promise.resolve({
          data: [
            {
              job_id: "job-1",
              title: "Backend Developer",
            },
          ],
        });
      }

      return Promise.resolve({ data: [] });
    });
  });

  it("shows FAILED without 0% or Sin clasificación", async () => {
    api.post.mockResolvedValueOnce({
      data: {
        status: "FAILED",
        match_score: null,
        recommendation: "EVALUATION_FAILED",
        summary:
          "No fue posible completar la evaluación. Intenta nuevamente.",
        strengths: [],
        gaps: [],
        error_message:
          "No fue posible completar la evaluación. Intenta nuevamente.",
      },
    });

    renderCandidates();

    await screen.findByText("Ana Test");

    fireEvent.change(
      screen.getByRole("combobox"),
      {
        target: { value: "job-1" },
      },
    );

    fireEvent.click(
      screen.getByRole(
        "button",
        { name: "Evaluar candidato" },
      ),
    );

    await waitFor(() => {
      expect(
        screen.getByText("Evaluación fallida"),
      ).toBeInTheDocument();
    });

    expect(
      screen.queryByText("Sin clasificación"),
    ).not.toBeInTheDocument();

    expect(
      screen.queryByText("0%"),
    ).not.toBeInTheDocument();
  });

  it("shows public error message and hides score on FAILED evaluation", async () => {
    api.post.mockResolvedValueOnce({
      data: {
        status: "FAILED",
        match_score: null,
        recommendation: "EVALUATION_FAILED",
        summary: "No fue posible completar la evaluación. Intenta nuevamente.",
        strengths: [],
        gaps: [],
        error_message: "No fue posible completar la evaluación. Intenta nuevamente.",
      },
    });

    renderCandidates();
    await screen.findByText("Ana Test");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "job-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Evaluar candidato" }));

    await waitFor(() => {
      expect(screen.getByText("Evaluación fallida")).toBeInTheDocument();
    });

    expect(screen.getByText("No fue posible completar la evaluación. Intenta nuevamente.")).toBeInTheDocument();
    expect(screen.queryByText("Sin clasificación")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("score-bar", { selector: ".score-bar" })).not.toBeInTheDocument();
  });

  it("supports PARTIAL_MATCH on successful evaluation", async () => {
    api.post.mockResolvedValueOnce({
      data: {
        status: "COMPLETED",
        match_score: 70,
        recommendation: "PARTIAL_MATCH",
        summary:
          "La candidata presenta experiencia técnica relevante para la vacante y evidencia concreta en varias competencias requeridas. También mantiene algunas brechas que deberían validarse durante la entrevista.",
        strengths: ["Python"],
        gaps: ["Kubernetes"],
        error_message: null,
      },
    });

    renderCandidates();

    await screen.findByText("Ana Test");

    fireEvent.change(
      screen.getByRole("combobox"),
      {
        target: { value: "job-1" },
      },
    );

    fireEvent.click(
      screen.getByRole(
        "button",
        { name: "Evaluar candidato" },
      ),
    );

    await screen.findByText("70%");

    expect(
      screen.getByText("Coincidencia parcial"),
    ).toBeInTheDocument();

    expect(
      screen.queryByText("Sin clasificación"),
    ).not.toBeInTheDocument();
  });
});
