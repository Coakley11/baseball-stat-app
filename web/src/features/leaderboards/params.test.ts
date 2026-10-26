import { describe, expect, it } from "vitest";

import { CATALOG } from "@/lib/api/mock/fixtures/catalog";

import { formatWeights, parseWeights, readLeaderboardParams, sameWeights } from "./params";

const read = (search: string) => readLeaderboardParams(new URLSearchParams(search), CATALOG);

describe("Leaderboards URL", () => {
  it("uses the catalog defaults for a bare URL", () => {
    const state = read("");
    expect(state.query).toEqual({ yearRange: { start: 2020, end: 2025 }, metric: "score", limit: 25, weights: undefined, minimums: { ab: null, stats: {} } });
    expect(state.issue).toBeNull();
  });

  it("reads Top N within the catalog's bounds, otherwise the default", () => {
    expect(read("top=50").query.limit).toBe(50);
    expect(read("top=3").query.limit).toBe(25); // below the minimum of 5
    expect(read("top=500").query.limit).toBe(25);
    expect(read("top=abc").query.limit).toBe(25);
  });

  it("reads custom weights, keeping only allowed stats and in-bounds positive values", () => {
    expect(parseWeights("HR:2,RBI:1.5", CATALOG)).toEqual({ HR: 2, RBI: 1.5 });
    expect(parseWeights("HR:2,WAR:3,SB:99,BB:-1,R:abc", CATALOG)).toEqual({ HR: 2 });
    expect(parseWeights("WAR:3", CATALOG)).toBeUndefined();
    expect(parseWeights(null, CATALOG)).toBeUndefined();
    expect(read("w=HR:2,RBI:1").query.weights).toEqual({ HR: 2, RBI: 1 });
  });

  it("writes weights back in the same form", () => {
    expect(formatWeights({ HR: 2, RBI: 1, SB: 0 })).toBe("HR:2,RBI:1");
    expect(sameWeights({ HR: 1, RBI: 1, SB: 1 }, { SB: 1, RBI: 1, HR: 1, R: 0 })).toBe(true);
    expect(sameWeights({ HR: 1 }, { HR: 2 })).toBe(false);
  });

  it("reads minimums the user sets", () => {
    expect(read("minab=1000&mins=HR:100").query.minimums).toEqual({ ab: 1000, stats: { HR: 100 } });
    expect(read("minab=0").query.minimums?.ab).toBe(0);
    expect(read("mins=WAR:3").query.minimums).toEqual({ ab: null, stats: {} });
  });

  it("flags an unknown stat and impossible seasons without guessing", () => {
    expect(read("metric=WAR").issue).toEqual({ kind: "metric", value: "WAR" });
    expect(read("from=2025&to=2020").issue?.kind).toBe("range");
  });
});
