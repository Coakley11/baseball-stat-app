import type { Catalog, CellValue, MetricDefinition, ResultTable } from "@/lib/api";
import { formatStat, MISSING } from "@/lib/format";

import { metricOf } from "./params";
import styles from "./questions.module.css";

/** The cell as text: stats by their metric's format, text as given, nothing as a dash. */
function cellText(value: CellValue, metric: MetricDefinition | undefined): string {
  if (value === null) return MISSING;
  if (typeof value === "string") return value;
  return metric ? formatStat(value, metric.format) : String(value);
}

/**
 * A result table drawn from the API's own column list: the headers, their order and where each
 * value sits in a row all come from `table.columns`, the same metadata that heads the CSV export.
 * The frontend adds only formatting. Scrolls inside its own frame on phones; the player column
 * stays put.
 */
export function ResultTableView({
  table,
  catalog,
  label,
  caption,
  rankedMetric,
  sortDirection,
  firstRank = 1,
}: {
  table: ResultTable;
  catalog: Catalog;
  /** Accessible name of the scroll region. */
  label: string;
  caption: string;
  /** The stat the ranking is by; its column is marked. */
  rankedMetric: string;
  sortDirection: "ascending" | "descending";
  /** Position shown when a row has no rank of its own (never used for ranked rows). */
  firstRank?: number;
}) {
  const columns = table.columns.map((column) => ({
    column,
    metric: column.metric ? metricOf(catalog, column.metric) : undefined,
    sticky: column.field === "player.name",
    ranked: column.metric === rankedMetric,
  }));

  return (
    <div className={styles.tableScroll} role="region" aria-label={label} tabIndex={0}>
      <table className={styles.table}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            {columns.map(({ column, metric, sticky, ranked }) => (
              <th
                key={column.field}
                scope="col"
                className={[sticky ? styles.stickyCell : "", !metric ? styles.textCell : "", ranked ? styles.sortedCol : ""].filter(Boolean).join(" ") || undefined}
                aria-sort={ranked ? sortDirection : undefined}
              >
                {column.label}
                {ranked && <span aria-hidden="true">{sortDirection === "ascending" ? " ↑" : " ↓"}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={row.id}>
              <td>{row.rank ?? (row.note ? MISSING : firstRank + i)}</td>
              {columns.map(({ column, metric, sticky, ranked }, c) => {
                const text = cellText(row.cells[c] ?? null, metric);
                const className = [sticky ? styles.stickyCell : "", !metric ? styles.textCell : "", ranked ? styles.sortedCol : ""].filter(Boolean).join(" ") || undefined;
                return sticky ? (
                  <th key={column.field} scope="row" className={className}>
                    {text}
                    {row.note && <span className={styles.rowNote}>{row.note}</span>}
                  </th>
                ) : (
                  <td key={column.field} className={className}>
                    {text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
