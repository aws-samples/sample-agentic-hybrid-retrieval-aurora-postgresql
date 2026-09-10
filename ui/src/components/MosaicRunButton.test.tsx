// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MosaicRunButton } from "./MosaicRunButton";

describe("MosaicRunButton", () => {
  it("is named by its label and says so on hover when the plane stands alone", () => {
    render(<MosaicRunButton label="Run Mosaic" />);
    const button = screen.getByRole("button", { name: "Run Mosaic" });
    expect(button.getAttribute("title")).toBe("Run Mosaic");
    expect(button.textContent).toBe("");
    expect(button.querySelector(".mosaic-run-disc svg")).toBeTruthy();
  });

  it("prints the label beside the plane when asked, without a redundant tooltip", () => {
    render(<MosaicRunButton label="Ask Mosaic" showLabel />);
    const button = screen.getByRole("button", { name: "Ask Mosaic" });
    expect(button.getAttribute("title")).toBeNull();
    expect(button.getAttribute("aria-label")).toBeNull();
    expect(button.classList.contains("labelled")).toBe(true);
  });

  it("stays busy and disabled while a request is in flight", () => {
    render(<MosaicRunButton label="Finding products" running />);
    const button = screen.getByRole("button", { name: "Finding products" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.querySelector(".mosaic-run-spinner")).toBeTruthy();
  });
});
