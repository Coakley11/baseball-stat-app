/**
 * The BaseballClient backed by the Python API, through the same-origin proxy (/api/baseball,
 * see lib/api/proxy.ts). Requests go out with explicit parameters, and each response is mapped
 * by ./mapping (renames only).
 */
import type { BaseballClient, RequestOptions } from "../client";
import { BaseballApiError } from "../errors";
import type { components } from "../generated/baseball-api";
import type { Catalog, HistoricalExplorerQuery, LeaderboardQuery } from "../types";
import {
  HISTORICAL_DEFAULTS,
  HISTORICAL_METRICS,
  interimMetric,
  LEADERBOARD_DEFAULTS,
  LEADERBOARD_METRICS,
} from "./interimCatalog";
import { toHistoricalResult, toLeaderboardResult, toPlayerSummary } from "./mapping";

type Schemas = components["schemas"];

/** Rows per ranking request (the API allows 1–200; Streamlit's Top N defaults to 25). */
export const PAGE_SIZE = 25;
const WARMUP_POLL_MS = 1500;
const WARMUP_LIMIT_MS = 45_000;

export interface HttpClientOptions {
  /** Where `<path>` requests go: "/api/baseball" in the browser, "<origin>/api/v1" in live tests. */
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

/** API error envelope or transport failure → the frontend's error kinds (by status, then code). */
async function toError(res: Response): Promise<BaseballApiError> {
  let message = "The baseball data service returned an error.";
  try {
    const body = (await res.json()) as Schemas["ErrorResponse"];
    if (body?.error?.message) message = body.error.message;
  } catch {
    // Non-JSON error body: keep the generic message.
  }
  if (res.status === 502 || res.status === 503 || res.status === 504) return new BaseballApiError("unavailable", message);
  if (res.status === 400 || res.status === 404 || res.status === 409 || res.status === 422) {
    return new BaseballApiError("invalid_request", message);
  }
  return new BaseballApiError("unknown", message);
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

export function createHttpClient({ baseUrl = "/api/baseball", fetchImpl }: HttpClientOptions = {}): BaseballClient {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const root = baseUrl.replace(/\/+$/, "");

  async function get<T>(path: string, params: Record<string, string | number> | null, request?: RequestOptions): Promise<T> {
    const query = params ? `?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()}` : "";
    let res: Response;
    try {
      res = await doFetch(`${root}/${path}${query}`, { headers: { accept: "application/json" }, signal: request?.signal });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new BaseballApiError("unavailable", "The baseball data service didn't respond.");
    }
    if (!res.ok) throw await toError(res);
    return (await res.json()) as T;
  }

  return {
    source: "api",
    capabilities: { playerSeasonRanking: false },

    async getCatalog(request) {
      // Year bounds are live; the rest is the documented interim catalog (until handoff R1).
      // After a cold start the API loads its data for ~18 s, so wait for /health to say so.
      const started = Date.now();
      let health = await get<Schemas["HealthInfo"]>("health", null, request);
      while (!health.data_loaded || !health.seasons) {
        if (Date.now() - started > WARMUP_LIMIT_MS) {
          throw new BaseballApiError("unavailable", "The baseball data service is still starting up.");
        }
        await wait(WARMUP_POLL_MS, request?.signal);
        health = await get<Schemas["HealthInfo"]>("health", null, request);
      }
      const [first, last] = health.seasons as [number, number];
      const keys = [...new Set([...HISTORICAL_METRICS, ...LEADERBOARD_METRICS])];
      const catalog: Catalog = {
        years: { start: first, end: last },
        metrics: keys.map(interimMetric),
        historical: {
          yearRange: { start: Math.max(first, HISTORICAL_DEFAULTS.start), end: last },
          metric: HISTORICAL_DEFAULTS.metric,
          order: HISTORICAL_DEFAULTS.order,
          metrics: HISTORICAL_METRICS,
        },
        leaderboards: {
          yearRange: { start: Math.max(first, LEADERBOARD_DEFAULTS.start), end: last },
          metric: LEADERBOARD_DEFAULTS.metric,
          metrics: LEADERBOARD_METRICS,
        },
      };
      return catalog;
    },

    async searchPlayers(text, request) {
      const q = text.trim();
      if (q.length < 2) return [];
      const res = await get<Schemas["PlayerSearchResult"]>("players/search", { q, limit: request?.limit ?? 8 }, request);
      return res.results.map(toPlayerSummary);
    },

    async getPlayer(id, request) {
      try {
        const res = await get<Schemas["PlayerSeasonsResult"]>(`players/${encodeURIComponent(id)}/seasons`, null, request);
        return toPlayerSummary(res.player);
      } catch (error) {
        if (error instanceof BaseballApiError && error.kind === "invalid_request") return null;
        throw error;
      }
    },

    async getHistoricalExplorer(query: HistoricalExplorerQuery, request) {
      if (query.playerId !== null) {
        throw new BaseballApiError("unsupported", "Rankings for one player's seasons aren't available from the API yet.");
      }
      const res = await get<Schemas["SeasonLeadersResult"]>(
        "seasons",
        { start: query.yearRange.start, end: query.yearRange.end, metric: query.metric, order: query.order, limit: PAGE_SIZE },
        request,
      );
      return toHistoricalResult(res);
    },

    async getLeaderboard(query: LeaderboardQuery, request) {
      const res = await get<Schemas["LeaderboardResult"]>(
        "leaderboards",
        { start: query.yearRange.start, end: query.yearRange.end, metric: query.metric, limit: PAGE_SIZE },
        request,
      );
      return toLeaderboardResult(res);
    },
  };
}
