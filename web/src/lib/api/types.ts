/**
 * View models the pages use. The wire format is the generated OpenAPI types
 * (generated/baseball-api.ts); only the HTTP adapter (http/mapping.ts) reads those and fills
 * these in, so pages never depend on wire names. Pages import from "@/lib/api", never from a
 * fixture or the generated file.
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
 * `score` → one decimal at most, `year` → "2024" (no thousands separator).
 */
export type StatFormat = "rate" | "count" | "score" | "year";

export interface MetricDefinition {
  key: MetricKey;
  /** Short label for tiles, axes and table headers: "HR", "AVG", "Score". */
  label: string;
  /** Plain-language name for sentences and controls ("home runs"), from the API. */
  name: string;
  format: StatFormat;
}

/** Rows per page of a ranked table (the page size the pages ask the API for). */
export const TABLE_PAGE_SIZE = 25;

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
   * Whether the season meets the active minimums (the API's `meets_minimum`). Seasons below
   * them only appear on one player's timeline, unranked.
   */
  qualified: boolean;
  /** 1-based rank in the full result; `null` for an unranked below-minimum season. */
  rank: number | null;
}

/**
 * The sample-size rule a rate-stat ranking is using (rate_stat_qualification.py).
 * `not_applicable` for counting stats. The frontend shows `summary` verbatim when present.
 */
export interface QualificationInfo {
  kind: "qualified" | "manual" | "none" | "not_applicable";
  /** The chip line: "Qualified hitters · at least 2,349 AB over 2020–2025". `null` for counting stats. */
  summary: string | null;
  /** One or two plain-text sentences on the rule in force; `null` when there is none. */
  explanation: string | null;
  minAtBats: number | null;
  scope: "season" | "span";
}

/** The answer-first headline block, written by the API. */
export interface Answer {
  /** Short claim: "Aaron Judge, 2024: 1.159 OPS". */
  headline: string;
  /** One or two scoped sentences: "…is the highest among the 2,412 seasons shown (2010–2025)." */
  detail: string;
  /** Context line, e.g. "2024 · New York Yankees · OF" or "Ranked by home runs". */
  context: string;
}

/* ------------------------------------------------------------------ catalog */

export interface ExplorerDefaults {
  yearRange: YearRange;
  metric: MetricKey;
}

/**
 * One table column, exactly as the API describes it: the header, where the value sits in a row
 * (`field`, a dotted path like "stats.HR"), and the stat it belongs to (`null` for text).
 * The same list is the CSV header, so tables and exports always agree.
 */
export interface TableColumn {
  label: string;
  field: string;
  metric: MetricKey | null;
}

export interface FilterOption {
  value: string;
  label: string;
}

export type PositionSource = "season" | "career";

/** The filters the API applies to Historical Explorer (parameters of /seasons). */
export interface HistoricalFilters {
  /** Batting hands to include; empty = all. */
  bats: string[];
  positionSource: PositionSource;
  /** Primary positions to include; empty = all. */
  positions: string[];
  /** Franchises / leagues to include (values from the catalog); empty = all. */
  teams: string[];
  /** One row per player-season (primary team) instead of one per team. */
  combine: boolean;
}

/**
 * Minimums the user sets (the API applies them; nothing is evaluated here). `ab: null` means the
 * API's automatic qualified minimum; a number, including 0, is the user's own. `stats` holds
 * other stat minimums by key ("HR": 20).
 */
export interface Minimums {
  ab: number | null;
  stats: Record<MetricKey, number>;
}

export const NO_MINIMUMS: Minimums = { ab: null, stats: {} };

export const NO_HISTORICAL_FILTERS: HistoricalFilters = {
  bats: [],
  positionSource: "season",
  positions: [],
  teams: [],
  combine: false,
};

