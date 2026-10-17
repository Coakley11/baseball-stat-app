/**
 * Reading a question from the URL. Input validation only (is this a known metric, are these
 * real seasons?), using the catalog the API publishes; the API still validates every request.
 */
import type { Catalog, MetricDefinition, YearRange } from "@/lib/api";

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
