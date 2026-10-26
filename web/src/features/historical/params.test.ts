import { describe, expect, it } from "vitest";

import { NO_HISTORICAL_FILTERS, NO_MINIMUMS } from "@/lib/api";
import { CATALOG } from "@/lib/api/mock/fixtures/catalog";

import { historicalHref, readHistoricalParams } from "./params";

const read = (search: string) => readHistoricalParams(new URLSearchParams(search), CATALOG);

describe("Historical Explorer URL", () => {
  it("uses the catalog defaults for a bare URL", () => {
    const state = read("");
    expect(state.query).toEqual({
      yearRange: { start: 2010, end: 2025 },
      metric: "HR",
      order: "desc",
      playerId: null,
      filters: NO_HISTORICAL_FILTERS,
      minimums: NO_MINIMUMS,
      explicitRange: { start: false, end: false },
    });
    expect(state.rawRange).toEqual({ start: "2010", end: "2025" });
    expect(state.scope).toBe("all");
    expect(state.issue).toBeNull();
  });

  it("reads a full question", () => {
    const state = read("from=2015&to=2020&metric=OPS&order=asc&player=judgeaa01");
    expect(state.query).toEqual({
      yearRange: { start: 2015, end: 2020 },
      metric: "OPS",
      order: "asc",
      playerId: "judgeaa01",
      filters: NO_HISTORICAL_FILTERS,
      minimums: NO_MINIMUMS,
      explicitRange: { start: true, end: true },
    });
    expect(state.scope).toBe("player");
  });

  it("reads filters and the table page, ignoring values the catalog doesn't offer", () => {
    const state = read("bats=L,X&psrc=career&pos=SS,ZZ&team=American+League,All+Teams&combine=1&page=3");
    expect(state.query.filters).toEqual({ bats: ["L"], positionSource: "career", positions: ["SS"], teams: ["American League"], combine: true });
    expect(state.page).toBe(3);
    expect(read("page=0").page).toBe(1);
    expect(read("page=abc").page).toBe(1);
  });

  it("round-trips filters through a link", () => {
    const filters = { bats: ["B"], positionSource: "season" as const, positions: ["C"], teams: [], combine: true };
    const href = historicalHref({ ...read("").query, filters }, CATALOG);
    expect(href).toBe("/players/historical?bats=B&pos=C&combine=1");
    expect(read(href.split("?")[1]!).query.filters).toEqual(filters);
  });

  it("one player: only the bounds the user chose are explicit; the rest is the player's career", () => {
    const none = read("player=cabremi01");
    expect(none.query.explicitRange).toEqual({ start: false, end: false });
    expect(none.rawRange).toEqual({ start: "", end: "" }); // the page fills in the career the API reports
    expect(none.issue).toBeNull();

    const fromOnly = read("player=cabremi01&from=2015");
    expect(fromOnly.query.explicitRange).toEqual({ start: true, end: false });
    expect(fromOnly.rawRange).toEqual({ start: "2015", end: "" });

    const both = read("player=cabremi01&from=2015&to=2020");
    expect(both.query.explicitRange).toEqual({ start: true, end: true });

    // Choosing "One player" before a player: the same career rule.
    expect(read("scope=player").rawRange).toEqual({ start: "", end: "" });
  });

  it("all players keep the default range", () => {
    expect(read("").rawRange).toEqual({ start: "2010", end: "2025" });
    expect(read("from=2015").rawRange).toEqual({ start: "2015", end: "2025" });
    expect(read("from=2015").query.yearRange).toEqual({ start: 2015, end: 2025 });
  });

  it("one player: a bad bound is still caught (outside the data), but a missing one is not an error", () => {
    expect(read("player=cabremi01&from=1700").issue?.kind).toBe("range");
    expect(read("player=cabremi01&from=2020&to=2010").issue?.kind).toBe("range");
    expect(read("player=cabremi01&to=2008").issue).toBeNull();
  });

  it("reads minimums, ignoring stats the catalog doesn't list and negative values", () => {
    expect(read("minab=300&mins=HR:30,OPS:0.8").query.minimums).toEqual({ ab: 300, stats: { HR: 30, OPS: 0.8 } });
    expect(read("minab=0").query.minimums).toEqual({ ab: 0, stats: {} }); // 0 = no minimum, not "unset"
    expect(read("minab=-5&mins=WAR:3,HR:-1,RBI:").query.minimums).toEqual(NO_MINIMUMS);
    expect(read("minab=abc").query.minimums?.ab).toBeNull();
  });

  it("reads several franchises", () => {
    const state = read("team=Boston+Red+Sox,New+York+Yankees,American+League");
    expect(state.query.filters?.teams).toEqual(["Boston Red Sox", "New York Yankees", "American League"]);
  });

  it("links carry only the bounds the user chose, plus filters and minimums", () => {
    const player = read("player=cabremi01&metric=OPS").query;
    // The API reports the career back; a link to every player's seasons must not carry it.
    expect(historicalHref({ ...player, yearRange: { start: 2003, end: 2023 }, playerId: null }, CATALOG)).toBe("/players/historical?metric=OPS");
    expect(historicalHref({ ...read("from=2015&to=2020").query, playerId: "judgeaa01" }, CATALOG)).toBe("/players/historical?from=2015&to=2020&player=judgeaa01");
    expect(historicalHref({ ...read("minab=300&mins=HR:30&team=Boston+Red+Sox").query }, CATALOG)).toBe(
      "/players/historical?team=Boston+Red+Sox&minab=300&mins=HR%3A30",
    );
    // A query without explicit-range information (e.g. from Leaderboards) uses the default comparison.
    expect(historicalHref({ yearRange: { start: 2020, end: 2025 }, metric: "HR" }, CATALOG)).toBe("/players/historical?from=2020");
  });

  it("knows when a player is still to be chosen", () => {
    const state = read("scope=player");
    expect(state.scope).toBe("player");
    expect(state.query.playerId).toBeNull();
  });

  it("flags unknown metrics and impossible seasons instead of guessing", () => {
    expect(read("metric=WAR").issue).toEqual({ kind: "metric", value: "WAR" });
    expect(read("from=2025&to=2010").issue).toEqual({ kind: "range", from: "2025", to: "2010" });
    expect(read("from=1700").issue?.kind).toBe("range");
    expect(read("from=abc").rawRange.start).toBe("abc");
  });

  it("builds links that omit defaults", () => {
    expect(historicalHref({ yearRange: { start: 2010, end: 2025 }, metric: "HR", order: "desc", playerId: null }, CATALOG)).toBe("/players/historical");
    expect(historicalHref({ yearRange: { start: 2010, end: 2025 }, metric: "OPS", order: "desc", playerId: "judgeaa01" }, CATALOG)).toBe(
      "/players/historical?metric=OPS&player=judgeaa01",
    );
  });
});
