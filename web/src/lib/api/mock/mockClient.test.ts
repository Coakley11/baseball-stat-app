import { describe, expect, it } from "vitest";

import { BaseballApiError } from "../errors";
import { createMockClient } from "./mockClient";

const client = createMockClient({ latencyMs: 0, scenario: "normal" });
const HIST_DEFAULT = { yearRange: { start: 2010, end: 2025 }, metric: "HR", order: "desc" as const, playerId: null };

async function rejection(promise: Promise<unknown>): Promise<BaseballApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof BaseballApiError) return error;
    throw error;
  }
  throw new Error("expected a rejection");
}

describe("fixture adapter", () => {
  it("serves the canned default Historical Explorer answer", async () => {
    const result = await client.getHistoricalExplorer(HIST_DEFAULT);
    expect(result.answer?.headline).toBe("Aaron Judge, 2022: 62 home runs");
    expect(result.seasons[0]?.id).toBe(result.topSeasonId);
    expect(result.chart?.kind).toBe("ranking");
  });

  it("keeps every chart and top-season id resolvable", async () => {
    const questions = [
      { ...HIST_DEFAULT },
      { ...HIST_DEFAULT, metric: "OPS" },
      { ...HIST_DEFAULT, playerId: "judgeaa01" },
      { ...HIST_DEFAULT, playerId: "judgeaa01", metric: "OPS" },
      { ...HIST_DEFAULT, playerId: "guerrvl02" },
      { ...HIST_DEFAULT, playerId: "guerrvl02", metric: "OPS" },
    ];
    for (const q of questions) {
      const result = await client.getHistoricalExplorer(q);
      const ids = new Set(result.seasons.map((s) => s.id));
      expect(ids.has(result.topSeasonId!)).toBe(true);
      for (const id of result.chart!.seasonIds) expect(ids.has(id)).toBe(true);
      expect(result.query).toEqual(q);
    }
  });

  it("rejects questions the sample data doesn't cover instead of showing other numbers", async () => {
    const error = await rejection(client.getHistoricalExplorer({ ...HIST_DEFAULT, yearRange: { start: 1990, end: 2000 } }));
    expect(error.kind).toBe("unsupported");
    expect((await rejection(client.getLeaderboard({ yearRange: { start: 2020, end: 2025 }, metric: "SB" }))).kind).toBe("unsupported");
  });

  it("validates requests like the API", async () => {
    expect((await rejection(client.getHistoricalExplorer({ ...HIST_DEFAULT, metric: "WAR" }))).kind).toBe("invalid_request");
    expect((await rejection(client.getLeaderboard({ yearRange: { start: 2025, end: 2020 }, metric: "HR" }))).kind).toBe("invalid_request");
    expect((await rejection(client.getHistoricalExplorer({ ...HIST_DEFAULT, playerId: "nobody01" }))).kind).toBe("invalid_request");
  });

  it("serves leaderboards with authoritative qualification text", async () => {
    const ops = await client.getLeaderboard({ yearRange: { start: 2020, end: 2025 }, metric: "OPS" });
    expect(ops.qualification.summary).toBe("Qualified hitters · at least 2,349 AB over 2020–2025");
    expect(ops.entries.map((e) => e.rank)).toEqual(ops.entries.map((_, i) => i + 1));
    expect(ops.entries.some((e) => e.player.name === "Ronald Acuña Jr.")).toBe(false);
  });

  it("covers the other page's default range so cross-page links land on an answer", async () => {
    const seasons = await client.getHistoricalExplorer({ ...HIST_DEFAULT, yearRange: { start: 2020, end: 2025 } });
    expect(seasons.answer?.detail).toContain("(2020–2025)");
    const leaders = await client.getLeaderboard({ yearRange: { start: 2010, end: 2025 }, metric: "HR" });
    expect(leaders.columns).toEqual(["HR"]);
    expect(leaders.entries[0]?.player.name).toBe("Giancarlo Stanton");
  });

  it("searches player names ignoring case and accents", async () => {
    expect((await client.searchPlayers("jose")).map((p) => p.name)).toEqual(["José Bautista", "José Ramírez"]);
    expect((await client.searchPlayers("GUERRERO")).map((p) => p.name)).toEqual(["Vladimir Guerrero Jr."]);
    expect(await client.searchPlayers("  ")).toEqual([]);
  });

  it("simulates outages and empty answers on request", async () => {
    const down = createMockClient({ latencyMs: 0, scenario: "unavailable" });
    expect((await rejection(down.getLeaderboard({ yearRange: { start: 2020, end: 2025 }, metric: "HR" }))).kind).toBe("unavailable");
    const empty = createMockClient({ latencyMs: 0, scenario: "empty" });
    const result = await empty.getLeaderboard({ yearRange: { start: 2020, end: 2025 }, metric: "OPS" });
    expect(result.entries).toEqual([]);
    expect(result.answer).toBeNull();
  });

  it("stops when the request is aborted", async () => {
    const slow = createMockClient({ latencyMs: 10_000, scenario: "normal" });
    const controller = new AbortController();
    const pending = slow.getHistoricalExplorer(HIST_DEFAULT, { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toThrow(/Aborted/);
  });
});
