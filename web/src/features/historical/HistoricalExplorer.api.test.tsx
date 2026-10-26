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
const HE_JUDGE = "seasons?metric=OPS&order=desc&player_id=judgeaa01&limit=25&include_below_minimum=true"; // career: no years sent
const CABRERA = "seasons?metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true";
const CABRERA_FROM = "seasons?start=2015&metric=OPS&order=desc&player_id=cabremi01&limit=25&include_below_minimum=true";

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
    // The chip, and the same line again beside the minimums controls.
    expect(screen.getAllByText(raw.qualification.summary).length).toBeGreaterThan(0);
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

  it("a page past the end says so and offers the first page, instead of an empty table", async () => {
    const user = userEvent.setup();
    open("page=9999");
    expect(await screen.findByRole("heading", { name: "That page is past the last season" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Back to the first page" }));
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical", { scroll: false });
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
    expect(screen.getByText(`${raw.start}–${raw.end} · OPS · Aaron Judge`)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Best seasons by every player" })).toHaveAttribute("href", "/players/historical?metric=OPS");
  });

  it("one player with no chosen years uses the player's whole career, as the API reports it", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(CABRERA);
    const { fetchImpl } = open("player=cabremi01&metric=OPS");
    expect(await screen.findByRole("heading", { level: 2, name: raw.answer!.headline })).toBeInTheDocument();
    expect(fetchImpl.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("player_id")).every((u) => !/[?&](start|end)=/.test(u))).toBe(true);
    // The boxes show the career the API returned, not the all-players default.
    expect(screen.getByLabelText("From season")).toHaveValue(String(raw.start));
    expect(screen.getByLabelText("To season")).toHaveValue(String(raw.end));
    expect(raw.start).toBeLessThan(2010);
    expect(screen.getByText(`${raw.start}–${raw.end} · OPS · Miguel Cabrera`)).toBeInTheDocument();
    // Below-minimum career seasons are shown, unranked and marked.
    const table = within(screen.getByRole("region", { name: "Seasons" })).getByRole("table");
    expect(within(table).getAllByText("Below the minimum")).toHaveLength(raw.rows.filter((r) => !r.meets_minimum).length);
  });

  it("one player: a chosen bound is kept and the other is still the career", async () => {
    const raw = recorded<Schemas["SeasonLeadersResult"]>(CABRERA_FROM);
    const { fetchImpl } = open("player=cabremi01&metric=OPS&from=2015");
    expect(await screen.findByRole("heading", { level: 2, name: raw.answer!.headline })).toBeInTheDocument();
    expect(fetchImpl.mock.calls.some(([u]) => String(u).endsWith(CABRERA_FROM))).toBe(true);
    expect(screen.getByLabelText("From season")).toHaveValue("2015");
    expect(screen.getByLabelText("To season")).toHaveValue(String(raw.end));
  });

  it("all players keep the default range", async () => {
    open("");
    await screen.findByRole("region", { name: "Answer" });
    expect(screen.getByLabelText("From season")).toHaveValue("2010");
    expect(screen.getByLabelText("To season")).toHaveValue("2025");
  });

  it("choosing One player alone doesn't put the all-players range in the URL", async () => {
    const user = userEvent.setup();
    open("");
    await screen.findByRole("region", { name: "Answer" });
    await user.click(screen.getByText("One player"));
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical?scope=player", { scroll: false });
  });

  it("the link from a player's seasons back to all players doesn't carry the career as a chosen range", async () => {
    open("player=cabremi01&metric=OPS");
    await screen.findByRole("region", { name: "Answer" });
    expect(screen.getByRole("link", { name: "Best seasons by every player" })).toHaveAttribute("href", "/players/historical?metric=OPS");
  });

  it("minimums: Apply writes them to the URL; the API's own line says what applies", async () => {
    const user = userEvent.setup();
    open("");
    await screen.findByRole("region", { name: "Answer" });
    expect(screen.getByRole("button", { name: "Apply minimums" })).toBeDisabled();
    await user.type(screen.getByLabelText("Minimum at-bats"), "500");
    await user.type(screen.getByLabelText("Minimum HR"), "30");
    await user.click(screen.getByRole("button", { name: "Apply minimums" }));
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical?minab=500&mins=HR%3A30", { scroll: false });
  });

  it("minimums in the URL go to the API and its qualification line is shown", async () => {
    const OPS_BOTH = "seasons?start=2010&end=2025&metric=OPS&order=desc&min_ab=300&min_HR=30&limit=25";
    const raw = recorded<Schemas["SeasonLeadersResult"]>(OPS_BOTH);
    const { fetchImpl } = open("metric=OPS&minab=300&mins=HR:30");
    expect(await screen.findByRole("heading", { level: 2, name: raw.answer!.headline })).toBeInTheDocument();
    expect(fetchImpl.mock.calls.some(([u]) => String(u).endsWith(OPS_BOTH))).toBe(true);
    expect(screen.getAllByText("Minimum you set · at least 300 AB in the season").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Minimum at-bats")).toHaveValue(300);
    expect(screen.getByLabelText("Minimum HR")).toHaveValue(30);
    expect(screen.getByText(/of .+ seasons/, { selector: "caption" })).toHaveTextContent(`of ${formatCount(raw.total_rows)} seasons`);
    expect(screen.getByText("2010–2025 · OPS · All players · Filtered")).toBeInTheDocument();
  });

  it("0 at-bats means no minimum, and Reset clears every minimum", async () => {
    const user = userEvent.setup();
    const OPS_ZERO = "seasons?start=2010&end=2025&metric=OPS&order=desc&min_ab=0&limit=25";
    open("metric=OPS&minab=0");
    expect(await screen.findByRole("heading", { name: recorded<Schemas["SeasonLeadersResult"]>(OPS_ZERO).answer!.headline })).toBeInTheDocument();
    expect(screen.getAllByText("No at-bat minimum · part-time players can lead this list").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Minimum at-bats")).toHaveValue(0);
    await user.click(screen.getByRole("button", { name: "Reset minimums" }));
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical?metric=OPS", { scroll: false });
  });

  it("several franchises: each checkbox adds to the URL list, and Clear empties it", async () => {
    const user = userEvent.setup();
    open("team=Boston+Red+Sox");
    await screen.findByRole("region", { name: "Answer" });
    expect(screen.getByLabelText("Boston Red Sox")).toBeChecked();
    expect(screen.getByText(/1 selected/)).toBeInTheDocument();
    await user.click(screen.getByLabelText("New York Yankees"));
    expect(nav.push).toHaveBeenLastCalledWith("/players/historical?team=Boston+Red+Sox%2CNew+York+Yankees", { scroll: false });
  });

  it("several franchises in the URL: the API's union, with both checked", async () => {
    const both = "seasons?start=2010&end=2025&metric=HR&order=desc&teams=Boston+Red+Sox%2CNew+York+Yankees&limit=25";
    const raw = recorded<Schemas["SeasonLeadersResult"]>(both);
    open("team=Boston+Red+Sox,New+York+Yankees");
    expect(await screen.findByRole("heading", { level: 2, name: raw.answer!.headline })).toBeInTheDocument();
    expect(screen.getByLabelText("Boston Red Sox")).toBeChecked();
    expect(screen.getByLabelText("New York Yankees")).toBeChecked();
    expect(screen.getByText(/2 selected/)).toBeInTheDocument();
    expect(screen.getByText(/of .+ seasons/, { selector: "caption" })).toHaveTextContent(`of ${formatCount(raw.total_rows)} seasons`);
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
