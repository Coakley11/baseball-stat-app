import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { formatCount } from "@/lib/format";
import { nav } from "@/test/nextNavigation";
import { createRecordedClient, recorded } from "@/test/recordedApi";
import { renderWithClient } from "@/test/renderWithClient";

import { Leaderboards } from "./Leaderboards";

vi.mock("next/navigation", async () => (await import("@/test/nextNavigation")).nextNavigationMock);

type Schemas = components["schemas"];
const LB = "leaderboards?start=2020&end=2025&metric=score&limit=25";
const LB_OPS = "leaderboards?start=2020&end=2025&metric=OPS&limit=25";
const LB_WEIGHTED = "leaderboards?start=2020&end=2025&metric=score&weights=HR%3A2%2CRBI%3A1&limit=25";
const LB_TOP10 = "leaderboards?start=2020&end=2025&metric=score&limit=10";

function open(search: string) {
  nav.reset("/players/leaderboards", search);
  const recordedClient = createRecordedClient();
  renderWithClient(<Leaderboards />, { client: recordedClient.client });
  return recordedClient;
}

describe("Leaderboards on the real API (recorded, 5ca7a26)", () => {
  beforeEach(() => nav.reset());

  it("shows the API's answer, the real top 3 with their at-bats, and the top-10 bars", async () => {
    const raw = recorded<Schemas["LeaderboardResult"]>(LB);
    open("");
    expect(await screen.findByRole("heading", { level: 2, name: raw.answer!.headline })).toBeInTheDocument();
    const answer = screen.getByRole("region", { name: "Answer" });
    expect(answer).toHaveTextContent(raw.answer!.context);
    expect(answer).toHaveTextContent(raw.answer!.body);
    expect(answer.textContent).not.toMatch(/Explore more|Change the weights/);

    const podium = screen.getByRole("heading", { name: "Top 3" }).closest("section")!;
    const cards = within(podium).getAllByRole("listitem");
    raw.rows.slice(0, 3).forEach((row, i) => {
      expect(cards[i]).toHaveTextContent(row.player.name);
      expect(cards[i]).toHaveTextContent(`${formatCount(row.stats.AB!)} AB`); // authoritative sub-line, no games/seasons
      expect(cards[i]).toHaveTextContent(`Rank ${row.rank}`);
    });
    expect(within(screen.getByRole("figure", { name: "Top 10 by score, 2020–2025" })).getAllByRole("listitem")).toHaveLength(10);
  });

  it("draws the table from the API's column list, ending in Score", async () => {
    const raw = recorded<Schemas["LeaderboardResult"]>(LB);
    const catalog = recorded<Schemas["Catalog"]>("catalog");
    open("");
    await screen.findByRole("region", { name: "Answer" });
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent?.replace(/ [↑↓]$/, ""))).toEqual([
      "#",
      ...catalog.leaderboards.columns.map((c) => c.label),
    ]);
    expect(within(table).getByRole("columnheader", { name: /^Score/ })).toHaveAttribute("aria-sort", "descending");
    const first = within(table).getAllByRole("row")[1]!;
    expect(first).toHaveTextContent(raw.rows[0]!.player.name);
    expect(within(first).getAllByRole("cell").at(-1)).toHaveTextContent(String(Math.round(raw.rows[0]!.score * 10) / 10));
    expect(within(table).getByText(new RegExp(`Top 25 of ${formatCount(raw.total_rows)} ranked by score`))).toBeInTheDocument();
  });

  it("states the qualification chip and explanation from the API for rate stats", async () => {
    const raw = recorded<Schemas["LeaderboardResult"]>(LB_OPS);
    open("metric=OPS");
    expect(await screen.findByRole("heading", { name: raw.answer!.headline })).toBeInTheDocument();
    expect(screen.getByText(raw.qualification.summary)).toBeInTheDocument();
    expect(screen.getByText(raw.qualification.explanation!)).toBeInTheDocument();
    expect(screen.getByText(`${formatCount(raw.total_rows)} qualified hitters ranked`)).toBeInTheDocument();
    expect(screen.queryByText(/Stat minimum filters/)).toBeNull();
  });

  it("Top N: asks the API for that many players", async () => {
    const user = userEvent.setup();
    const raw = recorded<Schemas["LeaderboardResult"]>(LB_TOP10);
    const { fetchImpl } = open("top=10");
    expect(await screen.findByRole("region", { name: "Answer" })).toBeInTheDocument();
    expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith(LB_TOP10))).toBe(true);
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(raw.rows.length + 1);
    expect(screen.getByLabelText("Players shown")).toHaveValue("10");

    await user.selectOptions(screen.getByLabelText("Players shown"), "50");
    expect(nav.push).toHaveBeenLastCalledWith("/players/leaderboards?top=50", { scroll: false });
  });

  it("custom weights: Apply sends them to the API, and the answer reflects the API's result", async () => {
    const user = userEvent.setup();
    const raw = recorded<Schemas["LeaderboardResult"]>(LB_WEIGHTED);
    const { fetchImpl } = open("w=HR:2,RBI:1");
    expect(await screen.findByRole("heading", { name: raw.answer!.headline })).toBeInTheDocument();
    expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith(LB_WEIGHTED))).toBe(true);
    expect(screen.getByLabelText("HR")).toHaveValue(2);
    expect(screen.getByLabelText("SB")).toHaveValue(0);

    // Changing a weight enables Apply; applying writes it to the URL (the API recomputes).
    expect(screen.getByRole("button", { name: "Apply weights" })).toBeDisabled();
    await user.clear(screen.getByLabelText("SB"));
    await user.type(screen.getByLabelText("SB"), "1");
    await user.click(screen.getByRole("button", { name: "Apply weights" }));
    expect(nav.push).toHaveBeenLastCalledWith("/players/leaderboards?w=HR%3A2%2CRBI%3A1%2CSB%3A1", { scroll: false });
  });

  it("won't apply weights that are all zero or out of bounds", async () => {
    const user = userEvent.setup();
    open("");
    await screen.findByRole("region", { name: "Answer" });
    for (const stat of ["HR", "RBI", "SB"]) {
      await user.clear(screen.getByLabelText(stat));
      await user.type(screen.getByLabelText(stat), "0");
    }
    expect(screen.getByRole("button", { name: "Apply weights" })).toBeDisabled();
    expect(screen.getByText(/at least one above zero/)).toBeInTheDocument();
  });

  it("links to the API's CSV for the Top N shown", async () => {
    open("");
    await screen.findByRole("region", { name: "Answer" });
    const link = screen.getByRole("link", { name: "Download CSV" });
    expect(link).toHaveAttribute("href", "http://recorded.test/api/v1/leaderboards?start=2020&end=2025&metric=score&limit=25&format=csv");
    expect(link).toHaveAttribute("download");
  });

  it("offers next steps into Historical Explorer, including the leader's own seasons", async () => {
    const raw = recorded<Schemas["LeaderboardResult"]>("leaderboards?start=2020&end=2025&metric=HR&limit=25");
    open("metric=HR");
    await screen.findByRole("heading", { name: raw.answer!.headline });
    const steps = screen.getByRole("navigation", { name: "Next steps" });
    const links = within(steps).getAllByRole("link");
    expect(links[0]).toHaveTextContent(`${raw.rows[0]!.player.name}'s best seasons`);
    expect(links[0]).toHaveAttribute("href", `/players/historical?player=${raw.rows[0]!.player.player_id}`);
    expect(links[1]).toHaveAttribute("href", "/players/historical?from=2020");
  });
});
