// eslint-disable-next-line no-unused-vars
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function renderPage() {
  return render(
    <MemoryRouter>
      <Integrations />
    </MemoryRouter>,
  );
}

describe("Gmail corporate integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows setup state and callback URI when OAuth client is not configured", async () => {
    api.get.mockResolvedValueOnce({
      data: {
        enabled: true,
        configured: false,
        oauth_configured: false,
        connected: false,
        connected_email: null,
        provider: "INDEED",
        safe_filter: true,
        redirect_uri: "https://abc.execute-api.us-east-2.amazonaws.com/prod/api/integrations/gmail/oauth/callback",
      },
    });

    renderPage();

    expect(await screen.findByRole("heading", { name: "Integraciones" })).toBeInTheDocument();
    expect(screen.getByText("Gmail corporativo")).toBeInTheDocument();
    expect(screen.getByText("OAuth de Gmail no configurado")).toBeInTheDocument();
    expect(screen.getByText(/abc\.execute-api\.us-east-2\.amazonaws\.com/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Conectar Gmail" })).toBeDisabled();
  });

  it("starts OAuth from the authenticated app and redirects to Google", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    api.get
      .mockResolvedValueOnce({
        data: {
          enabled: true,
          configured: false,
          oauth_configured: true,
          connected: false,
          connected_email: null,
          provider: "INDEED",
          safe_filter: true,
          redirect_uri: "https://abc.execute-api.us-east-2.amazonaws.com/prod/api/integrations/gmail/oauth/callback",
        },
      })
      .mockResolvedValueOnce({
        data: {
          authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?state=abc",
        },
      });

    renderPage();

    const connect = await screen.findByRole("button", { name: "Conectar Gmail" });
    fireEvent.click(connect);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/integrations/gmail/oauth/start");
      expect(openSpy).toHaveBeenCalledWith(
        "https://accounts.google.com/o/oauth2/v2/auth?state=abc",
        "_self",
      );
    });

    openSpy.mockRestore();
  });

  it("shows connected mailbox and can trigger a manual sync", async () => {
    api.get.mockResolvedValueOnce({
      data: {
        enabled: true,
        configured: true,
        oauth_configured: true,
        connected: true,
        connected_email: "recruiting@asiaticorp.com",
        provider: "INDEED",
        safe_filter: true,
        redirect_uri: "https://abc.execute-api.us-east-2.amazonaws.com/prod/api/integrations/gmail/oauth/callback",
      },
    });
    api.post.mockResolvedValueOnce({
      data: {
        mode: "FULL",
        discovered: 3,
        created: 2,
        existing: 1,
        needs_review: 0,
        skipped: 0,
      },
    });

    renderPage();

    expect(await screen.findByText("recruiting@asiaticorp.com")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sincronizar ahora" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/integrations/gmail/sync");
    });
    expect(await screen.findByText(/2 candidatos nuevos/)).toBeInTheDocument();
  });

  it("disconnects the corporate mailbox and refreshes status", async () => {
    api.get
      .mockResolvedValueOnce({
        data: {
          enabled: true,
          configured: true,
          oauth_configured: true,
          connected: true,
          connected_email: "recruiting@asiaticorp.com",
          provider: "INDEED",
          safe_filter: true,
          redirect_uri: "https://abc.execute-api.us-east-2.amazonaws.com/prod/api/integrations/gmail/oauth/callback",
        },
      })
      .mockResolvedValueOnce({
        data: {
          enabled: true,
          configured: false,
          oauth_configured: true,
          connected: false,
          connected_email: null,
          provider: "INDEED",
          safe_filter: true,
          redirect_uri: "https://abc.execute-api.us-east-2.amazonaws.com/prod/api/integrations/gmail/oauth/callback",
        },
      });
    api.delete.mockResolvedValueOnce({ data: { connected: false } });

    renderPage();
    await screen.findByText("recruiting@asiaticorp.com");

    fireEvent.click(screen.getByRole("button", { name: "Desconectar" }));

    await waitFor(() => {
      expect(api.delete).toHaveBeenCalledWith("/integrations/gmail");
    });
    expect(await screen.findByText("Gmail listo para conectar")).toBeInTheDocument();
  });
});
