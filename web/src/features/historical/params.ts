/**
 * Historical Explorer question ⇄ URL. Parameters: from, to, metric, order (asc), player,
 * scope=player (choosing "One player" before picking one). Defaults come from the catalog and
 * are omitted from links.
 */
import type { Catalog, HistoricalExplorerQuery, SortOrder } from "@/lib/api";

import { readMetric, readYearRange, type ParamIssue, type ReadableParams } from "../shared/params";

export const HISTORICAL_PATH = "/players/historical";

export interface HistoricalUrlState {
  query: HistoricalExplorerQuery;
  scope: "all" | "player";
  /** The seasons exactly as written in the URL, for the inputs. */
  rawRange: { start: string; end: string };
  issue: ParamIssue | null;
}

export function readHistoricalParams(params: ReadableParams, catalog: Catalog): HistoricalUrlState {
  const defaults = catalog.historical;
  const range = readYearRange(params, defaults.yearRange, catalog.years);
  const metric = readMetric(params, defaults.metrics, defaults.metric);
  const order: SortOrder = params.get("order") === "asc" ? "asc" : params.get("order") === "desc" ? "desc" : defaults.order;
  const playerId = params.get("player") || null;
  const scope = playerId !== null || params.get("scope") === "player" ? "player" : "all";
  return {
    query: { yearRange: range.range, metric: metric.metric, order, playerId },
    scope,
    rawRange: { start: params.get("from") ?? String(defaults.yearRange.start), end: params.get("to") ?? String(defaults.yearRange.end) },
    issue: range.issue ?? metric.issue,
  };
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
  const text = params.toString();
  return text ? `${HISTORICAL_PATH}?${text}` : HISTORICAL_PATH;
}
