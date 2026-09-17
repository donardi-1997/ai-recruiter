// eslint-disable-next-line no-unused-vars
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BrandMark from "../components/BrandMark";

describe("ASIATI brand mark", () => {
  it("renders the official ASIATI logo asset", () => {
    render(<BrandMark />);

    const logo = screen.getByRole("img", { name: "ASIATI" });
    expect(logo).toHaveAttribute("src", "/asiati-logo.svg");
  });

  it("renders the logo inside a circular frame", () => {
    render(<BrandMark />);

    const logo = screen.getByRole("img", { name: "ASIATI" });
    expect(logo.parentElement).toHaveClass("asiati-logo-frame");
    expect(logo.parentElement).toHaveClass("asiati-logo-frame--round");
  });
});
