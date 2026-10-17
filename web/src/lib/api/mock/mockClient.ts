/**
 * Fixture adapter: answers the BaseballClient interface from canned sample data.
 *
 * It never ranks, filters by stat, qualifies or derives numbers. It validates the request the
 * way the API is expected to (unknown metric, bad range), then looks up a canned answer; any
 * question without one rejects with `unsupported`, so the UI never shows numbers for a
 * question that wasn't actually answered.
 *
 * Development switch: add `?mock=loading | slow | unavailable | empty` to any page URL to force
 * that state.
 */
import type { BaseballClient, RequestOptions } from "../client";
import { BaseballApiError } from "../errors";
import type {
  HistoricalExplorerQuery,
  HistoricalExplorerResult,
  LeaderboardQuery,
  LeaderboardResult,
  PlayerSummary,
  YearRange,
} from "../types";
import { CATALOG } from "./fixtures/catalog";
import { findHistoricalScenario, HISTORICAL_SCENARIOS } from "./fixtures/historical";
import { findLeaderboardScenario, LEADERBOARD_SCENARIOS } from "./fixtures/leaderboards";
import { PLAYERS } from "./fixtures/players";

export type MockScenario = "normal" | "loading" | "slow" | "unavailable" | "empty";

export interface MockClientOptions {
  /** Simulated network latency in ms. */
  latencyMs?: number;
  /** Fixed scenario; by default read from the page URL's `?mock=` parameter. */
  scenario?: MockScenario | (() => MockScenario);
}

const SCENARIOS: MockScenario[] = ["normal", "loading", "slow", "unavailable", "empty"];

function scenarioFromUrl(): MockScenario {
  if (typeof window === "undefined") return "normal";
  const value = new URLSearchParams(window.location.search).get("mock");
  return SCENARIOS.includes(value as MockScenario) ? (value as MockScenario) : "normal";
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const timer = Number.isFinite(ms) ? setTimeout(resolve, ms) : undefined;
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

function checkRange(range: YearRange): void {
  const { start, end } = CATALOG.years;
  const valid = [range.start, range.end].every((y) => Number.isInteger(y) && y >= start && y <= end);
  if (!valid || range.start > range.end) {
    throw new BaseballApiError("invalid_request", `Choose seasons between ${start} and ${end}, with the first year no later than the last.`);
  }
}

function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function createMockClient(options: MockClientOptions = {}): BaseballClient {
  const latencyMs = options.latencyMs ?? 350;
  const scenarioOf = (): MockScenario =>
    typeof options.scenario === "function" ? options.scenario() : options.scenario ?? scenarioFromUrl();

  /** Applies latency and the loading/slow/unavailable switches. Returns the active scenario. */
  async function respond(request?: RequestOptions): Promise<MockScenario> {
    const scenario = scenarioOf();
    const delay = scenario === "loading" ? Number.POSITIVE_INFINITY : scenario === "slow" ? 2500 : latencyMs;
    await wait(delay, request?.signal);
    if (scenario === "unavailable") {
      throw new BaseballApiError("unavailable", "The baseball data service didn't respond.");
    }
    return scenario;
  }

  return {
    source: "mock",

    async getCatalog(request) {
      await wait(Math.min(latencyMs, 100), request?.signal);
      return CATALOG;
    },

    async searchPlayers(text, request) {
      await wait(Math.min(latencyMs, 150), request?.signal);
      const needle = fold(text.trim());
      if (!needle) return [];
      return PLAYERS.filter((p) => fold(p.name).includes(needle)).slice(0, request?.limit ?? 8);
    },

    async getPlayer(id, request) {
      await wait(Math.min(latencyMs, 100), request?.signal);
      return PLAYERS.find((p) => p.id === id) ?? null;
    },

    async getHistoricalExplorer(query: HistoricalExplorerQuery, request): Promise<HistoricalExplorerResult> {
      const scenario = await respond(request);
      if (!CATALOG.historical.metrics.includes(query.metric)) {
        throw new BaseballApiError("invalid_request", `"${query.metric}" isn't a stat this page can rank.`);
      }
      checkRange(query.yearRange);
      if (query.playerId !== null && !PLAYERS.some((p: PlayerSummary) => p.id === query.playerId)) {
        throw new BaseballApiError("invalid_request", "That player isn't in the data.");
      }
      const canned = findHistoricalScenario(query.yearRange, query.playerId, query.metric, query.order);
      if (scenario === "empty") {
        const base = canned ?? Object.values(HISTORICAL_SCENARIOS)[0]!;
        return { ...base, query, answer: null, topSeasonId: null, seasons: [], totalCount: 0, chart: null };
      }
      if (!canned) {
        throw new BaseballApiError(
          "unsupported",
          "The sample data covers 2010–2025 and 2020–2025, highest first, ranked by home runs or OPS (one-player views: Aaron Judge or Vladimir Guerrero Jr., 2010–2025).",
        );
      }
      return canned;
    },

    async getLeaderboard(query: LeaderboardQuery, request): Promise<LeaderboardResult> {
      const scenario = await respond(request);
      if (!CATALOG.leaderboards.metrics.includes(query.metric)) {
        throw new BaseballApiError("invalid_request", `"${query.metric}" isn't a stat this page can rank.`);
      }
      checkRange(query.yearRange);
      const canned = findLeaderboardScenario(query.yearRange, query.metric);
      if (scenario === "empty") {
        const base = canned ?? LEADERBOARD_SCENARIOS.OPS!;
        return { ...base, query, answer: null, entries: [], totalRanked: 0 };
      }
      if (!canned) {
        throw new BaseballApiError(
          "unsupported",
          "The sample data covers 2020–2025 by weighted score, home runs or OPS, and 2010–2025 by home runs.",
        );
      }
      return canned;
    },
  };
}
