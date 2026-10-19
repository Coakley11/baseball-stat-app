import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HomeView } from "./HomeView";

describe("Home", () => {
  it("leads with the four task cards", () => {
    render(<HomeView />);
    expect(screen.getByRole("heading", { level: 1, name: "What would you like to do?" })).toBeInTheDocument();
    const tasks = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(tasks).toEqual(["Explore Players", "Compare Players", "Prepare for a Draft", "Manage My League"]);
  });

  it("sends Explore Players to the implemented pages", () => {
    render(<HomeView />);
    const card = screen.getByRole("group", { name: "Explore Players" });
    expect(within(card).getByRole("link", { name: "Find the best seasons" })).toHaveAttribute("href", "/players/historical");
    expect(within(card).getByRole("link", { name: "Leaderboards" })).toHaveAttribute("href", "/players/leaderboards");
  });

  it.each(["Compare Players", "Prepare for a Draft", "Manage My League"])(
    "marks %s as coming later without a fake button",
    (name) => {
      render(<HomeView />);
      const card = screen.getByRole("group", { name });
      expect(within(card).getByText("Coming later")).toBeInTheDocument();
      expect(within(card).queryByRole("link")).toBeNull();
      expect(within(card).queryByRole("button")).toBeNull();
    },
  );

  it("links ready-made questions only to implemented pages", () => {
    render(<HomeView />);
    const list = screen.getByRole("heading", { name: "Try a question" }).closest("section")!;
    for (const link of within(list).getAllByRole("link")) {
      expect(link.getAttribute("href")).toMatch(/^\/players\/(historical|leaderboards)/);
    }
  });

  it("reserves Ask AMI without an input or assistant", () => {
    render(<HomeView />);
    const ami = screen.getByRole("heading", { name: "Ask a question in plain English" }).closest("section")!;
    expect(within(ami).getByText(/Ask AMI/)).toBeInTheDocument();
    expect(within(ami).queryByRole("textbox")).toBeNull();
    expect(within(ami).queryByRole("button")).toBeNull();
  });
});
