import type { Catalog, HistoricalExplorerResult } from "@/lib/api";
import { formatCount, formatStat, MISSING } from "@/lib/format";

import { metricOf } from "../shared/params";
import shared from "../shared/questions.module.css";

/** Every returned season in API rank order. Scrolls inside its own frame on phones. */
export function SeasonTable({ result, catalog }: { result: HistoricalExplorerResult; catalog: Catalog }) {
  const playerScope = result.query.playerId !== null;
  const order = result.query.order === "asc" ? "ascending" : "descending";
  const columns = result.columns.map((key) => ({ key, def: metricOf(catalog, key) }));
  const caption = `Showing ${formatCount(result.seasons.length)} of ${formatCount(result.totalCount)} seasons, ranked by ${result.metric.name} (${result.query.order === "asc" ? "lowest" : "highest"} first).`;

  return (
    <div className={shared.tableScroll} role="region" aria-label="All seasons" tabIndex={0}>
      <table className={shared.table}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            {!playerScope && (
              <th scope="col" className={shared.stickyCell}>
                Player
              </th>
            )}
            <th scope="col" className={playerScope ? shared.stickyCell : shared.textCell}>
              Season
            </th>
            <th scope="col" className={shared.textCell}>
              Team
            </th>
            <th scope="col" className={shared.textCell}>
              Pos
            </th>
            {columns.map(({ key, def }) => {
              const sorted = key === result.metric.key;
              return (
                <th key={key} scope="col" className={sorted ? shared.sortedCol : undefined} aria-sort={sorted ? order : undefined}>
                  {def?.label ?? key}
                  {sorted && <span aria-hidden="true">{order === "ascending" ? " ↑" : " ↓"}</span>}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {result.seasons.map((season, i) => (
            <tr key={season.id}>
              <td>{i + 1}</td>
              {!playerScope && (
                <th scope="row" className={shared.stickyCell}>
                  {season.player.name}
                </th>
              )}
              {playerScope ? (
                <th scope="row" className={shared.stickyCell}>
                  {season.year}
                  {!season.qualified && <span className={shared.rowNote}>Below AB minimum</span>}
                </th>
              ) : (
                <td className={shared.textCell}>{season.year}</td>
              )}
              <td className={shared.textCell}>{season.team ?? MISSING}</td>
              <td className={shared.textCell}>{season.position ?? MISSING}</td>
              {columns.map(({ key, def }) => (
                <td key={key} className={key === result.metric.key ? shared.sortedCol : undefined}>
                  {formatStat(season.stats[key], def?.format ?? "count")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
