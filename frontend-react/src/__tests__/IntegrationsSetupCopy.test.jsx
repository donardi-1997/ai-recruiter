// eslint-disable-next-line no-unused-vars
import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Integrations from "../pages/Integrations";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from "../api/client";

describe("Gmail OAuth setup guidance", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("explains that the HTTPS callback is ready while Google credentials are pending", async () => {
    api.get.mockResolvedValueOnce({
      data: {
        enabled: true,
        configured: false,
        oauth_configured: false,
        connected: false,
        connected_email: null,
        provider: "INDEED",
        safe_filter: false,
        redirect_uri: "https://3fkmecjfig.execute-api.us-east-2.amazonaws.com/api/integrations/gmail/oauth/callback",
      },
    });

    render(
      <MemoryRouter>
        <Integrations />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Credenciales de Google pendientes")).toBeInTheDocument();
    expect(screen.getByText(/El callback HTTPS ya está preparado/)).toBeInTheDocument();
    expect(screen.getByText(/3fkmecjfig\.execute-api\.us-east-2\.amazonaws\.com/)).toBeInTheDocument();
  });
});
