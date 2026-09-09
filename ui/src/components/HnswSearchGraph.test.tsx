// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mountHnswScene } from "../hnswScene";
import { HnswSearchGraph } from "./HnswSearchGraph";

vi.mock("../hnswScene", () => ({ mountHnswScene: vi.fn() }));
const scene = { setStep: vi.fn(), setProgress: vi.fn(), highlight: vi.fn(), reset: vi.fn(), rotate: vi.fn(), zoom: vi.fn(), dispose: vi.fn() };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(mountHnswScene).mockReturnValue(scene); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("HnswSearchGraph", () => {
  it("handles a first frame timestamp before playback, then pauses and replays", async () => {
    let frame!: FrameRequestCallback;
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => { frame = callback; return 1; }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.spyOn(performance, "now").mockReturnValue(100);
    render(<HnswSearchGraph />);
    await screen.findByRole("button", { name: "Reset view" });
    fireEvent.click(screen.getByRole("button", { name: "Watch the search" }));
    act(() => frame(90));
    expect(scene.setProgress).toHaveBeenLastCalledWith(0, true);
    expect(screen.getByRole("button", { name: "Pause search" })).toBeTruthy();
    act(() => frame(5100));
    fireEvent.click(screen.getByRole("button", { name: "Pause search" }));
    expect(cancelAnimationFrame).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Continue search" }));
    act(() => frame(12100));
    expect(screen.getByRole("list", { name: "Illustrated candidate product types" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Watch again" }));
    expect(scene.setProgress).toHaveBeenLastCalledWith(0, false);
    expect(screen.queryByRole("list", { name: "Illustrated candidate product types" })).toBeNull();
  });
  it("changes graph layers and releases the renderer on navigation", async () => {
    const view = render(<HnswSearchGraph />);
    await screen.findByRole("button", { name: "Reset view" });
    fireEvent.click(screen.getByRole("button", { name: "3. Find neighbors" }));
    expect(scene.setStep).toHaveBeenLastCalledWith(2);
    fireEvent.click(screen.getByRole("button", { name: "Rotate graph left" }));
    expect(scene.rotate).toHaveBeenCalledWith(0.3);
    view.unmount();
    expect(scene.dispose).toHaveBeenCalledOnce();
  });

  it("keeps the explanation usable without WebGL and retries the renderer", async () => {
    vi.mocked(mountHnswScene).mockImplementationOnce(() => { throw new Error("No WebGL"); });
    render(<HnswSearchGraph />);
    const retry = await screen.findByRole("button", { name: "Retry 3D" });
    expect(screen.getByRole("img", { name: "Flat view of the HNSW layers" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "2. Move closer" }));
    fireEvent.click(retry);
    await screen.findByRole("button", { name: "Reset view" });
    await waitFor(() => expect(scene.setProgress).toHaveBeenLastCalledWith(2, false));
  });
});
