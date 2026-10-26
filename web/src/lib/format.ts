/**
 * Display formatting only. These turn an API value into text; they never derive a statistic.
 * Matches the Streamlit pages: rates to three places without the leading zero (".311"),
 * counts with thousands separators, scores to one decimal at most.
 */
import type { MetricDefinition, StatFormat, YearRange } from "@/lib/api";

const COUNT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const SCORE = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export const MISSING = "—";

export function formatStat(value: number | null | undefined, format: StatFormat): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return MISSING;
  switch (format) {
    case "rate": {
      const text = value.toFixed(3);
      return text.startsWith("0.") ? text.slice(1) : text;
    }
    case "score":
      return SCORE.format(value);
    case "year":
      return String(Math.trunc(value));
    case "count":
      return COUNT.format(value);
  }
}

export function formatMetric(value: number | null | undefined, metric: Pick<MetricDefinition, "format">): string {
  return formatStat(value, metric.format);
}

export function formatCount(value: number): string {
  return COUNT.format(value);
}

export function formatYearRange(range: YearRange): string {
  return range.start === range.end ? String(range.start) : `${range.start}–${range.end}`;
}

/** "1st", "2nd", "3rd", "11th". */
export function ordinal(n: number): string {
  const tens = n % 100;
  const suffix = tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}
