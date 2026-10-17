/**
 * Frontend models for the Baseball Explorer read API (WEB-M1 scope).
 *
 * TEMPORARY: these are hand-written to describe the JSON the frontend needs. When the Python
 * API publishes its OpenAPI schema, replace this file with generated types (or re-export them
 * from here) and fix whatever the compiler flags. Pages import from "@/lib/api", never from a
 * fixture, so only the adapter and this file should need to change.
 *
 * Design rules:
 * - Every number is authoritative Python output. The frontend never ranks, qualifies, sums or
 *   derives a statistic; it only formats values for display (see lib/format.ts).
 * - Plain-language answer sentences come from the API (today: u1_answers.py), so wording and
 *   superlative rules ("most" vs "highest") stay in one place.
 * - A missing value is `null`, never 0, so "not recorded" stays distinguishable from zero.
 */

/** A rankable stat key as the API names it ("HR", "OPS", "score"). */
export type MetricKey = string;

/**
 * How a metric's value is displayed. `rate` → ".311" / "1.159", `count` → "1,234",
 * `score` → one decimal at most.
 */
export type StatFormat = "rate" | "count" | "score";

export interface MetricDefinition {
  key: MetricKey;
  /** Short label for tiles, axes and table headers: "HR", "AVG", "Score". */
  label: string;
  /** Plain-language name for sentences and controls: "home runs", "OPS". */
  name: string;
  format: StatFormat;
}

export interface YearRange {
  start: number;
  end: number;
}

export type SortOrder = "desc" | "asc";

export interface PlayerSummary {
  id: string;
  name: string;
  /** "R" | "L" | "B" (switch) or null when unknown. */
  bats: string | null;
  primaryPosition: string | null;
  firstSeason: number | null;
  lastSeason: number | null;
}

/** Stat values keyed by MetricKey; `null` = not recorded / not available. */
export type StatLine = Record<MetricKey, number | null>;

export interface PlayerSeason {
  /** Stable row id (one row per player-season, or per player-season-team in split mode). */
  id: string;
  player: Pick<PlayerSummary, "id" | "name">;
  year: number;
  /** Short team id ("NYY"). */
  team: string | null;
  /** That season's team name ("New York Yankees"), when the source provides it. */
  teamName: string | null;
  position: string | null;
  stats: StatLine;
  /**
   * Whether the season meets the active at-bat minimum. Only meaningful when the qualification
   * applies; rows below it can still appear (e.g. on a single player's timeline) but are never
   * the answer.
   */
  qualified: boolean;
}

/**
 * The sample-size rule a rate-stat ranking is using (rate_stat_qualification.py).
 * `not_applicable` for counting stats. The frontend shows `summary` verbatim when present.
 */
export interface QualificationInfo {
  kind: "qualified" | "manual" | "none" | "not_applicable";
  /**
   * "Qualified hitters · at least 2,349 AB over 2020–2025". `null` until the API publishes
   * surface-neutral copy (handoff R4); the UI then shows only the number.
   */
  summary: string | null;
  minAtBats: number | null;
  scope: "season" | "span";
}

/** The answer-first headline block, written by the API. */
export interface Answer {
  /** Short claim: "Aaron Judge, 2024: 1.159 OPS". */
  headline: string;
  /**
   * One or two scoped sentences: "…is the highest among the 2,412 seasons shown (2010–2025)."
   * `null` when the source doesn't provide it (real API until handoff R2/R3).
   */
  detail: string | null;
  /** Optional context line, e.g. "2024 · NYY · CF". */
  context: string | null;
}

/* ------------------------------------------------------------------ catalog */

export interface ExplorerDefaults {
  yearRange: YearRange;
  metric: MetricKey;
}

export interface Catalog {
  /** First and last seasons the data covers. */
  years: YearRange;
  metrics: MetricDefinition[];
  historical: ExplorerDefaults & { metrics: MetricKey[]; order: SortOrder };
  leaderboards: ExplorerDefaults & { metrics: MetricKey[] };
}

/* ------------------------------------------------------- historical explorer */

export interface HistoricalExplorerQuery {
  yearRange: YearRange;
  metric: MetricKey;
  order: SortOrder;
  /** Restrict to one player's seasons; null = every player. */
  playerId: string | null;
}

/** The default visual the API recommends for this answer. */
export type SeasonChart =
  | {
      /** Best seasons across players: horizontal ranking bars. */
      kind: "ranking";
      title: string;
      /** Season ids from `seasons`, in ranked order (at most 10). */
      seasonIds: string[];
    }
  | {
      /** One player's seasons over time: a line by year. */
      kind: "timeline";
      title: string;
      /** Season ids from `seasons`, in year order. */
      seasonIds: string[];
    };

export interface HistoricalExplorerResult {
  /** The question actually answered (normalised by the API). Display this, not the request. */
  query: HistoricalExplorerQuery;
  metric: MetricDefinition;
  qualification: QualificationInfo;
  /** null when nothing matched. */
  answer: Answer | null;
  /** The season the answer is about. */
  topSeasonId: string | null;
  /** Metrics to show as tiles for the top season, the ranked metric first. */
  keyMetrics: MetricKey[];
  /** Table columns, in display order. */
  columns: MetricKey[];
  /** Ranked seasons (first page). Player scope: every season, ranked; see `qualified`. */
  seasons: PlayerSeason[];
  /** Seasons matching the question in total (may exceed `seasons.length`). */
  totalCount: number;
  player: PlayerSummary | null;
  chart: SeasonChart | null;
}

/* ------------------------------------------------------------- leaderboards */

export interface LeaderboardQuery {
  yearRange: YearRange;
  metric: MetricKey;
}

export interface LeaderboardEntry {
  rank: number;
  player: Pick<PlayerSummary, "id" | "name">;
  /** Seasons played inside the range; `null` when the source doesn't report it (real API). */
  seasons: number | null;
  /** Totals (and rates from totals) over the range. */
  stats: StatLine;
}

export interface ScoreDefinition {
  /** "HR + RBI + SB, each weighted 1"; `null` until the API words it (handoff R3). */
  summary: string | null;
  weights: { metric: MetricKey; weight: number }[];
}

export interface LeaderboardResult {
  query: LeaderboardQuery;
  metric: MetricDefinition;
  qualification: QualificationInfo;
  answer: Answer | null;
  /** Ranked entries (first page). */
  entries: LeaderboardEntry[];
  /** Players ranked in total. */
  totalRanked: number;
  columns: MetricKey[];
  /** Present when `metric` is the weighted score. */
  score: ScoreDefinition | null;
}
