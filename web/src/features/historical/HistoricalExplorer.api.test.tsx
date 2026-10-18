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
const HE_OPS = "seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25";
const HE_PAGE2 = `${HE_HR}&offset=25`;
const HE_FILTERED = "seasons?start=2010&end=2025&metric=HR&order=desc&bats=L&positions=SS&position_source=season&limit=25";
const HE_JUDGE = "seasons?start=2010&end=2025&metric=OPS&order=desc&player_id=judgeaa01&limit=25&include_below_minimum=true";

function open(search: string, options: RecordedClientOptions = {}) {
  nav.reset("/players/historical", search);
  const recordedClient = createRecordedClient(options);
  renderWithClient(<HistoricalExplorer />, { client: recordedClient.client });
  return recordedClient;
}

describe("Historical Explorer on the real API (recorded, 5ca7a26)", () => {
  beforeEach(() => nav.reset());

  it("shows the API's answer, context, tiles, qualification-free counting stat, chart and next step", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_HR);
    open("");
    expect(await screen.findByRole("heading", { level: 2, name: raw.answer!.headline })).toBeInTheDocument();

    const answer = screen.getByRole("region", { name: "Answer" });
    expect(answer).toHaveTextContent(raw.answer!.context);
    expect(answer).toHaveTextContent(raw.answer!.body);
    // Tiles: the API's metric list, in order, valued from the top season's stats.
    const labels = within(answer).getAllByRole("term").map((t) => t.textContent);
    const catalog = recorded<Schemas["Catalog"]>("catalog");
    expect(labels).toEqual(raw.answer!.tile_metrics.map((k) => catalog.metrics.find((m) => m.key === k)!.label));
    expect(within(answer).getAllByRole("definition")[0]).toHaveTextContent(String(raw.rows[0]!.stats.HR));
    expect(screen.queryByText(/^Qualified/)).toBeNull(); // counting stat: no qualification chip

    const chart = screen.getByRole("figure", { name: "Top 10 seasons by home runs" });
    const bars = within(chart).getAllByRole("listitem");
    expect(bars).toHaveLength(10);
    raw.rows.slice(0, 10).forEach((row, i) => {
      expect(bars[i]).toHaveTextContent(row.player.name);
      expect(bars[i]).toHaveTextContent(String(row.stats.HR));
    });

    const steps = screen.getByRole("navigation", { name: "Next steps" });
    expect(within(steps).getByRole("link", { name: /All of .+'s seasons/ })).toBeInTheDocument();
    expect(within(steps).getByRole("link", { name: "Leaders over 2010–2025" })).toBeInTheDocument();
  });

  it("states the qualification the API describes, and explains it under Explore more", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_OPS);
    open("metric=OPS");
    expect(await screen.findByRole("heading", { name: raw.answer!.headline })).toBeInTheDocument();
    expect(screen.getByText(raw.qualification.summary)).toBeInTheDocument();
    expect(screen.getByText(raw.qualification.explanation!)).toBeInTheDocument();
    expect(screen.queryByText(/Stat minimum filters/)).toBeNull();
  });

  it("draws the table from the API's column list: headers, order, formats and values", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_HR);
    const catalog = recorded<Schemas["Catalog"]>("catalog");
    open("");
    await screen.findByRole("region", { name: "Answer" });

    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent?.replace(/ [↑↓]$/, ""))).toEqual([
      "#",
      ...catalog.historical.columns.map((c) => c.label),
    ]);
    expect(within(table).getByRole("columnheader", { name: /^HR/ })).toHaveAttribute("aria-sort", "descending");
    expect(within(table).getByText(new RegExp(`Rows 1–25 of ${formatCount(raw.total_rows)} seasons`))).toBeInTheDocument();

    const first = within(table).getAllByRole("row")[1]!;
    const row = raw.rows[0]!;
    expect(first).toHaveTextContent(row.player.name);
    expect(within(first).getAllByRole("cell")[0]).toHaveTextContent(String(row.rank)); // # column
    expect(first).toHaveTextContent(String(row.year)); // year: "2022", never "2,022"
    expect(first.textContent).not.toContain(formatCount(row.year));
    expect(first).toHaveTextContent(row.team!.season_name!);
    const cells = within(first).getAllByRole("cell").map((c) => c.textContent);
    expect(cells).toContain(String(row.stats.HR));
    expect(cells).toContain(row.stats.BA!.toFixed(3).replace(/^0/, "")); // rates like ".311"
  });

  it("pages through the ranking with Previous / Next, using the API's offset", async () => {
    const user = userEvent.setup();
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_HR);
    open("");
    await screen.findByRole("region", { name: "Answer" });
    expect(screen.getByText(`Rows 1–25 of ${formatCount(raw.total_rows)}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical?page=2", { scroll: false });
  });

  it("shows page two from its offset, continuing the ranks", async () => {
    const raw2 = recorded<Schemas["SeasonLeadersResult"]>(HE_PAGE2);
    open("page=2");
    expect(await screen.findByText(new RegExp(`Rows 26–50 of ${formatCount(raw2.total_rows)} seasons`))).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(within(table).getAllByRole("row")[1]!).getAllByRole("cell")[0]).toHaveTextContent("26");
    expect(screen.getByRole("heading", { level: 2, name: recorded<Schemas["SeasonLeadersResult"]>(HE_HR).answer!.headline })).toBeInTheDocument(); // the answer is still page one's
  });

  it("applies filters through the API and says the answer is filtered", async () => {
    const user = userEvent.setup();
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_FILTERED);
    const { fetchImpl } = open("bats=L&pos=SS");
    expect(await screen.findByRole("heading", { name: raw.answer!.headline })).toBeInTheDocument();
    expect(fetchImpl.mock.calls.some(([url]) => String(url).endsWith(HE_FILTERED))).toBe(true);
    expect(screen.getByText("2010–2025 · Home runs · All players · Filtered")).toBeInTheDocument();
    expect(screen.getByLabelText("Left")).toBeChecked();
    expect(screen.getByLabelText("SS")).toBeChecked();

    await user.click(screen.getByLabelText("Right"));
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical?bats=L%2CR&pos=SS", { scroll: false });
  });

  it("links to the API's CSV export for every ranked row, and builds no file itself", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_HR);
    open("");
    await screen.findByRole("region", { name: "Answer" });
    const link = screen.getByRole("link", { name: "Download CSV" });
    expect(link).toHaveAttribute("href", "http://recorded.test/api/v1/seasons?start=2010&end=2025&metric=HR&order=desc&format=csv");
    expect(link).toHaveAttribute("download");
    expect(link.getAttribute("href")).not.toMatch(/limit|offset/);
    expect(screen.getByText(new RegExp(`Every ranked season for this question \\(${formatCount(raw.ranked_rows)}\\)`))).toBeInTheDocument();
  });

  it("one player: the API's timeline with below-minimum seasons marked, unranked and noted in the table", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(HE_JUDGE);
    open("player=judgeaa01&metric=OPS");
    expect(await screen.findByRole("heading", { level: 2, name: raw.answer!.headline })).toBeInTheDocument();
    expect(screen.getByRole("figure", { name: /Aaron Judge · OPS by season/ })).toBeInTheDocument();
    expect(screen.getAllByText("Below the minimum").length).toBeGreaterThan(0);

    const belowCount = raw.rows.filter((r) => !r.meets_minimum).length;
    const table = within(screen.getByRole("region", { name: "Seasons" })).getByRole("table");
    expect(within(table).getAllByText("Below the minimum")).toHaveLength(belowCount);
    expect(screen.getByText("2010–2025 · OPS · Aaron Judge")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Best seasons by every player" })).toHaveAttribute("href", "/players/historical?metric=OPS");
  });

  it("offers the one-player choice and a player search", async () => {
    open("scope=player");
    expect(await screen.findByRole("heading", { name: "Choose a player" })).toBeInTheDocument();
    expect(screen.getByLabelText("Find a player")).toBeInTheDocument();
    expect(screen.getByText("One player")).toBeInTheDocument();
  });

  it("shows the empty state for a real empty result", async () => {
    open("", { substitute: { [HE_HR]: `${HE_HR}&min_HR=100` } });
    expect(await screen.findByRole("heading", { name: "No seasons match" })).toBeInTheDocument();
  });

  it("waits out the API's cold start without showing an error", async () => {
    open("", { warmingUp: 2 });
    expect(await screen.findByRole("region", { name: "Answer" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
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
