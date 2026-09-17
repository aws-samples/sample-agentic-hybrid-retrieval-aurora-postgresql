// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AlexProfile } from "./AlexProfile";

afterEach(cleanup);

describe("Alex’s profile", () => {
  it("moves focus into the card and returns it to Alex when dismissed", () => {
    const onOpen = vi.fn();
    render(<AlexProfile onOpen={onOpen} />);
    const trigger = screen.getByRole("button", { name: "About Alex" });

    fireEvent.click(trigger);
    expect(onOpen).toHaveBeenCalledOnce();
    expect(screen.getByRole("dialog", { name: "Meet Alex." })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Meet Alex." }));
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Close Alex’s profile" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("dismisses when clicking or moving focus outside, without taking focus back", () => {
    render(<><AlexProfile onOpen={vi.fn()} /><button>Continue shopping</button></>);
    const trigger = screen.getByRole("button", { name: "About Alex" });
    const outside = screen.getByRole("button", { name: "Continue shopping" });

    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByRole("heading", { name: "Meet Alex." }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.pointerDown(outside);
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(trigger);
    act(() => outside.focus());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(outside);
  });
});