export interface Catalog {
  /** First and last seasons the data covers. */
  years: YearRange;
  metrics: MetricDefinition[];
  historical: ExplorerDefaults & {
    metrics: MetricKey[];
    order: SortOrder;
    columns: TableColumn[];
    filters: {
      bats: FilterOption[];
      positionSources: FilterOption[];
      /** Position options for each position source. */
      positionsBySource: Record<PositionSource, string[]>;
      teams: FilterOption[];
      /** Stats that accept a user minimum (besides at-bats). */
      minimumColumns: MetricKey[];
    };
  };
  leaderboards: ExplorerDefaults & {
    metrics: MetricKey[];
    columns: TableColumn[];
    /** Default weights behind the weighted score. */
    weights: Record<MetricKey, number>;
    weightStats: MetricKey[];
    weightBounds: [number, number];
    weightStep: number;
    /** The default and allowed range of "how many players". */
    limit: number;
    limitBounds: [number, number];
    /** Stats that accept a user minimum (besides at-bats). */
    minimumColumns: MetricKey[];
  };
}

/** A table cell value, resolved from the row by the column's `field`. */
export type CellValue = string | number | null;

export interface TableRow {
  id: string;
  /** The API's rank for this row; `null` for an unranked row. */
  rank: number | null;
  /** One value per column, in column order. */
  cells: CellValue[];
  /** A short note about this row, e.g. "Below AB minimum". */
  note: string | null;
}

export interface ResultTable {
  columns: TableColumn[];
  rows: TableRow[];
}

/* ------------------------------------------------------- historical explorer */

export interface HistoricalExplorerQuery {
  yearRange: YearRange;
  metric: MetricKey;
  order: SortOrder;
  /** Restrict to one player's seasons; null = every player. */
  playerId: string | null;
  /** Filters; omitted = none. */
  filters?: HistoricalFilters;
  /** Minimums the user set; omitted = the API's automatic qualified minimum. */
  minimums?: Minimums;
  /**
   * For one player's seasons: which bounds of `yearRange` the user actually chose. A bound they
   * didn't choose is left out of the request, so the API uses the player's career for it.
   * Ignored for all players, which always use `yearRange`.
   */
  explicitRange?: { start: boolean; end: boolean };
  /** 0-based position of the first row wanted; omitted = 0. */
  offset?: number;
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
  /** Metrics to show as tiles for the top season, in order (the API's `tile_metrics`). */
  keyMetrics: MetricKey[];
  /** The page of seasons returned, with their stats (for tiles and charts). */
  seasons: PlayerSeason[];
  /** The same page as a table, in the API's column order. */
  table: ResultTable;
  /** Rows in the full result (one player's view also counts unranked seasons). */
  totalCount: number;
  /** Seasons that pass the filters and minimums. */
  rankedCount: number;
  /** 0-based position of the first row returned. */
  offset: number;
  player: PlayerSummary | null;
  chart: SeasonChart | null;
}

/* ------------------------------------------------------------- leaderboards */

export interface LeaderboardQuery {
  yearRange: YearRange;
  metric: MetricKey;
  /** How many players (Top N); omitted = the catalog default. */
  limit?: number;
  /** Minimums the user set; omitted = the API's automatic qualified minimum. */
  minimums?: Minimums;
  /** Custom weights for the score; omitted = the API's defaults. */
  weights?: Record<MetricKey, number>;
}

export interface LeaderboardEntry {
  rank: number;
  player: Pick<PlayerSummary, "id" | "name">;
  /** Totals (and rates from totals) over the range. */
  stats: StatLine;
}

export interface ScoreDefinition {
  weights: { metric: MetricKey; weight: number }[];
}

export interface LeaderboardResult {
  query: LeaderboardQuery;
  metric: MetricDefinition;
  qualification: QualificationInfo;
  answer: Answer | null;
  /** Ranked entries (the Top N asked for). */
  entries: LeaderboardEntry[];
  /** Players ranked in total. */
  totalRanked: number;
  table: ResultTable;
  /** Present when `metric` is the weighted score. */
  score: ScoreDefinition | null;
}
