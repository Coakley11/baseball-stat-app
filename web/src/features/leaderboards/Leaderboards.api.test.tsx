import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { formatCount } from "@/lib/format";
import { nav } from "@/test/nextNavigation";
import { createRecordedClient, recorded } from "@/test/recordedApi";
import { renderWithClient } from "@/test/renderWithClient";

import { Leaderboards } from "./Leaderboards";

vi.mock("next/navigation", async () => (await import("@/test/nextNavigation")).nextNavigationMock);

type Schemas = components["schemas"];

function open(search: string) {
  nav.reset("/players/leaderboards", search);
  renderWithClient(<Leaderboards />, { client: createRecordedClient().client });
}

describe("Leaderboards on the real API (recorded)", () => {
  beforeEach(() => nav.reset());

  it("titles the ranking without inventing an answer, then shows the real top 3, bars and weights", async () => {
    const raw = recorded<Schemas["LeaderboardResult"]>("leaderboards?start=2020&end=2025&metric=score&limit=25");
    open("");
    expect(await screen.findByRole("heading", { level: 2, name: "Leaders by Score, 2020–2025" })).toBeInTheDocument();

    const podium = screen.getByRole("heading", { name: "Top 3" }).closest("section")!;
    const cards = within(podium).getAllByRole("listitem");
    raw.rows.slice(0, 3).forEach((row, i) => {
      expect(cards[i]).toHaveTextContent(row.player.name);
      // The API sends no seasons count and G is null on leaderboard rows: no sub-line is shown.
      expect(row.stats.G).toBeNull();
      expect(cards[i]).not.toHaveTextContent(/games|seasons/);
    });

    expect(within(screen.getByRole("figure", { name: "Top 10 by Score, 2020–2025" })).getAllByRole("listitem")).toHaveLength(10);
    expect(screen.getByText("Weights in this score: HR ×1, RBI ×1, SB ×1.")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText(`Showing 25 of ${formatCount(raw.total_rows)} ranked`, { exact: false })).toBeInTheDocument();
  });

  it("shows the API's qualification minimum and qualified count for OPS", async () => {
    const raw = recorded<Schemas["LeaderboardResult"]>("leaderboards?start=2020&end=2025&metric=OPS&limit=25");
    open("metric=OPS");
    expect(await screen.findByRole("heading", { name: "Leaders by OPS, 2020–2025" })).toBeInTheDocument();
    expect(screen.getByText(`At least ${formatCount(raw.qualification.min_ab)} AB (automatic qualification minimum)`)).toBeInTheDocument();
    expect(screen.getByText(`${formatCount(raw.total_rows)} qualified hitters ranked`)).toBeInTheDocument();
  });

  it("offers only next steps the real API can answer", async () => {
    open("metric=HR");
    await screen.findByRole("heading", { name: "Leaders by HR, 2020–2025" });
    const steps = screen.getByRole("navigation", { name: "Next steps" });
    const links = within(steps).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual(["Best single seasons, 2020–2025"]);
    expect(links[0]).toHaveAttribute("href", "/players/historical?from=2020");
  });
});
