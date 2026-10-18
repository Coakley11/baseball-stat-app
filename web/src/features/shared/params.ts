/**
 * Reading a question from the URL. Input validation only (is this a known metric, are these
 * real seasons?), using the catalog the API publishes; the API still validates every request.
 */
import type { Catalog, MetricDefinition, Minimums, YearRange } from "@/lib/api";

export interface ReadableParams {
  get(name: string): string | null;
}

export type ParamIssue = { kind: "metric"; value: string } | { kind: "range"; from: string; to: string };

export function readYearRange(
  params: ReadableParams,
  defaults: YearRange,
  bounds: YearRange,
): { range: YearRange; issue: ParamIssue | null } {
  const fromText = params.get("from");
  const toText = params.get("to");
  const start = fromText === null ? defaults.start : Number(fromText);
  const end = toText === null ? defaults.end : Number(toText);
  const ok = [start, end].every((y) => Number.isInteger(y) && y >= bounds.start && y <= bounds.end) && start <= end;
  if (ok) return { range: { start, end }, issue: null };
  return { range: defaults, issue: { kind: "range", from: fromText ?? String(defaults.start), to: toText ?? String(defaults.end) } };
}

export function readMetric(
  params: ReadableParams,
  allowed: string[],
  fallback: string,
): { metric: string; issue: ParamIssue | null } {
  const value = params.get("metric");
  if (value === null) return { metric: fallback, issue: null };
  if (allowed.includes(value)) return { metric: value, issue: null };
  return { metric: fallback, issue: { kind: "metric", value } };
}

export function metricOf(catalog: Catalog, key: string): MetricDefinition | undefined {
  return catalog.metrics.find((m) => m.key === key);
}

/** "Home runs", "OPS", "Batting average". */
export function metricTitle(metric: MetricDefinition): string {
  return metric.name.charAt(0).toUpperCase() + metric.name.slice(1);
}

/** "Home runs (HR)", "OPS", "Batting average (AVG)". */
export function metricOptionLabel(metric: MetricDefinition): string {
  const name = metricTitle(metric);
  return name.toLowerCase() === metric.label.toLowerCase() ? metric.label : `${name} (${metric.label})`;
}

/**
 * The current question in words for the collapsed phone summary, built only from what the URL
 * and the catalog say: "2010–2025 · Home runs · All players".
 */
export function questionSummary(rawRange: { start: string; end: string }, metric: MetricDefinition | undefined, ...rest: (string | null | undefined)[]): string {
  const range = rawRange.start === rawRange.end ? rawRange.start : `${rawRange.start}–${rawRange.end}`;
  return [range, metric ? metricTitle(metric) : "Choose a stat", ...rest].filter(Boolean).join(" · ");
}

/* ------------------------------------------------------------------ minimums */

/** "HR:20,OPS:0.8" → { HR: 20, OPS: 0.8 }, keeping only stats the catalog allows and values ≥ 0. */
export function parseStatMinimums(text: string | null, allowed: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of (text ?? "").split(",")) {
    const [stat, raw] = part.split(":");
    const value = Number(raw);
    if (stat && allowed.includes(stat) && raw !== undefined && raw !== "" && Number.isFinite(value) && value >= 0) out[stat] = value;
  }
  return out;
}

/** minab (an at-bat count, 0 allowed) and mins ("HR:20,OPS:0.8") → the user's minimums. */
export function readMinimums(params: ReadableParams, allowed: string[]): Minimums {
  const raw = params.get("minab");
  const ab = raw === null || raw.trim() === "" ? null : Number(raw);
  return {
    ab: ab !== null && Number.isFinite(ab) && ab >= 0 ? Math.floor(ab) : null,
    stats: parseStatMinimums(params.get("mins"), allowed),
  };
}

/** The URL parameters that express a set of minimums (the inverse of readMinimums). */
export function minimumUrlParams(minimums: Minimums): Record<string, string | null> {
  const stats = Object.entries(minimums.stats).map(([stat, value]) => `${stat}:${value}`);
  return { minab: minimums.ab === null ? null : String(minimums.ab), mins: stats.length ? stats.join(",") : null };
}

export function hasMinimums(minimums: Minimums | undefined): boolean {
  return minimums !== undefined && (minimums.ab !== null || Object.keys(minimums.stats).length > 0);
}
