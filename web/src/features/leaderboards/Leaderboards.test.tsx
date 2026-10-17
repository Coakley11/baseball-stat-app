import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MockScenario } from "@/lib/api/mock/mockClient";
import { nav } from "@/test/nextNavigation";
import { renderWithClient } from "@/test/renderWithClient";

import { Leaderboards } from "./Leaderboards";

vi.mock("next/navigation", async () => (await import("@/test/nextNavigation")).nextNavigationMock);

function open(search: string, scenario: MockScenario | (() => MockScenario) = "normal") {
  nav.reset("/players/leaderboards", search);
  return renderWithClient(<Leaderboards />, { scenario });
}

describe("Leaderboards", () => {
  beforeEach(() => nav.reset());

  it("leads with what is ranked, the top 3, and a top-10 visual", async () => {
    open("");
    expect(await screen.findByRole("heading", { level: 2, name: "José Ramírez leads 2020–2025 in weighted score: 954" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent("Ranked by weighted score · 2020–2025");

    const podium = screen.getByRole("heading", { name: "Top 3" }).closest("section")!;
    const cards = within(podium).getAllByRole("listitem");
    expect(cards.map((c) => c.textContent)).toEqual([
      expect.stringContaining("José Ramírez"),
      expect.stringContaining("Shohei Ohtani"),
      expect.stringContaining("Aaron Judge"),
    ]);
    expect(cards[0]).toHaveTextContent("Rank 1");

    const chart = screen.getByRole("figure", { name: "Top 10 by weighted score, 2020–2025" });
    expect(within(chart).getAllByRole("listitem")).toHaveLength(10);
  });

  it("states the qualification rule from the API for rate stats", async () => {
    open("metric=OPS");
    expect(await screen.findByRole("heading", { name: "Aaron Judge leads 2020–2025 in OPS: 1.058" })).toBeInTheDocument();
    expect(screen.getByText("Qualified hitters · at least 2,349 AB over 2020–2025")).toBeInTheDocument();
    expect(screen.getByText("142 qualified hitters ranked")).toBeInTheDocument();
  });

  it("explains the weighted score and keeps the full ranking under Explore more", async () => {
    open("");
    await screen.findByRole("heading", { name: /José Ramírez leads/ });
    expect(screen.getByText("HR + RBI + SB, each weighted 1. Other stats are weighted 0.")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(table.closest("details")).not.toHaveAttribute("open");
    expect(within(table).getByText(/Showing 15 of 1,604 ranked/)).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: /Score/ })).toHaveAttribute("aria-sort", "descending");
    // Corey Seager's walks are missing in the sample: shown as a dash, not zero.
    const seager = within(table).getByRole("row", { name: /Corey Seager/ });
    expect(seager).toHaveTextContent("—");
  });

  it("offers next steps into Historical Explorer", async () => {
    open("metric=HR");
    await screen.findByRole("heading", { name: /Aaron Judge leads 2020–2025 in home runs/ });
    const steps = screen.getByRole("navigation", { name: "Next steps" });
    expect(within(steps).getByRole("link", { name: "Aaron Judge's best seasons" })).toHaveAttribute("href", "/players/historical?player=judgeaa01");
    expect(within(steps).getByRole("link", { name: "Best single seasons, 2020–2025" })).toHaveAttribute("href", "/players/historical?from=2020");
  });

  it("shows a loading state", async () => {
    open("", "loading");
    expect(await screen.findByText("Ranking players…")).toBeInTheDocument();
  });

  it("asks for a stat when the URL names one that doesn't exist", async () => {
    open("metric=WAR");
    expect(await screen.findByRole("heading", { name: "Pick a stat to rank" })).toBeInTheDocument();
    expect(screen.getByLabelText("Rank by")).toHaveValue("");
  });

  it("explains when no hitter qualifies", async () => {
    open("metric=OPS", "empty");
    expect(await screen.findByRole("heading", { name: "No qualified hitters" })).toBeInTheDocument();
    expect(screen.getByText(/at least 2,349 AB over 2020–2025/)).toBeInTheDocument();
  });

  it("shows an error with Retry when the data service is unavailable", async () => {
    open("", "unavailable");
    expect(await screen.findByRole("alert")).toHaveTextContent("Baseball data is unavailable right now");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("commits the seasons on Enter, not on every keystroke", async () => {
    const user = userEvent.setup();
    open("");
    await screen.findByRole("heading", { name: /José Ramírez leads/ });
    const from = screen.getByLabelText("From season");
    await user.clear(from);
    await user.type(from, "2010");
    expect(nav.push).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    expect(nav.push).toHaveBeenLastCalledWith("/players/leaderboards?from=2010&to=2025", { scroll: false });
  });
});
