import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MockScenario } from "@/lib/api/mock/mockClient";
import { nav } from "@/test/nextNavigation";
import { renderWithClient } from "@/test/renderWithClient";

import { HistoricalExplorer } from "./HistoricalExplorer";

vi.mock("next/navigation", async () => (await import("@/test/nextNavigation")).nextNavigationMock);

function open(search: string, scenario: MockScenario | (() => MockScenario) = "normal") {
  nav.reset("/players/historical", search);
  return renderWithClient(<HistoricalExplorer />, { scenario });
}

describe("Historical Explorer", () => {
  beforeEach(() => nav.reset());

  it("answers first: headline, key metrics, default chart, next steps", async () => {
    open("");
    expect(await screen.findByRole("heading", { level: 2, name: "Aaron Judge, 2022: 62 home runs" })).toBeInTheDocument();

    const answer = screen.getByRole("region", { name: "Answer" });
    expect(answer).toHaveTextContent("2022 · NYY · RF");
    expect(within(answer).getAllByRole("term").map((t) => t.textContent)).toEqual(["HR", "RBI", "AVG", "OPS"]);
    expect(within(answer).getAllByRole("definition").map((d) => d.textContent)).toEqual(["62", "131", ".311", "1.111"]);

    const chart = screen.getByRole("figure", { name: "Top 10 seasons by home runs" });
    expect(within(chart).getAllByRole("listitem")).toHaveLength(10);
    expect(within(chart).getByText("Answer")).toBeInTheDocument();

    const steps = screen.getByRole("navigation", { name: "Next steps" });
    expect(within(steps).getByRole("link", { name: "All of Aaron Judge's seasons" })).toHaveAttribute(
      "href",
      "/players/historical?player=judgeaa01",
    );
    expect(within(steps).getByRole("link", { name: "Leaders over 2010–2025" })).toHaveAttribute(
      "href",
      "/players/leaderboards?from=2010&to=2025&metric=HR",
    );
  });

  it("states the qualification rule for rate stats", async () => {
    open("metric=OPS");
    expect(await screen.findByRole("heading", { name: "Aaron Judge, 2024: 1.159 OPS" })).toBeInTheDocument();
    expect(screen.getByText("Qualified seasons · at least 437 AB in the season")).toBeInTheDocument();
  });

  it("shows one player's seasons as a timeline with below-minimum seasons marked", async () => {
    open("player=judgeaa01&metric=OPS");
    expect(await screen.findByRole("figure", { name: "Aaron Judge · OPS by season" })).toBeInTheDocument();
    expect(screen.getAllByText("Below the at-bat minimum").length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: /10 seasons from 2016 to 2025/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Best seasons by every player" })).toHaveAttribute("href", "/players/historical?metric=OPS");
  });

  it("puts every season in a table under Explore more", async () => {
    open("");
    await screen.findByRole("heading", { name: "Aaron Judge, 2022: 62 home runs" });
    const table = screen.getByRole("table");
    expect(within(table).getByText(/Showing 15 of 9,718 seasons/)).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: /HR/ })).toHaveAttribute("aria-sort", "descending");
    expect(table.closest("details")).not.toHaveAttribute("open");
  });

  it("asks for a player when 'One player' has none yet", async () => {
    open("scope=player");
    expect(await screen.findByRole("heading", { name: "Choose a player" })).toBeInTheDocument();
    expect(screen.getByLabelText("Find a player")).toBeInTheDocument();
  });

  it("finds and selects a player", async () => {
    const user = userEvent.setup();
    open("scope=player");
    await user.type(await screen.findByLabelText("Find a player"), "guerr");
    await user.click(await screen.findByRole("button", { name: /Vladimir Guerrero Jr\./ }));
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical?player=guerrvl02", { scroll: false });
  });

  it("shows a loading state while the answer is on its way", async () => {
    open("", "loading");
    // The catalog arrives first; then the answer's own loading state stays up.
    expect(await screen.findByText("Finding seasons…")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByRole("region", { name: "Answer" })).toBeNull();
  });

  it("shows an error with Retry when the data service is unavailable", async () => {
    const user = userEvent.setup();
    let scenario: MockScenario = "unavailable";
    open("", () => scenario);
    expect(await screen.findByRole("alert")).toHaveTextContent("Baseball data is unavailable right now");
    scenario = "normal";
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Aaron Judge, 2022: 62 home runs" })).toBeInTheDocument();
  });

  it("shows an empty state when nothing matches", async () => {
    open("", "empty");
    expect(await screen.findByRole("heading", { name: "No seasons match" })).toBeInTheDocument();
  });

  it("says when a question isn't available rather than showing other numbers", async () => {
    open("from=1990&to=2000");
    expect(await screen.findByRole("heading", { name: "Not available yet" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Answer" })).toBeNull();
  });

  it("catches an unknown stat in the URL without asking the API", async () => {
    open("metric=WAR");
    expect(await screen.findByRole("heading", { name: "Pick a stat to rank" })).toBeInTheDocument();
    expect(screen.getByLabelText("Rank by")).toHaveValue("");
  });

  it("changing the stat updates the URL", async () => {
    const user = userEvent.setup();
    open("");
    await screen.findByRole("heading", { name: "Aaron Judge, 2022: 62 home runs" });
    await user.selectOptions(screen.getByLabelText("Rank by"), "OPS");
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical?metric=OPS", { scroll: false });
  });
});
