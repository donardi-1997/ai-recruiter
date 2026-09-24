// eslint-disable-next-line no-unused-vars
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "../pages/Dashboard";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
  },
}));

vi.mock("../context/SessionContext", () => ({
  useSession: vi.fn(),
}));

import api from "../api/client";
import { useSession } from "../context/SessionContext";


function renderPage() {
  return render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  );
}


function mockAdministrativeSession(role) {
  useSession.mockReturnValue({
    principal: {
      roles: [role],
      profile: {
        id: `${role.toLowerCase()}-1`,
        first_name: role === "SUPER_ADMIN" ? "Natalí" : "Administrador",
      },
    },
    hasPermission: (permission) => [
      "jobs.read",
      "candidates.read",
      "employees.read",
    ].includes(permission),
  });
}


describe("Administrative dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockImplementation((url) => {
      if (url === "/jobs") {
        return Promise.resolve({ data: [] });
      }
      if (url === "/candidates") {
        return Promise.resolve({ data: [] });
      }
      if (url === "/employees/summary") {
        return Promise.resolve({
          data: {
            employees_total: 8,
            active: 7,
            disabled: 1,
            onboarding: {
              total: 5,
              pending: 1,
              in_progress: 2,
              completed: 2,
              completion_percent: 40,
            },
          },
        });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
  });

  it.each(["ADMIN", "SUPER_ADMIN"])(
    "shows onboarding metrics to %s users with employee read permission",
    async (role) => {
      mockAdministrativeSession(role);
      renderPage();

      expect(await screen.findByText("Onboarding del equipo")).toBeInTheDocument();
      expect(screen.getByText("Empleados activos")).toBeInTheDocument();
      expect(screen.getByText("Pendientes")).toBeInTheDocument();
      expect(screen.getByText("En progreso")).toBeInTheDocument();
      expect(screen.getByText("Completados")).toBeInTheDocument();

      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith("/employees/summary");
      });
    },
  );
});
