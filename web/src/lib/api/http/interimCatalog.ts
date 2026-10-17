/**
 * INTERIM until the API serves `GET /catalog` (handoff R1).
 *
 * The question controls need their options before the first answer arrives. Each value here
 * mirrors baseball_api @ a9a80f7 and the Streamlit "Sort by" controls. None is a calculation,
 * and every one is checked against the live API by `npm run test:live`
 * (src/lib/api/http/api.live.test.ts), so a Python-side change fails a test instead of drifting.
 * Year bounds are not here: they come from /health at runtime.
 */
import type { MetricDefinition, StatFormat } from "../types";

/** Historical Explorer "Sort by" (streamlit_app.sort_options_hist). The API also accepts yearID; not offered, as in Streamlit. */
export const HISTORICAL_METRICS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"];
/** Leaderboards "Sort by" (services.LEADERBOARD_METRICS). */
export const LEADERBOARD_METRICS = ["score", ...HISTORICAL_METRICS];

/** What the API sends when no parameters are given (services.season_leaders / leaderboard). */
export const HISTORICAL_DEFAULTS = { start: 2010, metric: "HR", order: "desc" as const };
export const LEADERBOARD_DEFAULTS = { start: 2020, metric: "score" };

/** MetricInfo.label where it differs from the key (services._LABELS). */
const LABELS: Record<string, string> = { BA: "AVG", score: "Score" };
/** MetricInfo.kind for each stat: the four rate stats, the weighted score, otherwise counts. */
const RATE = new Set(["BA", "OBP", "SLG", "OPS"]);

export function interimMetric(key: string): MetricDefinition {
  const label = LABELS[key] ?? key;
  const format: StatFormat = RATE.has(key) ? "rate" : key === "score" ? "score" : "count";
  // No plain-language name in the API yet (handoff R5): use the API's own label.
  return { key, label, name: label, format };
}
