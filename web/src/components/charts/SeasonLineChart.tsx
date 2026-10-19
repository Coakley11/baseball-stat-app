"use client";

import { useEffect, useId, useRef, useState, type PointerEvent } from "react";

import styles from "./charts.module.css";
import { linear, niceTicks } from "./scale";

export interface SeasonPoint {
  year: number;
  value: number | null;
  /** Value as displayed. */
  display: string;
  /** The answer's season: larger marker + direct label. */
  highlight?: boolean;
  /** Drawn hollow, e.g. below the at-bat minimum. */
  hollow?: boolean;
}

interface SeasonLineChartProps {
  title: string;
  points: SeasonPoint[];
  /** Short metric label for the tooltip and table ("OPS"). */
  valueLabel: string;
  /** Formats axis tick values the same way as `display`. */
  formatTick: (value: number) => string;
  /** Legend text for hollow markers; shown only when some point is hollow. */
  hollowLabel?: string;
}

const HEIGHT = 240;
const MARGIN = { top: 24, right: 20, bottom: 30, left: 48 };

/**
 * One player's metric by season: a 2px line with markers, gaps where a value is missing,
 * hairline grid, a crosshair tooltip on pointer hover, and the same numbers in a data table
 * one click away (keyboard and screen-reader alternative).
 */
export function SeasonLineChart({ title, points, valueLabel, formatTick, hollowLabel }: SeasonLineChartProps) {
  const captionId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [active, setActive] = useState<number | null>(null);

  useEffect(() => {
    const node = containerRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(260, Math.round(entry.contentRect.width)));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const sorted = [...points].sort((a, b) => a.year - b.year);
  const values = sorted.flatMap((p) => (p.value === null ? [] : [p.value]));
  const ticks = niceTicks(Math.min(...values), Math.max(...values), 4);
  const yMin = ticks[0] ?? 0;
  const yMax = ticks[ticks.length - 1] ?? 1;
  const first = sorted[0]?.year ?? 0;
  const last = sorted[sorted.length - 1]?.year ?? 0;
  const innerWidth = width - MARGIN.left - MARGIN.right;
  const x = first === last ? () => MARGIN.left + innerWidth / 2 : linear([first, last], [MARGIN.left, width - MARGIN.right]);
  const y = linear([yMin, yMax], [HEIGHT - MARGIN.bottom, MARGIN.top]);

  // Break the line where a season has no value.
  const segments: SeasonPoint[][] = [[]];
  for (const p of sorted) {
    if (p.value === null) segments.push([]);
    else segments[segments.length - 1]!.push(p);
  }
  const paths = segments
    .filter((s) => s.length > 1)
    .map((s) => s.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.year).toFixed(1)},${y(p.value!).toFixed(1)}`).join(""));

  const labelEvery = Math.max(1, Math.ceil(sorted.length / Math.max(1, Math.floor(innerWidth / 46))));
  const activePoint = active === null ? null : sorted[active];
  const anyHollow = sorted.some((p) => p.hollow);

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * width;
    let nearest = 0;
    sorted.forEach((p, i) => {
      if (Math.abs(x(p.year) - px) < Math.abs(x(sorted[nearest]!.year) - px)) nearest = i;
    });
    setActive(nearest);
  }

  const summary = `${title}. ${sorted.length} seasons from ${first} to ${last}.`;

  return (
    <figure className={styles.figure} aria-labelledby={captionId}>
      <figcaption id={captionId} className={styles.caption}>
        {title}
      </figcaption>
      {anyHollow && hollowLabel && (
        <p className={styles.legend}>
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
            <circle cx="6" cy="6" r="4" className={styles.hollowMark} />
          </svg>
          {hollowLabel}
        </p>
      )}
      <div ref={containerRef} className={styles.plot}>
        <svg
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          role="img"
          aria-label={summary}
          onPointerMove={onPointerMove}
          onPointerLeave={() => setActive(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(t)} y2={y(t)} className={styles.grid} />
              <text x={MARGIN.left - 8} y={y(t)} className={styles.tickY} dominantBaseline="middle" textAnchor="end">
                {formatTick(t)}
              </text>
            </g>
          ))}
          {sorted.map((p, i) =>
            i % labelEvery === 0 || i === sorted.length - 1 ? (
              <text key={p.year} x={x(p.year)} y={HEIGHT - 8} className={styles.tickX} textAnchor="middle">
                {p.year}
              </text>
            ) : null,
          )}
          {activePoint && (
            <line x1={x(activePoint.year)} x2={x(activePoint.year)} y1={MARGIN.top - 8} y2={HEIGHT - MARGIN.bottom} className={styles.crosshair} />
          )}
          {paths.map((d) => (
            <path key={d} d={d} className={styles.line} />
          ))}
          {sorted.map((p) =>
            p.value === null ? null : (
              <circle
                key={p.year}
                cx={x(p.year)}
                cy={y(p.value)}
                r={p.highlight ? 6 : 4.5}
                className={p.hollow ? styles.hollowMark : styles.mark}
              />
            ),
          )}
          {sorted.map((p) =>
            p.highlight && p.value !== null ? (
              <text
                key={`label-${p.year}`}
                x={Math.min(Math.max(x(p.year), MARGIN.left + 16), width - MARGIN.right - 16)}
                y={y(p.value) - 12}
                className={styles.directLabel}
                textAnchor="middle"
              >
                {p.display}
              </text>
            ) : null,
          )}
        </svg>
        {activePoint && (
          <div
            className={styles.tooltip}
            style={{ left: `${Math.min(85, Math.max(15, (x(activePoint.year) / width) * 100))}%` }}
            aria-hidden="true"
          >
            <strong>{activePoint.year}</strong> · {activePoint.display} {valueLabel}
            {activePoint.hollow && hollowLabel ? <span className={styles.tooltipNote}>{hollowLabel}</span> : null}
          </div>
        )}
      </div>
      <details className={styles.tableToggle}>
        <summary>Show as table</summary>
        <table className={styles.dataTable}>
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr>
              <th scope="col">Season</th>
              <th scope="col">{valueLabel}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <tr key={p.year}>
                <th scope="row">{p.year}</th>
                <td>
                  {p.display}
                  {p.hollow && hollowLabel ? ` (${hollowLabel.toLowerCase()})` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
