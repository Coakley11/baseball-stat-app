/** SAMPLE DATA: mirrors the Streamlit pages' options and defaults (streamlit_app.py). */
import type { Catalog, MetricDefinition, TableColumn } from "../../types";

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
  { key: "yearID", label: "Year", name: "season", format: "year" },
];

const STAT_KEYS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"];

/** The real catalog's table columns (label, row field path, stat), as served by the API. */
const statColumns = (keys: string[]): TableColumn[] => keys.map((k) => ({ label: k, field: `stats.${k}`, metric: k }));

const HISTORICAL_COLUMNS: TableColumn[] = [
  { label: "Year", field: "year", metric: "yearID" },
  { label: "Player", field: "player.name", metric: null },
  { label: "Bats", field: "bats", metric: null },
  { label: "Primary Position", field: "position", metric: null },
  { label: "Team", field: "team.season_name", metric: null },
  ...statColumns(STAT_KEYS),
];

const LEADERBOARD_COLUMNS: TableColumn[] = [
  { label: "Player", field: "player.name", metric: null },
  { label: "Bats", field: "bats", metric: null },
  ...statColumns(STAT_KEYS),
  { label: "Score", field: "score", metric: "score" },
];

export const CATALOG: Catalog = {
  years: { start: 1871, end: 2025 },
  metrics: METRICS,
  historical: {
    yearRange: { start: 2010, end: 2025 },
    metric: "HR",
    order: "desc",
    metrics: STAT_KEYS,
    columns: HISTORICAL_COLUMNS,
    filters: {
      bats: [{ value: "B", label: "Both" }, { value: "L", label: "Left" }, { value: "R", label: "Right" }],
      positionSources: [{ value: "season", label: "Season Primary Position" }, { value: "career", label: "Career Primary Position" }],
      positionsBySource: { season: ["1B", "2B", "3B", "C", "CF", "LF", "RF", "SS"], career: ["1B", "2B", "3B", "C", "CF", "LF", "RF", "SS"] },
      teams: [
        { value: "All Teams", label: "All Teams" },
        { value: "American League", label: "American League" },
        { value: "National League", label: "National League" },
        { value: "Boston Red Sox", label: "Boston Red Sox" },
        { value: "Chicago Cubs", label: "Chicago Cubs" },
        { value: "New York Yankees", label: "New York Yankees" },
      ],
      minimumColumns: ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"],
    },
  },
  leaderboards: {
    yearRange: { start: 2020, end: 2025 },
    metric: "score",
    metrics: ["score", ...STAT_KEYS],
    columns: LEADERBOARD_COLUMNS,
    weights: { HR: 1, RBI: 1, SB: 1 },
    weightStats: STAT_KEYS,
    weightBounds: [0, 10],
    weightStep: 0.5,
    limit: 25,
    limitBounds: [5, 100],
    minimumColumns: ["R", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"],
  },
};

export function metricDefinition(key: string): MetricDefinition {
  const found = METRICS.find((m) => m.key === key);
  if (!found) throw new Error(`Fixture metric missing: ${key}`);
  return found;
}
