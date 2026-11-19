// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TerminalCommand } from "./TerminalCommand";

const command = "uv run python scripts/lab_state.py status";

function stubClipboard(writeText: ReturnType<typeof vi.fn> | undefined) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: writeText ? { writeText } : undefined,
  });
}

describe("TerminalCommand", () => {
  afterEach(cleanup);

  it("tells the participant to select and copy the command when the browser denies the clipboard", async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    render(<TerminalCommand command={command} />);
    fireEvent.click(screen.getByRole("button", { name: `Copy ${command}` }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(
      "Clipboard access is unavailable. Select the code and copy it manually.",
    );
    expect(screen.getByText(command).tagName).toBe("CODE");
  });

  it("tells the participant the same when the browser has no clipboard", async () => {
    stubClipboard(undefined);
    render(<TerminalCommand command={command} />);
    fireEvent.click(screen.getByRole("button", { name: `Copy ${command}` }));
    expect((await screen.findByRole("alert")).textContent).toContain("copy it manually");
  });

  it("copies in one click and shows no message when the clipboard works", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    render(<TerminalCommand command={command} />);
    fireEvent.click(screen.getByRole("button", { name: `Copy ${command}` }));

    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith(command));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
