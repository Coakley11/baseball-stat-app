/**
 * Wire format (generated from the pinned OpenAPI schema) → the view models the pages use.
 *
 * Renames and reshapes only. Every value is copied from the response; nothing is ranked,
 * filtered, totalled, qualified or worded here. Where the API doesn't provide something yet
 * (docs/WEB_M2_SCHEMA_COMPATIBILITY.md), the view-model field stays empty and the page shows
 * less. It never shows a guess.
 */
import type { components } from "../generated/baseball-api";
import type {
  HistoricalExplorerResult,
  LeaderboardResult,
  MetricDefinition,
  PlayerSeason,
  PlayerSummary,
  QualificationInfo,
  StatLine,
} from "../types";

type Schemas = components["schemas"];

/** Table columns, in the Streamlit pages' order (presentation; the API returns the full StatLine). */
export const SEASON_COLUMNS = ["R", "AB", "H", "2B", "3B", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"];
export const LEADERBOARD_COLUMNS = ["G", ...SEASON_COLUMNS];

export function toMetric(metric: Schemas["MetricInfo"]): MetricDefinition {
  const format = metric.kind === "rate" ? "rate" : metric.kind === "score" ? "score" : "count";
  // No plain-language name yet (handoff R5): the label stands in.
  return { key: metric.key, label: metric.label, name: metric.label, format };
}

export function toStatLine(stats: Schemas["StatLine"]): StatLine {
  const out: StatLine = {};
  for (const [key, value] of Object.entries(stats)) out[key] = value ?? null;
  return out;
}

/**
 * `kind` reads the API's own flags: `applies` (a minimum is in force) and `mode`. A rate-stat
 * ranking with no minimum is the one case where `applies` is false but the API still writes a
 * caption. The caption itself isn't shown (Markdown, Streamlit control names; handoff R4).
 */
export function toQualification(q: Schemas["Qualification"], scope: "season" | "span"): QualificationInfo {
  const kind = q.applies ? (q.mode === "manual" ? "manual" : "qualified") : q.text ? "none" : "not_applicable";
  return { kind, summary: null, minAtBats: q.applies ? q.min_ab : null, scope };
}

function seasonFromRow(row: Schemas["SeasonRow"]): PlayerSeason {
  return {
    id: `${row.player.player_id}-${row.year}-${row.team?.team_id ?? "none"}`,
    player: { id: row.player.player_id, name: row.player.name },
    year: row.year,
    team: row.team?.team_id ?? null,
    teamName: row.team?.season_name ?? row.team?.name ?? null,
    position: row.position,
    stats: toStatLine(row.stats),
    // Every row the API returns has passed the active minimum (it drops the others).
    qualified: true,
  };
}

export function toHistoricalResult(res: Schemas["SeasonLeadersResult"]): HistoricalExplorerResult {
  const metric = toMetric(res.metric);
  const seasons = res.rows.map(seasonFromRow);
  const top = seasons[0];
  const chartIds = seasons.slice(0, 10).map((s) => s.id);
  return {
    query: { yearRange: { start: res.start, end: res.end }, metric: res.metric.key, order: res.order, playerId: null },
    metric,
    qualification: toQualification(res.qualification, "season"),
    // The API's headline describes its first row; detail/context/tiles wait on handoff R2.
    answer: res.headline && top ? { headline: res.headline, detail: null, context: null } : null,
    topSeasonId: res.headline && top ? top.id : null,
    keyMetrics: [],
    columns: SEASON_COLUMNS,
    seasons,
    totalCount: res.total_rows,
    player: null,
    chart: chartIds.length ? { kind: "ranking", title: `Top ${chartIds.length} seasons by ${metric.label}`, seasonIds: chartIds } : null,
  };
}

export function toLeaderboardResult(res: Schemas["LeaderboardResult"]): LeaderboardResult {
  const metric = toMetric(res.metric);
  return {
    query: { yearRange: { start: res.start, end: res.end }, metric: res.metric.key },
    metric,
    qualification: toQualification(res.qualification, "span"),
    // No answer sentence in the API yet (handoff R3).
    answer: null,
    entries: res.rows.map((row) => ({
      rank: row.rank,
      player: { id: row.player.player_id, name: row.player.name },
      seasons: null,
      stats: { ...toStatLine(row.stats), score: row.score },
    })),
    totalRanked: res.total_rows,
    columns: res.metric.key === "score" ? ["score", ...LEADERBOARD_COLUMNS] : LEADERBOARD_COLUMNS,
    score:
      res.metric.key === "score"
        ? { summary: null, weights: Object.entries(res.weights).map(([m, weight]) => ({ metric: m, weight })) }
        : null,
  };
}

export function toPlayerSummary(summary: Schemas["PlayerSummary"]): PlayerSummary {
  return {
    id: summary.player.player_id,
    // `label` is the API's unique display name (adds the career span when names collide).
    name: summary.player.label,
    bats: summary.bats ?? null,
    primaryPosition: summary.career_primary_position ?? null,
    firstSeason: summary.first_season,
    lastSeason: summary.last_season,
  };
}
