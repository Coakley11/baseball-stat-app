import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

const pathname = vi.hoisted(() => ({ value: "/players/historical" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));

beforeAll(() => {
  // jsdom has <dialog> but not its modal methods.
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

describe("AppShell navigation", () => {
  it("groups pages under the U1 section headings", () => {
    render(<AppShell>content</AppShell>);
    const sidebar = screen.getByRole("complementary", { name: "Sidebar" });
    const headings = within(sidebar).getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Players", "Insights", "Draft", "My League", "Account"]);

    const players = within(sidebar).getByRole("list", { name: "Players" });
    expect(within(players).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Historical Explorer",
      "Career Totals, Later",
      "Compare Players, Later",
      "Leaderboards",
    ]);
  });

  it("marks the current page with aria-current", () => {
    render(<AppShell>content</AppShell>);
    const sidebar = screen.getByRole("complementary", { name: "Sidebar" });
    expect(within(sidebar).getByRole("link", { name: "Historical Explorer" })).toHaveAttribute("aria-current", "page");
    expect(within(sidebar).getByRole("link", { name: "Leaderboards" })).not.toHaveAttribute("aria-current");
  });

  it("links only to pages that exist", () => {
    render(<AppShell>content</AppShell>);
    const sidebar = screen.getByRole("complementary", { name: "Sidebar" });
    expect(within(sidebar).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "/",
      "/",
      "/players/historical",
      "/players/leaderboards",
    ]);
    expect(within(sidebar).queryByRole("link", { name: /Live Draft/ })).toBeNull();
  });

  it("opens and closes the phone menu with the current page called out", async () => {
    const user = userEvent.setup();
    render(<AppShell>content</AppShell>);
    const dialog = document.getElementById("site-menu") as HTMLDialogElement;
    expect(dialog.open).toBe(false);

    await user.click(screen.getByRole("button", { name: "Menu" }));
    expect(dialog.open).toBe(true);
    expect(within(dialog).getByText("Historical Explorer", { selector: "strong" })).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Historical Explorer" })).toHaveAttribute("aria-current", "page");

    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(dialog.open).toBe(false);
  });

  it("offers a skip link to the main content", () => {
    render(<AppShell>content</AppShell>);
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });
});
