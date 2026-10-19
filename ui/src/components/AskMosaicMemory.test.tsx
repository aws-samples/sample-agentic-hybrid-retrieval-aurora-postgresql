// @vitest-environment jsdom
import { cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { MemoryControl, MemoryReceipt, useAskMosaicMemory } from "./AskMosaicMemory";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("checks a connection only when opened and does not opt in silently", async () => {
  const status = vi.spyOn(api, "memoryStatus").mockResolvedValue({ memory_status: "not_configured", configuration: null });
  const { result, rerender } = renderHook(({ open }) => useAskMosaicMemory(open), { initialProps: { open: false } });
  expect(status).not.toHaveBeenCalled();
  rerender({ open: true });
  await waitFor(() => expect(result.current.status).toBe("not_configured"));
  expect(result.current.enabled).toBe(false);
});

it("allows opting out when memory becomes unavailable", () => {
  const setEnabled = vi.fn();
  render(<MemoryControl memory={{ enabled: true, setEnabled, status: "unavailable", retry: vi.fn() }} pending={false} />);
  fireEvent.click(screen.getByRole("checkbox", { name: "Use saved memories" }));
  expect(setEnabled).toHaveBeenCalledWith(false);
  expect(screen.getByText(/AgentCore Memory is unavailable/)).toBeTruthy();
});

it("shows actual records and a failed save without claiming new memories exist", () => {
  render(<MemoryReceipt memory={{ enabled: true, status: "connected", write_status: "failed", event_ids_read: ["event"], records: [{
    id: "real-record", text: '{"preference":"Prefers quiet equipment"}', strategy_id: "preferences", namespaces: [], created_at: "", score: null,
  }] }} />);
  fireEvent.click(screen.getByText("Memories used"));
  expect(screen.getByText("Prefers quiet equipment")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain("could not be saved");
  expect(screen.queryByText(/Conversation saved/)).toBeNull();
  expect(screen.getByText(/1 earlier conversation events/)).toBeTruthy();
});

it("keeps memory to one toggle and shows its sentence as a line only when memory cannot be used", () => {
  const { rerender } = render(<MemoryControl memory={{ enabled: false, setEnabled: vi.fn(), status: "connected", retry: vi.fn() }} pending={false} />);
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByText(/Memory is off/).className).toContain("sr-only");
  rerender(<MemoryControl memory={{ enabled: false, setEnabled: vi.fn(), status: "unavailable", retry: vi.fn() }} pending={false} />);
  expect(screen.getByText(/AgentCore Memory is unavailable/).className).not.toContain("sr-only");
  expect(screen.getByRole("button", { name: "Retry connection" })).toBeTruthy();
});
