/**
 * Wire format (generated from the pinned OpenAPI schema) → the view models the pages use.
 *
 * Renames, reshaping and path lookups only. Every value is copied from the response; nothing is
 * ranked, filtered, totalled, qualified or worded here. Table cells are found by the API's own
 * column metadata (`field` paths), so the column order is the API's, not ours.
 */
import type { components } from "../generated/baseball-api";
import type {
  Catalog,
  CellValue,
  HistoricalExplorerQuery,
  HistoricalExplorerResult,
  LeaderboardQuery,
  LeaderboardResult,
  MetricDefinition,
  PlayerSeason,
  PlayerSummary,
  QualificationInfo,
  ResultTable,
  StatLine,
  TableColumn,
} from "../types";

type Schemas = components["schemas"];

export function toMetric(metric: Schemas["MetricInfo"]): MetricDefinition {
  return { key: metric.key, label: metric.label, name: metric.name, format: metric.kind };
}

function toColumns(columns: readonly Schemas["Column"][]): TableColumn[] {
  return columns.map((c) => ({ label: c.label, field: c.field, metric: c.metric }));
}

export function toCatalog(res: Schemas["Catalog"]): Catalog {
  const h = res.historical;
  const l = res.leaderboards;
  const positions = h.filters.positions_by_source;
  return {
    years: { start: res.seasons.first, end: res.seasons.last },
    metrics: res.metrics.map(toMetric),
    historical: {
      yearRange: { start: h.defaults.start, end: h.defaults.end },
      metric: h.defaults.metric,
      order: h.defaults.order,
      metrics: [...h.metrics],
      columns: toColumns(h.columns),
      filters: {
        bats: h.filters.bats.map((o) => ({ ...o })),
        positionSources: h.filters.position_sources.map((o) => ({ ...o })),
        positionsBySource: {
          season: [...(positions.season ?? h.filters.positions)],
          career: [...(positions.career ?? [])],
        },
        teams: h.filters.teams.map((o) => ({ ...o })),
      },
    },
    leaderboards: {
      yearRange: { start: l.defaults.start, end: l.defaults.end },
      metric: l.defaults.metric,
      metrics: [...l.metrics],
      columns: toColumns(l.columns),
      weights: { ...l.defaults.weights },
      weightStats: [...l.weight_stats],
      weightBounds: [l.weight_bounds[0] ?? 0, l.weight_bounds[1] ?? 10],
      weightStep: l.weight_step,
      limit: l.defaults.limit,
      limitBounds: [l.limit_bounds[0] ?? 5, l.limit_bounds[1] ?? 100],
    },
  };
}

export function toStatLine(stats: Schemas["StatLine"]): StatLine {
  const out: StatLine = {};
  for (const [key, value] of Object.entries(stats)) out[key] = value ?? null;
  return out;
}

/** Follows a dotted path ("stats.HR", "team.season_name") into a row. Missing → null. */
export function valueAtPath(row: unknown, path: string): CellValue {
  let current: unknown = row;
  for (const key of path.split(".")) {
    if (current === null || typeof current !== "object") return null;
    current = (current as Record<string, unknown>)[key];
  }
  return typeof current === "string" || typeof current === "number" ? current : null;
}

function buildTable<Row extends object>(
  columns: TableColumn[],
  rows: readonly Row[],
  describe: (row: Row, index: number) => { id: string; rank: number | null; note: string | null },
): ResultTable {
  return {
    columns,
    rows: rows.map((row, i) => ({ ...describe(row, i), cells: columns.map((c) => valueAtPath(row, c.field)) })),
  };
}

/**
 * `kind` reads the API's flags: `applies` (a minimum is in force) and `mode`. A rate-stat ranking
 * with no minimum has `applies: false` but still gets a chip line, so it is "none". The API's
 * Markdown `text` is not used: it names a Streamlit control.
 */
export function toQualification(q: Schemas["Qualification"], scope: "season" | "span"): QualificationInfo {
  const summary = q.summary || null;
  const kind = q.applies ? (q.mode === "manual" ? "manual" : "qualified") : summary ? "none" : "not_applicable";
  return { kind, summary, explanation: q.explanation ?? null, minAtBats: q.applies ? q.min_ab : null, scope };
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
    qualified: row.meets_minimum,
    rank: row.rank,
  };
}

export function toHistoricalResult(
  res: Schemas["SeasonLeadersResult"],
  request: HistoricalExplorerQuery,
  columns: TableColumn[],
): HistoricalExplorerResult {
  const metric = toMetric(res.metric);
  const seasons = res.rows.map(seasonFromRow);
  const first = seasons[0];
  const answer = res.answer ? { headline: res.answer.headline, detail: res.answer.body, context: res.answer.context } : null;
  const onePlayer = res.player_id !== null;
  const playerName = first?.player.name ?? null;

  let chart: HistoricalExplorerResult["chart"] = null;
  if (onePlayer && playerName) {
    chart = { kind: "timeline", title: `${playerName} · ${metric.name} by season`, seasonIds: seasons.map((s) => s.id) };
  } else if (!onePlayer && res.offset === 0 && seasons.length > 0) {
    const top = seasons.slice(0, 10);
    chart = { kind: "ranking", title: `Top ${top.length} seasons by ${metric.name}`, seasonIds: top.map((s) => s.id) };
  }

  return {
    query: { ...request, yearRange: { start: res.start, end: res.end }, metric: res.metric.key, order: res.order, playerId: res.player_id },
    metric,
    qualification: toQualification(res.qualification, "season"),
    answer,
    // rows[0] is the answer's season when this is the first page.
    topSeasonId: res.offset === 0 && first && first.rank === 1 ? first.id : null,
    keyMetrics: res.answer ? [...res.answer.tile_metrics] : [],
    seasons,
    table: buildTable(columns, res.rows, (row, i) => ({
      id: seasons[i]!.id,
      rank: row.rank,
      note: row.meets_minimum ? null : "Below the minimum",
    })),
    totalCount: res.total_rows,
    rankedCount: res.ranked_rows,
    offset: res.offset,
    player: onePlayer && first ? { id: first.player.id, name: first.player.name, bats: res.rows[0]?.bats ?? null, primaryPosition: null, firstSeason: null, lastSeason: null } : null,
    chart,
  };
}

export function toLeaderboardResult(
  res: Schemas["LeaderboardResult"],
  request: LeaderboardQuery,
  columns: TableColumn[],
): LeaderboardResult {
  return {
    query: { ...request, yearRange: { start: res.start, end: res.end }, metric: res.metric.key },
    metric: toMetric(res.metric),
    qualification: toQualification(res.qualification, "span"),
    answer: res.answer ? { headline: res.answer.headline, detail: res.answer.body, context: res.answer.context } : null,
    entries: res.rows.map((row) => ({
      rank: row.rank,
      player: { id: row.player.player_id, name: row.player.name },
      stats: { ...toStatLine(row.stats), score: row.score },
    })),
    totalRanked: res.total_rows,
    table: buildTable(columns, res.rows, (row) => ({ id: row.player.player_id, rank: row.rank, note: null })),
    score: res.metric.key === "score" ? { weights: Object.entries(res.weights).map(([metric, weight]) => ({ metric, weight })) } : null,
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
