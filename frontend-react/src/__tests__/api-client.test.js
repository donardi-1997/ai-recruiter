import { describe, expect, it } from "vitest";

import { skipsAutomaticRefresh } from "../api/client";

describe("API session refresh routing", () => {
  it("allows /auth/me to recover an expired access token", () => {
    expect(skipsAutomaticRefresh("/auth/me")).toBe(false);
  });

  it.each([
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/auth/logout",
  ])("does not recurse refresh on %s", (url) => {
    expect(skipsAutomaticRefresh(url)).toBe(true);
  });
});
