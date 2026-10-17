"use client";

import { useId, useState, type FormEvent, type ReactNode } from "react";

import type { MetricDefinition, YearRange } from "@/lib/api";

import { metricOptionLabel } from "./params";
import styles from "./questions.module.css";

/** The question row at the top of an answer-first page. Wraps on phones; never scrolls sideways. */
export function QuestionBar({ label, children }: { label: string; children: ReactNode }) {
  return (
    <form
      className={styles.questionBar}
      aria-label={label}
      onSubmit={(event: FormEvent) => event.preventDefault()}
    >
      {children}
    </form>
  );
}

/**
 * From/To season inputs. Commits on blur or Enter (not on every keystroke), so typing "2015"
 * doesn't ask four questions. Remount with `key` to reset to a new value from the URL.
 */
export function YearRangeFields({
  value,
  bounds,
  onCommit,
}: {
  /** As written in the URL (may be invalid, so the user can see and fix it). */
  value: { start: string; end: string };
  bounds: YearRange;
  onCommit: (range: { start: string; end: string }) => void;
}) {
  const id = useId();
  const [start, setStart] = useState(value.start);
  const [end, setEnd] = useState(value.end);

  const commit = () => {
    if (start !== value.start || end !== value.end) onCommit({ start: start.trim(), end: end.trim() });
  };

  return (
    <fieldset className={styles.yearFields}>
      <legend className={styles.label}>
        Seasons{" "}
        <span id={`${id}-hint`} className={styles.hint}>
          {bounds.start}–{bounds.end}
        </span>
      </legend>
      <div className={styles.yearInputs}>
        <label className="sr-only" htmlFor={`${id}-from`}>
          From season
        </label>
        <input
          id={`${id}-from`}
          className={styles.input}
          inputMode="numeric"
          pattern="[0-9]*"
          maxLength={4}
          value={start}
          onChange={(e) => setStart(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()}
          aria-describedby={`${id}-hint`}
        />
        <span aria-hidden="true" className={styles.yearDash}>
          –
        </span>
        <label className="sr-only" htmlFor={`${id}-to`}>
          To season
        </label>
        <input
          id={`${id}-to`}
          className={styles.input}
          inputMode="numeric"
          pattern="[0-9]*"
          maxLength={4}
          value={end}
          onChange={(e) => setEnd(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && commit()}
          aria-describedby={`${id}-hint`}
        />
      </div>
    </fieldset>
  );
}

export function MetricSelect({
  label,
  metrics,
  value,
  onChange,
}: {
  label: string;
  metrics: MetricDefinition[];
  /** `null` when the URL asked for a metric that doesn't exist. */
  value: string | null;
  onChange: (metric: string) => void;
}) {
  const id = useId();
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <select id={id} className={styles.select} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        {value === null && (
          <option value="" disabled>
            Choose a stat
          </option>
        )}
        {metrics.map((m) => (
          <option key={m.key} value={m.key}>
            {metricOptionLabel(m)}
          </option>
        ))}
      </select>
    </div>
  );
}
