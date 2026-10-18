/**
 * Leaderboards question ⇄ URL. Parameters: from, to, metric, top (how many players),
 * w (custom score weights, "HR:1,RBI:2"), minab and mins (minimums the user sets). Defaults come from the catalog.
 */
import type { Catalog, LeaderboardQuery } from "@/lib/api";

import { readMetric, readMinimums, readYearRange, type ParamIssue, type ReadableParams } from "../shared/params";

export const LEADERBOARDS_PATH = "/players/leaderboards";

export interface LeaderboardUrlState {
  query: LeaderboardQuery;
  rawRange: { start: string; end: string };
  issue: ParamIssue | null;
}

/** "HR:1,RBI:2" → { HR: 1, RBI: 2 }, keeping only stats the catalog allows and values in bounds. */
export function parseWeights(text: string | null, catalog: Catalog): Record<string, number> | undefined {
  if (!text) return undefined;
  const { weightStats, weightBounds } = catalog.leaderboards;
  const out: Record<string, number> = {};
  for (const part of text.split(",")) {
    const [stat, raw] = part.split(":");
    const value = Number(raw);
    if (stat && weightStats.includes(stat) && Number.isFinite(value) && value >= weightBounds[0] && value <= weightBounds[1] && value > 0) {
      out[stat] = value;
    }
  }
  return Object.keys(out).length ? out : undefined;
}

export function formatWeights(weights: Record<string, number>): string {
  return Object.entries(weights)
    .filter(([, w]) => w > 0)
    .map(([stat, w]) => `${stat}:${w}`)
    .join(",");
}

export function sameWeights(a: Record<string, number>, b: Record<string, number>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((k) => (a[k] ?? 0) === (b[k] ?? 0));
}

export function readLeaderboardParams(params: ReadableParams, catalog: Catalog): LeaderboardUrlState {
  const defaults = catalog.leaderboards;
  const range = readYearRange(params, defaults.yearRange, catalog.years);
  const metric = readMetric(params, defaults.metrics, defaults.metric);
  const top = Math.floor(Number(params.get("top")));
  const limit = Number.isFinite(top) && top >= defaults.limitBounds[0] && top <= defaults.limitBounds[1] ? top : defaults.limit;
  return {
    query: {
      yearRange: range.range,
      metric: metric.metric,
      limit,
      weights: parseWeights(params.get("w"), catalog),
      minimums: readMinimums(params, defaults.minimumColumns),
    },
    rawRange: { start: params.get("from") ?? String(defaults.yearRange.start), end: params.get("to") ?? String(defaults.yearRange.end) },
    issue: range.issue ?? metric.issue,
  };
}
