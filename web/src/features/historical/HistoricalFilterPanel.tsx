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
  const team = filters.teams[0] ?? "All Teams";

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

      <div className={shared.field}>
        <label className={shared.label} htmlFor={`${id}-team`}>
          Franchise / league
        </label>
        <select
          id={`${id}-team`}
          className={shared.select}
          value={team}
          onChange={(e) => onChange({ ...filters, teams: e.target.value === "All Teams" ? [] : [e.target.value] })}
        >
          {options.teams.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

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
