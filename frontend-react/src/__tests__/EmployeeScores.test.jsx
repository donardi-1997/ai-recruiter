// eslint-disable-next-line no-unused-vars
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EmployeeScores from "../pages/EmployeeScores";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import api from "../api/client";


function renderPage() {
  return render(
    <MemoryRouter>
      <EmployeeScores />
    </MemoryRouter>,
  );
}


describe("Direction employee scoring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/direction/employee-scores") {
        return Promise.resolve({
          data: {
            items: [
              {
                id: "employee-1",
                email: "ana@asiati.com.co",
                first_name: "Ana",
                last_name: "Pérez",
                job_title: "Comercial",
                department: "Ventas",
                status: "ACTIVE",
                score_total: 25,
              },
            ],
          },
        });
      }
      if (url === "/direction/employee-scores/employee-1") {
        return Promise.resolve({
          data: {
            employee: {
              id: "employee-1",
              email: "ana@asiati.com.co",
              first_name: "Ana",
              last_name: "Pérez",
              job_title: "Comercial",
              department: "Ventas",
              score_total: 25,
            },
            history: [
              {
                id: "event-1",
                employee_id: "employee-1",
                points: 30,
                description: "Completó el proyecto.",
                status: "ACTIVE",
                event_date: "2026-09-24T12:00:00+00:00",
              },
              {
                id: "event-2",
                employee_id: "employee-1",
                points: -5,
                description: "Ausencia registrada.",
                status: "ACTIVE",
                event_date: "2026-09-23T12:00:00+00:00",
              },
            ],
          },
        });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
  });

  it("shows total and auditable history", async () => {
    renderPage();

    expect((await screen.findAllByText("Ana Pérez")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Completó el proyecto.")).toBeInTheDocument();
    expect(screen.getByText("Ausencia registrada.")).toBeInTheDocument();
    expect(screen.getAllByText("+25").length).toBeGreaterThan(0);
  });

  it("submits arbitrary positive points with a description", async () => {
    api.post.mockResolvedValueOnce({ data: {} });
    renderPage();

    await screen.findAllByText("Ana Pérez");

    fireEvent.change(screen.getByLabelText("Puntos"), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Terminó el proyecto asignado." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Guardar calificación" }),
    );

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/direction/employee-scores/employee-1/events",
        {
          points: 30,
          description: "Terminó el proyecto asignado.",
        },
      );
    });
  });

  it("submits negative points without applying an automatic rule", async () => {
    api.post.mockResolvedValueOnce({ data: {} });
    renderPage();

    await screen.findAllByText("Ana Pérez");

    fireEvent.change(screen.getByLabelText("Puntos"), {
      target: { value: "-5" },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Ausencia definida por Dirección." },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Guardar calificación" }),
    );

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/direction/employee-scores/employee-1/events",
        {
          points: -5,
          description: "Ausencia definida por Dirección.",
        },
      );
    });
  });
});
