import { describe, expect, it } from "vitest";

import { CATALOG } from "@/lib/api/mock/fixtures/catalog";

import { historicalHref, readHistoricalParams } from "./params";

const read = (search: string) => readHistoricalParams(new URLSearchParams(search), CATALOG);

describe("Historical Explorer URL", () => {
  it("uses the catalog defaults for a bare URL", () => {
    const state = read("");
    expect(state.query).toEqual({ yearRange: { start: 2010, end: 2025 }, metric: "HR", order: "desc", playerId: null });
    expect(state.scope).toBe("all");
    expect(state.issue).toBeNull();
  });

  it("reads a full question", () => {
    const state = read("from=2015&to=2020&metric=OPS&order=asc&player=judgeaa01");
    expect(state.query).toEqual({ yearRange: { start: 2015, end: 2020 }, metric: "OPS", order: "asc", playerId: "judgeaa01" });
    expect(state.scope).toBe("player");
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
