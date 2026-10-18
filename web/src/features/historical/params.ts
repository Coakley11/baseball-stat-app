/**
 * Historical Explorer question ⇄ URL. Parameters: from, to, metric, order (asc), player,
 * scope=player (choosing "One player" before picking one), bats, psrc (career), pos, team,
 * combine (1), page. Defaults come from the catalog and are omitted from links; unknown filter
 * values are ignored (the API validates every request too).
 */
import type { Catalog, HistoricalExplorerQuery, HistoricalFilters, PositionSource, SortOrder } from "@/lib/api";
import { NO_HISTORICAL_FILTERS } from "@/lib/api";

import { readMetric, readYearRange, type ParamIssue, type ReadableParams } from "../shared/params";

export const HISTORICAL_PATH = "/players/historical";

export interface HistoricalUrlState {
  /** The question for the answer (first page). */
  query: HistoricalExplorerQuery;
  scope: "all" | "player";
  /** The seasons exactly as written in the URL, for the inputs. */
  rawRange: { start: string; end: string };
  /** 1-based table page. */
  page: number;
  issue: ParamIssue | null;
}

function listParam(params: ReadableParams, name: string): string[] {
  return (params.get(name) ?? "").split(",").map((v) => v.trim()).filter(Boolean);
}

export function readHistoricalParams(params: ReadableParams, catalog: Catalog): HistoricalUrlState {
  const defaults = catalog.historical;
  const range = readYearRange(params, defaults.yearRange, catalog.years);
  const metric = readMetric(params, defaults.metrics, defaults.metric);
  const order: SortOrder = params.get("order") === "asc" ? "asc" : params.get("order") === "desc" ? "desc" : defaults.order;
  const playerId = params.get("player") || null;
  const scope = playerId !== null || params.get("scope") === "player" ? "player" : "all";

  const positionSource: PositionSource = params.get("psrc") === "career" ? "career" : "season";
  const knownBats = new Set(defaults.filters.bats.map((o) => o.value));
  const knownPositions = new Set(defaults.filters.positionsBySource[positionSource]);
  const knownTeams = new Set(defaults.filters.teams.map((o) => o.value));
  const filters: HistoricalFilters = {
    bats: listParam(params, "bats").filter((v) => knownBats.has(v)),
    positionSource,
    positions: listParam(params, "pos").filter((v) => knownPositions.has(v)),
    teams: listParam(params, "team").filter((v) => knownTeams.has(v) && v !== "All Teams"),
    combine: params.get("combine") === "1",
  };
  const page = Math.max(1, Math.floor(Number(params.get("page"))) || 1);

  return {
    query: { yearRange: range.range, metric: metric.metric, order, playerId, filters },
    scope,
    rawRange: { start: params.get("from") ?? String(defaults.yearRange.start), end: params.get("to") ?? String(defaults.yearRange.end) },
    page,
    issue: range.issue ?? metric.issue,
  };
}

/** The URL parameters that express a set of filters (the inverse of what readHistoricalParams reads). */
export function filterParams(filters: HistoricalFilters): Record<string, string | null> {
  return {
    bats: filters.bats.length ? filters.bats.join(",") : null,
    psrc: filters.positionSource === "career" ? "career" : null,
    pos: filters.positions.length ? filters.positions.join(",") : null,
    team: filters.teams.length ? filters.teams.join(",") : null,
    combine: filters.combine ? "1" : null,
  };
}

export function hasFilters(filters: HistoricalFilters | undefined): boolean {
  return JSON.stringify(filters ?? NO_HISTORICAL_FILTERS) !== JSON.stringify(NO_HISTORICAL_FILTERS);
}

/** A link to a Historical Explorer question, leaving out values equal to the defaults. */
export function historicalHref(query: Partial<HistoricalExplorerQuery>, catalog: Catalog): string {
  const defaults = catalog.historical;
  const params = new URLSearchParams();
  if (query.yearRange && query.yearRange.start !== defaults.yearRange.start) params.set("from", String(query.yearRange.start));
  if (query.yearRange && query.yearRange.end !== defaults.yearRange.end) params.set("to", String(query.yearRange.end));
  if (query.metric && query.metric !== defaults.metric) params.set("metric", query.metric);
  if (query.order && query.order !== defaults.order) params.set("order", query.order);
  if (query.playerId) params.set("player", query.playerId);
  for (const [key, value] of Object.entries(filterParams(query.filters ?? NO_HISTORICAL_FILTERS))) {
    if (value !== null) params.set(key, value);
  }
  const text = params.toString();
  return text ? `${HISTORICAL_PATH}?${text}` : HISTORICAL_PATH;
}
