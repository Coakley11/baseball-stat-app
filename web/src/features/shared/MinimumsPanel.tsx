"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/primitives";
import type { Catalog, Minimums } from "@/lib/api";

import { metricOf, minimumUrlParams } from "./params";
import shared from "./questions.module.css";

function toNumber(text: string): number | null {
  const t = text.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : Number.NaN;
}

/**
 * Minimums the user sets: at-bats, and any stat the catalog lists. Left empty, at-bats use the
 * API's automatic qualified minimum (0 means no minimum at all). The API applies every minimum;
 * this only collects the numbers and puts them in the URL when the user presses Apply.
 */
export function MinimumsPanel({
  catalog,
  columns,
  minimums,
  status,
  onApply,
}: {
  catalog: Catalog;
  /** Stats that accept a minimum (the catalog's list). */
  columns: string[];
  /** What the URL currently holds. */
  minimums: Minimums;
  /** The API's own line about the minimum in force, when it has one. */
  status: string | null;
  onApply: (changes: Record<string, string | null>) => void;
}) {
  const id = useId();
  const [ab, setAb] = useState(minimums.ab === null ? "" : String(minimums.ab));
  const [stats, setStats] = useState<Record<string, string>>(() =>
    Object.fromEntries(columns.map((c) => [c, minimums.stats[c] === undefined ? "" : String(minimums.stats[c])])),
  );

  const abValue = toNumber(ab);
  const statValues = columns.map((c) => [c, toNumber(stats[c] ?? "")] as const);
  const valid = !Number.isNaN(abValue) && (abValue === null || Number.isInteger(abValue)) && statValues.every(([, v]) => !Number.isNaN(v));
  const next: Minimums = {
    ab: abValue === null || Number.isNaN(abValue) ? null : abValue,
    stats: Object.fromEntries(statValues.flatMap(([c, v]) => (v === null || Number.isNaN(v) ? [] : [[c, v]]))),
  };
  const changed = JSON.stringify(minimumUrlParams(next)) !== JSON.stringify(minimumUrlParams(minimums));
  const active = minimums.ab !== null || Object.keys(minimums.stats).length > 0;

  return (
    <div>
      <h3 className={shared.subheading}>Minimums</h3>
      <p className={shared.note} style={{ marginBottom: "var(--space-3)" }}>
        Only seasons (or players) that reach the minimums you set are ranked. The Python app applies them.
      </p>
      {status && <p style={{ marginBottom: "var(--space-3)", fontWeight: 600 }}>{status}</p>}
      <div className={shared.weightGrid}>
        <div className={shared.weightField}>
          <label className={shared.label} htmlFor={`${id}-ab`}>
            At-bats
          </label>
          <input
            id={`${id}-ab`}
            className={shared.input}
            type="number"
            inputMode="numeric"
            min={0}
            step={1}
            aria-label="Minimum at-bats"
            placeholder="Automatic"
            value={ab}
            onChange={(e) => setAb(e.target.value)}
          />
        </div>
        {columns.map((stat) => (
          <div key={stat} className={shared.weightField}>
            <label className={shared.label} htmlFor={`${id}-${stat}`}>
              {metricOf(catalog, stat)?.label ?? stat}
            </label>
            <input
              id={`${id}-${stat}`}
              className={shared.input}
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              aria-label={`Minimum ${metricOf(catalog, stat)?.label ?? stat}`}
              placeholder="None"
              value={stats[stat] ?? ""}
              onChange={(e) => setStats((s) => ({ ...s, [stat]: e.target.value }))}
            />
          </div>
        ))}
      </div>
      <p className={shared.note} style={{ marginTop: "var(--space-2)" }}>
        Leave at-bats empty for the automatic qualified minimum; enter 0 for no minimum.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)", marginTop: "var(--space-3)", alignItems: "center" }}>
        <Button variant="primary" disabled={!valid || !changed} onClick={() => onApply(minimumUrlParams(next))}>
          Apply minimums
        </Button>
        <Button
          variant="ghost"
          disabled={!active && ab === "" && Object.values(stats).every((v) => v === "")}
          onClick={() => {
            setAb("");
            setStats(Object.fromEntries(columns.map((c) => [c, ""])));
            onApply(minimumUrlParams({ ab: null, stats: {} }));
          }}
        >
          Reset minimums
        </Button>
        {!valid && <span className={shared.note}>Use whole at-bats and numbers of zero or more.</span>}
      </div>
    </div>
  );
}
