/**
 * The BaseballClient backed by the Python API, through the same-origin proxy (/api/baseball,
 * see lib/api/proxy.ts). Requests go out with explicit parameters, each response is mapped by
 * ./mapping (renames and path lookups only), and errors become BaseballApiError. This is the one
 * place for response normalization, error mapping and (later) authentication.
 */
import type { BaseballClient, RequestOptions } from "../client";
import { BaseballApiError } from "../errors";
import type { components } from "../generated/baseball-api";
import { TABLE_PAGE_SIZE, type Catalog, type HistoricalExplorerQuery, type LeaderboardQuery } from "../types";
import { toCatalog, toHistoricalResult, toLeaderboardResult, toPlayerSummary } from "./mapping";

type Schemas = components["schemas"];
type Params = Record<string, string | number | boolean>;

/** While the API loads its data after a cold start (~18 s) it answers 503 + Retry-After. */
const WARMUP_LIMIT_MS = 60_000;
const DEFAULT_RETRY_AFTER_S = 2;

export interface HttpClientOptions {
  /** Where `<path>` requests go: "/api/baseball" in the browser, "<origin>/api/v1" in live tests. */
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

async function toError(res: Response): Promise<BaseballApiError> {
  let message = "The baseball data service returned an error.";
  try {
    const body = (await res.json()) as Schemas["ErrorResponse"];
    if (body?.error?.message) message = body.error.message;
  } catch {
    // Non-JSON error body: keep the generic message.
  }
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    const retryAfter = Number(res.headers.get("retry-after"));
    return new BaseballApiError("unavailable", message, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null);
  }
  if (res.status === 400 || res.status === 404 || res.status === 409 || res.status === 422) {
    return new BaseballApiError("invalid_request", message);
  }
  return new BaseballApiError("unknown", message);
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

function queryString(params: Params): string {
  return new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
}

/** The /seasons parameters for a Historical Explorer question (without paging or format). */
function historicalParams(query: HistoricalExplorerQuery): Params {
  const params: Params = {
    start: query.yearRange.start,
    end: query.yearRange.end,
    metric: query.metric,
    order: query.order,
  };
  const f = query.filters;
  if (f) {
    if (f.bats.length) params.bats = f.bats.join(",");
    if (f.positions.length) params.positions = f.positions.join(",");
    if (f.positions.length || f.positionSource !== "season") params.position_source = f.positionSource;
    if (f.teams.length) params.teams = f.teams.join(",");
    if (f.combine) params.combine = true;
  }
  if (query.playerId !== null) params.player_id = query.playerId;
  return params;
}

function leaderboardParams(query: LeaderboardQuery): Params {
  const params: Params = { start: query.yearRange.start, end: query.yearRange.end, metric: query.metric };
  if (query.weights) {
    params.weights = Object.entries(query.weights)
      .map(([stat, weight]) => `${stat}:${weight}`)
      .join(",");
  }
  return params;
}

export function createHttpClient({ baseUrl = "/api/baseball", fetchImpl }: HttpClientOptions = {}): BaseballClient {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const root = baseUrl.replace(/\/+$/, "");

  async function get<T>(path: string, params: Params | null, request?: RequestOptions): Promise<T> {
    const query = params ? `?${queryString(params)}` : "";
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

  // The catalog is fetched once per client. While the API is still loading its data it answers
  // 503 + Retry-After; wait as told (up to a minute) so the page just shows its loading state.
  let catalogPromise: Promise<Catalog> | null = null;
  function loadCatalog(): Promise<Catalog> {
    if (!catalogPromise) {
      const started = Date.now();
      const attempt = async (): Promise<Catalog> => {
        for (;;) {
          try {
            return toCatalog(await get<Schemas["Catalog"]>("catalog", null));
          } catch (error) {
            const warming = error instanceof BaseballApiError && error.kind === "unavailable" && error.retryAfterSeconds !== null;
            if (!warming || Date.now() - started > WARMUP_LIMIT_MS) throw error;
            await wait((error.retryAfterSeconds ?? DEFAULT_RETRY_AFTER_S) * 1000);
          }
        }
      };
      catalogPromise = attempt().catch((error: unknown) => {
        catalogPromise = null; // a failure isn't remembered; the next call tries again
        throw error;
      });
    }
    return catalogPromise;
  }

  /** Awaits a shared promise, but lets this caller's abort win. */
  function withAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
    if (!signal) return promise;
    return Promise.race([
      promise,
      new Promise<never>((_, reject) => {
        if (signal.aborted) reject(new DOMException("Aborted", "AbortError"));
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      }),
    ]);
  }

  return {
    source: "api",
    capabilities: { playerSeasonRanking: true, csvExport: true, paging: true },

    getCatalog: (request) => withAbort(loadCatalog(), request?.signal),

    async searchPlayers(text, request) {
      const q = text.trim();
      if (q.length < 2) return [];
      const res = await get<Schemas["PlayerSearchResult"]>("players/search", { q, limit: request?.limit ?? 8 }, request);
      return res.results.map(toPlayerSummary);
    },

    async getPlayer(id, request) {
      try {
        return toPlayerSummary(await get<Schemas["PlayerSummary"]>(`players/${encodeURIComponent(id)}`, null, request));
      } catch (error) {
        if (error instanceof BaseballApiError && error.kind === "invalid_request") return null;
        throw error;
      }
    },

    async getHistoricalExplorer(query, request) {
      const catalog = await withAbort(loadCatalog(), request?.signal);
      const params: Params = { ...historicalParams(query), limit: TABLE_PAGE_SIZE };
      if (query.offset) params.offset = query.offset;
      // One player's seasons include those below the minimum, marked and unranked.
      if (query.playerId !== null) params.include_below_minimum = true;
      const res = await get<Schemas["SeasonLeadersResult"]>("seasons", params, request);
      return toHistoricalResult(res, query, catalog.historical.columns);
    },

    async getLeaderboard(query, request) {
      const catalog = await withAbort(loadCatalog(), request?.signal);
      const limit = query.limit ?? catalog.leaderboards.limit;
      const res = await get<Schemas["LeaderboardResult"]>("leaderboards", { ...leaderboardParams(query), limit }, request);
      return toLeaderboardResult(res, { ...query, limit }, catalog.leaderboards.columns);
    },

    // The API builds the CSV (and names the file); these are just links to it through the proxy.
    historicalExportUrl: (query) => `${root}/seasons?${queryString({ ...historicalParams(query), format: "csv" })}`,
    leaderboardExportUrl: (query) =>
      `${root}/leaderboards?${queryString({ ...leaderboardParams(query), ...(query.limit ? { limit: query.limit } : {}), format: "csv" })}`,
  };
}
