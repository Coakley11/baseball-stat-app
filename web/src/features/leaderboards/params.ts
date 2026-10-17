/** Leaderboards question ⇄ URL. Parameters: from, to, metric. Defaults come from the catalog. */
import type { Catalog, LeaderboardQuery } from "@/lib/api";

import { readMetric, readYearRange, type ParamIssue, type ReadableParams } from "../shared/params";

export const LEADERBOARDS_PATH = "/players/leaderboards";

export interface LeaderboardUrlState {
  query: LeaderboardQuery;
  rawRange: { start: string; end: string };
  issue: ParamIssue | null;
}

export function readLeaderboardParams(params: ReadableParams, catalog: Catalog): LeaderboardUrlState {
  const defaults = catalog.leaderboards;
  const range = readYearRange(params, defaults.yearRange, catalog.years);
  const metric = readMetric(params, defaults.metrics, defaults.metric);
  return {
    query: { yearRange: range.range, metric: metric.metric },
    rawRange: { start: params.get("from") ?? String(defaults.yearRange.start), end: params.get("to") ?? String(defaults.yearRange.end) },
    issue: range.issue ?? metric.issue,
  };
}
