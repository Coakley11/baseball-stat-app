import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "@/lib/api/generated/baseball-api";
import { formatCount } from "@/lib/format";
import { nav } from "@/test/nextNavigation";
import { createRecordedClient, recorded, type RecordedClientOptions } from "@/test/recordedApi";
import { renderWithClient } from "@/test/renderWithClient";

import { HistoricalExplorer } from "./HistoricalExplorer";

vi.mock("next/navigation", async () => (await import("@/test/nextNavigation")).nextNavigationMock);

type Schemas = components["schemas"];
const HE_HR = "seasons?start=2010&end=2025&metric=HR&order=desc&limit=25";

function open(search: string, options: RecordedClientOptions = {}) {
  nav.reset("/players/historical", search);
  const recordedClient = createRecordedClient(options);
  renderWithClient(<HistoricalExplorer />, { client: recordedClient.client });
  return recordedClient;
}

describe("Historical Explorer on the real API (recorded)", () => {
  beforeEach(() => nav.reset());

  it("shows the API's headline and the real top-10 ranking, and nothing the API didn't send", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_HR);
    open("");
    expect(await screen.findByRole("heading", { level: 2, name: raw.headline! })).toBeInTheDocument();

    const answer = screen.getByRole("region", { name: "Answer" });
    expect(within(answer).queryByRole("term")).toBeNull(); // no tiles until R2
    expect(answer.querySelectorAll("p")).toHaveLength(2); // kicker + headline, no invented detail

    const chart = screen.getByRole("figure", { name: "Top 10 seasons by HR" });
    const bars = within(chart).getAllByRole("listitem");
    expect(bars).toHaveLength(10);
    raw.rows.slice(0, 10).forEach((row, i) => {
      expect(bars[i]).toHaveTextContent(row.player.name);
      expect(bars[i]).toHaveTextContent(String(row.stats.HR));
    });

    const table = screen.getByRole("table");
    expect(within(table).getByText(`Showing 25 of ${formatCount(raw.total_rows)} seasons`, { exact: false })).toBeInTheDocument();
    expect(within(table).getAllByText(raw.rows[0]!.team!.season_name!).length).toBeGreaterThan(0);
  });

  it("hides the one-player view and its links on real data", async () => {
    open("");
    await screen.findByRole("region", { name: "Answer" });
    expect(screen.queryByRole("group", { name: "Whose seasons" })).toBeNull();
    expect(screen.queryByText("One player")).toBeNull();
    const steps = screen.getByRole("navigation", { name: "Next steps" });
    expect(within(steps).getAllByRole("link").map((a) => a.textContent)).toEqual(["Leaders over 2010–2025"]);
    expect(screen.getByText("2010–2025 · HR · All players")).toBeInTheDocument();
  });

  it("answers a one-player link honestly instead of asking the API to guess", async () => {
    const { fetchImpl } = open("player=judgeaa01&metric=OPS");
    expect(await screen.findByRole("heading", { name: "One-player rankings aren't available yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Best seasons by every player" })).toHaveAttribute("href", "/players/historical?metric=OPS");
    expect(fetchImpl.mock.calls.map(([url]) => String(url))).not.toContainEqual(expect.stringContaining("/seasons"));
  });

  it("states the qualification minimum from the API's numbers", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>("seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25");
    open("metric=OPS");
    expect(await screen.findByRole("heading", { name: raw.headline! })).toBeInTheDocument();
    expect(screen.getByText(`At least ${formatCount(raw.qualification.min_ab)} AB (automatic qualification minimum)`)).toBeInTheDocument();
    expect(screen.queryByText(/Stat minimum filters/)).toBeNull();
  });

  it("shows the empty state for a real empty result", async () => {
    open("", { substitute: { [HE_HR]: `${HE_HR}&min_HR=100` } });
    expect(await screen.findByRole("heading", { name: "No seasons match" })).toBeInTheDocument();
  });

  it("shows the error state with Retry when the API is down, and recovers", async () => {
    const user = userEvent.setup();
    let down = true;
    open("", { fail: () => (down ? "network" : null) });
    expect(await screen.findByRole("alert")).toHaveTextContent("Baseball data is unavailable right now");
    down = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Answer" })).toBeInTheDocument();
  });
});
