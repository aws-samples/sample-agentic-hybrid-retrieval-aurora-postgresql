// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AgentNoticeNote } from "./AgentNoticeNote";

afterEach(cleanup);

const notice = { title: "Reference Retrieval agent", detail: "This answer comes from the reference agent." };

it("renders the title and the detail", () => {
  render(<AgentNoticeNote notice={notice} />);
  expect(screen.getByText(notice.title)).toBeTruthy();
  expect(screen.getByText(notice.detail)).toBeTruthy();
});

it("names the note by its visible title instead of repeating it in an aria-label", () => {
  render(<AgentNoticeNote notice={notice} />);
  const note = screen.getByRole("note", { name: notice.title });
  expect(note.hasAttribute("aria-label")).toBe(false);
  const heading = document.getElementById(note.getAttribute("aria-labelledby") ?? "");
  expect(heading?.textContent).toBe(notice.title);
});

it("gives two notes on one page different label targets", () => {
  render(<><AgentNoticeNote notice={notice} /><AgentNoticeNote notice={notice} /></>);
  const [first, second] = screen.getAllByRole("note");
  expect(first.getAttribute("aria-labelledby")).not.toBe(second.getAttribute("aria-labelledby"));
});
