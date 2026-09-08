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

const EMPTY_RANKING = {
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
};

const CANDIDATES_RANKING = {
  data: {
    candidates: [
      { candidate_id: "c1", candidate_name: "Ana", position: 1, status: "COMPLETED", match_score: 85, recommendation: "GOOD_MATCH", strengths: ["Python"], gaps: [] },
    ],
    ranking_generated_at: "2026-09-06T12:00:00Z",
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
};

describe("Ranking page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("alert", vi.fn());
    vi.stubGlobal("confirm", vi.fn(() => true));
    api.get.mockImplementation((url) => {
      if (url === "/jobs") {
        return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      }
      if (url.includes("/ranking")) {
        return Promise.resolve(EMPTY_RANKING);
      }
      return Promise.resolve({ data: [] });
    });
  });

  // ============================================================
  // TEST 1 — TRES BOTONES
  // ============================================================

  it("shows all three action buttons and not obsolete ones", async () => {
    renderRanking();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Evaluar candidatos" })).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Actualizar ranking" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recalcular ranking" })).toBeInTheDocument();
    expect(screen.queryByText("Calcular evaluaciones")).not.toBeInTheDocument();
    expect(screen.queryByText("Generar ranking")).not.toBeInTheDocument();
    expect(screen.queryByText("Ver ranking")).not.toBeInTheDocument();
  });

  // ============================================================
  // TEST 2 — EVALUAR CANDIDATOS
  // ============================================================

  it("sends correct POST when clicking Evaluar candidatos", async () => {
    api.post.mockResolvedValueOnce({ data: { total_candidates: 2, evaluated: 2, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Evaluar candidatos" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Evaluar candidatos" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/job-1/ranking/recalculate",
        null,
        { params: { mode: "incremental", scope: "assigned" } },
      );
    });
  });

  // ============================================================
  // TEST 3 — EVALUAR IGNORA rankingScope
  // ============================================================

  it("Evaluar candidatos uses the selected rankingScope", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve({ data: { candidates: [], ranking_generated_at: null, ranking_version: null, ranking_scope: "all", ranking_total: 0, total: 0, total_pages: 0, page: 1, page_size: 10, pending_candidates: 0 } });
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValueOnce({ data: { total_candidates: 3, evaluated: 3, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Evaluar candidatos" })).not.toBeDisabled(); });
    fireEvent.change(screen.getByDisplayValue("Solo esta vacante"), { target: { value: "all" } });
    await waitFor(() => { expect(screen.getByDisplayValue("Todos mis candidatos")).toBeInTheDocument(); });
    fireEvent.click(screen.getByRole("button", { name: "Evaluar candidatos" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/job-1/ranking/recalculate",
        null,
        { params: { mode: "incremental", scope: "all" } },
      );
    });
  });

  // ============================================================
  // TEST 4 — ACTUALIZAR NO HACE POST
  // ============================================================

  it("Actualizar ranking only calls GET, never POST", async () => {
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Actualizar ranking" })).not.toBeDisabled(); });
    api.post.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Actualizar ranking" }));
    await waitFor(() => {
      expect(api.post).not.toHaveBeenCalled();
      expect(
        api.get.mock.calls.some(
          ([url, config]) =>
            url === "/jobs/job-1/ranking" &&
            config?.params?.page === 1,
        ),
      ).toBe(true);
    });
  });

  // ============================================================
  // TEST 5 — ACTUALIZAR RESPETA SCOPE
  // ============================================================

  it("Actualizar ranking uses rankingScope for the GET", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve({ data: { candidates: [], ranking_generated_at: null, ranking_version: null, ranking_scope: "all", ranking_total: 0, total: 0, total_pages: 0, page: 1, page_size: 10, pending_candidates: 0 } });
      return Promise.resolve({ data: [] });
    });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Actualizar ranking" })).not.toBeDisabled(); });
    fireEvent.change(screen.getByDisplayValue("Solo esta vacante"), { target: { value: "all" } });
    await waitFor(() => { expect(screen.getByDisplayValue("Todos mis candidatos")).toBeInTheDocument(); });
    api.post.mockClear();
    api.get.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Actualizar ranking" }));
    await waitFor(() => {
      expect(api.post).not.toHaveBeenCalled();
      expect(
        api.get.mock.calls.some(
          ([url, config]) =>
            url === "/jobs/job-1/ranking" &&
            config?.params?.scope === "all",
        ),
      ).toBe(true);
    });
  });

  // ============================================================
  // TEST 6 — RECALCULAR CANCELADO
  // ============================================================

  it("Recalcular ranking cancelled via window.confirm", async () => {
    window.confirm = vi.fn(() => false);
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Recalcular ranking" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Recalcular ranking" }));
    expect(api.post).not.toHaveBeenCalled();
  });

  // ============================================================
  // TEST 7 — RECALCULAR CONFIRMADO
  // ============================================================

  it("sends correct POST when confirming Recalcular ranking", async () => {
    window.confirm = vi.fn(() => true);
    api.post.mockResolvedValueOnce({ data: { total_candidates: 1, evaluated: 1, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Recalcular ranking" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Recalcular ranking" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/job-1/ranking/recalculate",
        null,
        { params: { mode: "full", scope: "assigned" } },
      );
    });
  });

  // ============================================================
  // TEST 8 — RECALCULAR IGNORA rankingScope
  // ============================================================

  it("Recalcular ranking uses the selected rankingScope", async () => {
    window.confirm = vi.fn(() => true);
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve({ data: { candidates: [], ranking_generated_at: null, ranking_version: null, ranking_scope: "all", ranking_total: 0, total: 0, total_pages: 0, page: 1, page_size: 10, pending_candidates: 0 } });
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValueOnce({ data: { total_candidates: 1, evaluated: 1, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Recalcular ranking" })).not.toBeDisabled(); });
    fireEvent.change(screen.getByDisplayValue("Solo esta vacante"), { target: { value: "all" } });
    await waitFor(() => { expect(screen.getByDisplayValue("Todos mis candidatos")).toBeInTheDocument(); });
    fireEvent.click(screen.getByRole("button", { name: "Recalcular ranking" }));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/jobs/job-1/ranking/recalculate",
        null,
        { params: { mode: "full", scope: "all" } },
      );
    });
  });

  // ============================================================
  // TEST 9 — LOADING EVALUAR
  // ============================================================

  it("Evaluar candidatos shows loading and disables all buttons", async () => {
    let resolvePost;
    api.post.mockImplementation(() => new Promise((resolve) => { resolvePost = resolve; }));
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve(EMPTY_RANKING);
      return Promise.resolve({ data: [] });
    });
    renderRanking();
    const evalBtn = await screen.findByRole("button", { name: "Evaluar candidatos" });
    expect(evalBtn).not.toBeDisabled();
    fireEvent.click(evalBtn);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Evaluando candidatos..." })).toBeDisabled();
    });
    expect(screen.getByRole("button", { name: "Actualizar ranking" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Recalcular ranking" })).toBeDisabled();
    resolvePost({ data: { total_candidates: 0, evaluated: 0, failed: 0 } });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Evaluar candidatos" })).not.toBeDisabled();
    });
  });

  // ============================================================
  // TEST 10 — LOADING ACTUALIZAR
  // ============================================================

  it("Actualizar ranking shows loading and disables all buttons", async () => {
    let resolveGet;
    let rankingCount = 0;
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) {
        rankingCount += 1;
        if (rankingCount <= 1) {
          return Promise.resolve(EMPTY_RANKING);
        }
        return new Promise((resolve) => { resolveGet = resolve; });
      }
      return Promise.resolve({ data: [] });
    });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Actualizar ranking" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Actualizar ranking" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Actualizando ranking..." })).toBeDisabled();
    });
    expect(screen.getByRole("button", { name: "Evaluar candidatos" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Recalcular ranking" })).toBeDisabled();
    resolveGet(EMPTY_RANKING);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Actualizar ranking" })).not.toBeDisabled();
    });
  });

  // ============================================================
  // TEST 11 — LOADING RECALCULAR
  // ============================================================

  it("Recalcular ranking shows loading and disables all buttons", async () => {
    window.confirm = vi.fn(() => true);
    let resolvePost;
    api.post.mockImplementation(() => new Promise((resolve) => { resolvePost = resolve; }));
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) return Promise.resolve(EMPTY_RANKING);
      return Promise.resolve({ data: [] });
    });
    renderRanking();
    const recalcBtn = await screen.findByRole("button", { name: "Recalcular ranking" });
    expect(recalcBtn).not.toBeDisabled();
    fireEvent.click(recalcBtn);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Recalculando ranking..." })).toBeDisabled();
    });
    expect(screen.getByRole("button", { name: "Evaluar candidatos" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Actualizar ranking" })).toBeDisabled();
    resolvePost({ data: { total_candidates: 1, evaluated: 1, failed: 0 } });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Recalcular ranking" })).not.toBeDisabled();
    });
  });

  // ============================================================
  // TEST 12 — REFRESH POST EVALUACIÓN
  // ============================================================

  it("Evaluar candidatos refreshes ranking with page=1 after success", async () => {
    let rankingCalls = 0;
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) {
        rankingCalls += 1;
        if (rankingCalls <= 1) return Promise.resolve(EMPTY_RANKING);
        return Promise.resolve(CANDIDATES_RANKING);
      }
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValueOnce({ data: { total_candidates: 1, evaluated: 1, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Evaluar candidatos" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Evaluar candidatos" }));
    await waitFor(() => {
      const rankingCall = api.get.mock.calls.find(([url]) => url === "/jobs/job-1/ranking");
      expect(rankingCall).toBeDefined();
      expect(rankingCall[1].params.page).toBe(1);
    });
  });

  // ============================================================
  // TEST 13 — REFRESH POST RECÁLCULO
  // ============================================================

  it("Recalcular ranking refreshes ranking with page=1 after success", async () => {
    window.confirm = vi.fn(() => true);
    let rankingCalls = 0;
    api.get.mockImplementation((url) => {
      if (url === "/jobs") return Promise.resolve({ data: [{ job_id: "job-1", title: "Dev Python" }] });
      if (url.includes("/ranking")) {
        rankingCalls += 1;
        if (rankingCalls <= 1) return Promise.resolve(EMPTY_RANKING);
        return Promise.resolve(CANDIDATES_RANKING);
      }
      return Promise.resolve({ data: [] });
    });
    api.post.mockResolvedValueOnce({ data: { total_candidates: 1, evaluated: 1, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Recalcular ranking" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Recalcular ranking" }));
    await waitFor(() => {
      const rankingCall = api.get.mock.calls.find(([url]) => url === "/jobs/job-1/ranking");
      expect(rankingCall).toBeDefined();
      expect(rankingCall[1].params.page).toBe(1);
    });
  });

  // ============================================================
  // TEST 14 — NO MODAL DE MODO
  // ============================================================

  it("does not show mode modal after clicking Actualizar or Recalcular", async () => {
    window.confirm = vi.fn(() => true);
    api.post.mockResolvedValueOnce({ data: { total_candidates: 1, evaluated: 1, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Actualizar ranking" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Actualizar ranking" }));
    await waitFor(() => { expect(screen.getByText("Ranking actualizado.")).toBeInTheDocument(); });
    expect(screen.queryByText("Solo nuevos candidatos")).not.toBeInTheDocument();
    expect(screen.queryByText("Recalcular todo")).not.toBeInTheDocument();
    expect(screen.queryByText("¿Cómo quieres actualizar el ranking?")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recalcular ranking" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(screen.queryByText("¿Cómo quieres actualizar el ranking?")).not.toBeInTheDocument();
  });

  // ============================================================
  // TEST 15 — FEEDBACK
  // ============================================================

  it("shows correct feedback messages for each action", async () => {
    api.post.mockResolvedValueOnce({ data: { total_candidates: 2, evaluated: 2, failed: 0 } });
    renderRanking();
    await waitFor(() => { expect(screen.getByRole("button", { name: "Evaluar candidatos" })).not.toBeDisabled(); });
    fireEvent.click(screen.getByRole("button", { name: "Evaluar candidatos" }));
    await waitFor(() => { expect(screen.getByText("Evaluación completada: 2 candidatos procesados.")).toBeInTheDocument(); });

    fireEvent.click(screen.getByRole("button", { name: "Actualizar ranking" }));
    await waitFor(() => { expect(screen.getByText("Ranking actualizado.")).toBeInTheDocument(); });

    window.confirm = vi.fn(() => true);
    api.post.mockResolvedValueOnce({ data: { total_candidates: 1, evaluated: 1, failed: 0 } });
    fireEvent.click(screen.getByRole("button", { name: "Recalcular ranking" }));
    await waitFor(() => { expect(screen.getByText("Ranking recalculado correctamente.")).toBeInTheDocument(); });
  });

  it("shows useful feedback when persisted ranking scope does not match", async () => {
    api.get.mockImplementation((url, config) => {
      if (url === "/jobs") {
        return Promise.resolve({
          data: [{ job_id: "job-1", title: "Dev Python" }],
        });
      }

      if (url.includes("/ranking")) {
        const scope = config?.params?.scope || "assigned";

        if (scope === "all") {
          return Promise.resolve({
            data: {
              candidates: [],
              ranking_generated_at: "2026-09-08T10:00:00Z",
              ranking_version: 2,
              ranking_scope: "assigned",
              scope_mismatch: true,
              ranking_total: 0,
              total: 0,
              total_pages: 0,
              page: 1,
              page_size: 10,
              pending_candidates: 0,
            },
          });
        }

        return Promise.resolve(EMPTY_RANKING);
      }

      return Promise.resolve({ data: [] });
    });

    renderRanking();

    await screen.findByRole(
      "button",
      { name: "Actualizar ranking" },
    );

    fireEvent.change(
      screen.getByDisplayValue("Solo esta vacante"),
      { target: { value: "all" } },
    );

    await waitFor(() => {
      expect(
        screen.getByText(
          /El ranking actual fue generado solo para los candidatos asignados/i,
        ),
      ).toBeInTheDocument();
    });
  });

});
