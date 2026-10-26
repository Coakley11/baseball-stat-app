"use client";

import { useId } from "react";

import type { Catalog, HistoricalFilters, PositionSource } from "@/lib/api";

import shared from "../shared/questions.module.css";

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/**
 * Historical Explorer's filters (Explore more): batting hand, position (by season or career),
 * franchise or league, and one row per player-season. Options come from the API's catalog; each
 * change updates the URL, and the API does the filtering.
 */
export function HistoricalFilterPanel({
  catalog,
  filters,
  order,
  onChange,
  onOrder,
}: {
  catalog: Catalog;
  filters: HistoricalFilters;
  order: "asc" | "desc";
  onChange: (next: HistoricalFilters) => void;
  onOrder: (order: "asc" | "desc") => void;
}) {
  const id = useId();
  const { filters: options } = catalog.historical;
  const positions = options.positionsBySource[filters.positionSource];

  return (
    <div className={shared.filterGrid}>
      <div className={shared.field}>
        <label className={shared.label} htmlFor={`${id}-order`}>
          Order
        </label>
        <select id={`${id}-order`} className={shared.select} value={order} onChange={(e) => onOrder(e.target.value === "asc" ? "asc" : "desc")}>
          <option value="desc">Highest first</option>
          <option value="asc">Lowest first</option>
        </select>
      </div>

      <fieldset className={shared.filterGroup} style={{ gridColumn: "1 / -1" }}>
        <legend>
          Franchise / league
          {filters.teams.length > 0 && (
            <span className={shared.hint}>
              {" "}
              · {filters.teams.length} selected{" "}
              <button type="button" className={shared.linkButton} onClick={() => onChange({ ...filters, teams: [] })}>
                Clear
              </button>
            </span>
          )}
        </legend>
        <div className={`${shared.checks} ${shared.checksScroll}`}>
          {options.teams
            .filter((o) => o.value !== "All Teams")
            .map((o) => (
              <label key={o.value} className={shared.check}>
                <input type="checkbox" checked={filters.teams.includes(o.value)} onChange={() => onChange({ ...filters, teams: toggle(filters.teams, o.value) })} />
                {o.label}
              </label>
            ))}
        </div>
        <p className={shared.note} style={{ marginTop: "var(--space-2)" }}>
          {filters.teams.length === 0 ? "All teams." : "Seasons with any of the selected teams or leagues."}
        </p>
      </fieldset>

      <div className={shared.field}>
        <label className={shared.label} htmlFor={`${id}-psrc`}>
          Position filter mode
        </label>
        <select
          id={`${id}-psrc`}
          className={shared.select}
          value={filters.positionSource}
          onChange={(e) => onChange({ ...filters, positionSource: e.target.value as PositionSource, positions: [] })}
        >
          {options.positionSources.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <fieldset className={shared.filterGroup}>
        <legend>Batting hand</legend>
        <div className={shared.checks}>
          {options.bats.map((o) => (
            <label key={o.value} className={shared.check}>
              <input type="checkbox" checked={filters.bats.includes(o.value)} onChange={() => onChange({ ...filters, bats: toggle(filters.bats, o.value) })} />
              {o.label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className={shared.filterGroup}>
        <legend>Primary position</legend>
        <div className={shared.checks}>
          {positions.map((p) => (
            <label key={p} className={shared.check}>
              <input type="checkbox" checked={filters.positions.includes(p)} onChange={() => onChange({ ...filters, positions: toggle(filters.positions, p) })} />
              {p}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className={shared.filterGroup}>
        <legend>Split-team seasons</legend>
        <label className={shared.check}>
          <input type="checkbox" checked={filters.combine} onChange={() => onChange({ ...filters, combine: !filters.combine })} />
          One row per player-season
        </label>
      </fieldset>
    </div>
  );
}
