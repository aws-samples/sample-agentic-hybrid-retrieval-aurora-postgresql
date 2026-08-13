// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CodeBlock } from "./CodeBlock";

describe("CodeBlock", () => {
  afterEach(cleanup);

  it("reports clipboard failures instead of rejecting from the click handler", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: vi.fn().mockRejectedValue(new Error("denied")),
      },
    });

    render(<CodeBlock code="SELECT 1;" label="example.sql" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy SQL" }));

    expect(
      await screen.findByText(
        "Clipboard access is unavailable. Select the code and copy it manually.",
      ),
    ).toBeTruthy();
  });
});
