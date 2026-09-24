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
      if (url === "/candidates?page=1&page_size=20") {
        return Promise.resolve({
          data: {
            items: [
              {
                candidate_id: "candidate-1",
                name: "Ana Test",
              },
            ],
            total: 1,
            page: 1,
            page_size: 20,
            pages: 1,
          },
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

      if (url === "/candidates/candidate-1/download") {
        return Promise.resolve({
          data: {
            download_url: "https://signed.example/candidate-1",
            expires_in: 300,
          },
        });
      }

      return Promise.resolve({ data: [] });
    });
  });

  it("opens Ver CV in a separate tab without replacing the current page", async () => {
    const replace = vi.fn();
    const close = vi.fn();
    const viewer = {
      opener: window,
      location: { replace },
      close,
    };
    const open = vi.spyOn(window, "open").mockReturnValue(viewer);

    renderCandidates();
    await screen.findByText("Ana Test");

    expect(
      screen.queryByRole("button", { name: /Descargar CV/i }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /Ver CV/i }),
    );

    await waitFor(() => {
      expect(open).toHaveBeenCalledWith("about:blank", "_blank");
      expect(api.get).toHaveBeenCalledWith(
        "/candidates/candidate-1/download",
      );
      expect(replace).toHaveBeenCalledWith(
        "https://signed.example/candidate-1",
      );
    });
    expect(viewer.opener).toBeNull();
    expect(close).not.toHaveBeenCalled();
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

  it("replaces deletion with an auditable veto action", async () => {
    api.post.mockResolvedValueOnce({
      data: {
        candidate: {
          candidate_id: "candidate-1",
          name: "Ana Test",
          is_banned: true,
          banned_reason: "Fraude documental",
        },
        changed: true,
      },
    });

    renderCandidates();
    await screen.findByText("Ana Test");

    expect(screen.queryByRole("button", { name: /Eliminar/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Vetar" }));

    expect(await screen.findByRole("heading", { name: "Vetar candidato" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Motivo del veto"), {
      target: { value: "Fraude documental" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar veto" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/candidates/candidate-1/ban",
        { reason: "Fraude documental" },
      );
    });
  });

  it("shows Agregar candidato on Candidates page and opens the upload modal", async () => {
    renderCandidates();

    await screen.findByText("Ana Test");

    const addButton = screen.getByRole(
      "button",
      { name: /Agregar candidato/i },
    );

    expect(addButton).toBeInTheDocument();

    fireEvent.click(addButton);

    expect(
      await screen.findByRole(
        "heading",
        { name: "Agregar candidatos" },
      ),
    ).toBeInTheDocument();
  });

});
