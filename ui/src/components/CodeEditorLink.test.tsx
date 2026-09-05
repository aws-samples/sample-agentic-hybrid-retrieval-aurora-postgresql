// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CodeEditorLink } from "./CodeEditorLink";

describe("CodeEditorLink", () => {
  afterEach(cleanup);

  it("renders nothing when the service reports no Code Editor", () => {
    const { container } = render(<CodeEditorLink href={null} />);

    expect(container.innerHTML).toBe("");
  });

  it("renders nothing for a blank URL", () => {
    const { container } = render(<CodeEditorLink href="   " />);

    expect(container.innerHTML).toBe("");
  });

  it("opens the Code Editor in a new tab without handing it an opener", () => {
    render(<CodeEditorLink href="https://code.example.aws/?folder=/home/ec2-user" />);

    const link = screen.getByRole("link", { name: "Code Editor" });
    expect(link.getAttribute("href")).toBe(
      "https://code.example.aws/?folder=/home/ec2-user",
    );
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
  });

  it("refuses a URL carrying a Code Editor token", () => {
    // Mirrors the service rule: `/api/health` publishes the Code Editor origin,
    // never a URL with the one-time `tkn=` parameter in it. A token on the wire
    // would be pasted into a shared link, a screenshot, or a support thread. The
    // participant already holds an authenticated session, so dropping the link
    // costs one click and leaks nothing.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { container } = render(
      <CodeEditorLink href="https://code.example.aws/?tkn=8f2c1d" />,
    );

    expect(container.innerHTML).toBe("");
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain("tkn=");
    warn.mockRestore();
  });

  it("refuses the token however the parameter is cased or ordered", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { container } = render(
      <CodeEditorLink href="https://code.example.aws/?folder=/home&TKN=8f2c1d" />,
    );

    expect(container.innerHTML).toBe("");
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});
