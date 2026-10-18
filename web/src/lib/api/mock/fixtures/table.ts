/**
 * SAMPLE DATA helpers: build a result table from the catalog's column metadata, the same way the
 * real adapter does (a lookup by each column's `field` path). Nothing is computed.
 */
import { valueAtPath } from "../../http/mapping";
import type { LeaderboardEntry, PlayerSeason, ResultTable, TableColumn } from "../../types";

export function seasonTable(columns: TableColumn[], seasons: PlayerSeason[]): ResultTable {
  return {
    columns,
    rows: seasons.map((s) => ({
      id: s.id,
      rank: s.rank,
      note: s.qualified ? null : "Below the minimum",
      cells: columns.map((c) =>
        valueAtPath(
          { year: s.year, player: { name: s.player.name }, bats: null, position: s.position, team: { season_name: s.teamName ?? s.team }, stats: s.stats },
          c.field,
        ),
      ),
    })),
  };
}

export function leaderboardTable(columns: TableColumn[], entries: LeaderboardEntry[]): ResultTable {
  return {
    columns,
    rows: entries.map((e) => ({
      id: e.player.id,
      rank: e.rank,
      note: null,
      cells: columns.map((c) => valueAtPath({ player: { name: e.player.name }, bats: null, stats: e.stats, score: e.stats.score ?? null }, c.field)),
    })),
  };
}
