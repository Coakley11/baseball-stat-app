import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { QuestionBar } from "./QuestionControls";

describe("QuestionBar (phone summary)", () => {
  it("summarises the question and reveals the same controls on Change", async () => {
    const user = userEvent.setup();
    render(
      <QuestionBar label="Your question" summary="2010–2025 · Home runs · All players">
        <label>
          Rank by <select />
        </label>
      </QuestionBar>,
    );
    expect(screen.getByText("2010–2025 · Home runs · All players")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Change" });
    const fields = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(fields).not.toHaveAttribute("data-open");
    // The controls are in the document either way (hidden on phones by CSS only).
    expect(screen.getByLabelText("Rank by")).toBeInTheDocument();

    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Done" })).toHaveAttribute("aria-expanded", "true");
    expect(fields).toHaveAttribute("data-open");

    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(fields).not.toHaveAttribute("data-open");
  });

  it("stays open, with no toggle, when the user has to act", () => {
    render(
      <QuestionBar label="Your question" summary="2010–2025 · Choose a stat" forceOpen>
        <span>controls</span>
      </QuestionBar>,
    );
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
    expect(screen.getByText("controls").parentElement).toHaveAttribute("data-open");
  });
});
