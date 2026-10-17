/** SAMPLE DATA: mirrors the Streamlit pages' options and defaults (streamlit_app.py). */
import type { Catalog, MetricDefinition } from "../../types";

const METRICS: MetricDefinition[] = [
  { key: "score", label: "Score", name: "weighted score", format: "score" },
  { key: "R", label: "R", name: "runs", format: "count" },
  { key: "AB", label: "AB", name: "at-bats", format: "count" },
  { key: "H", label: "H", name: "hits", format: "count" },
  { key: "2B", label: "2B", name: "doubles", format: "count" },
  { key: "3B", label: "3B", name: "triples", format: "count" },
  { key: "HR", label: "HR", name: "home runs", format: "count" },
  { key: "RBI", label: "RBI", name: "RBIs", format: "count" },
  { key: "SB", label: "SB", name: "stolen bases", format: "count" },
  { key: "BB", label: "BB", name: "walks", format: "count" },
  { key: "BA", label: "AVG", name: "batting average", format: "rate" },
  { key: "OBP", label: "OBP", name: "on-base percentage", format: "rate" },
  { key: "SLG", label: "SLG", name: "slugging percentage", format: "rate" },
  { key: "OPS", label: "OPS", name: "OPS", format: "rate" },
];

const STAT_KEYS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"];

export const CATALOG: Catalog = {
  years: { start: 1871, end: 2025 },
  metrics: METRICS,
  historical: { yearRange: { start: 2010, end: 2025 }, metric: "HR", order: "desc", metrics: STAT_KEYS },
  leaderboards: { yearRange: { start: 2020, end: 2025 }, metric: "score", metrics: ["score", ...STAT_KEYS] },
};

export function metricDefinition(key: string): MetricDefinition {
  const found = METRICS.find((m) => m.key === key);
  if (!found) throw new Error(`Fixture metric missing: ${key}`);
  return found;
}
