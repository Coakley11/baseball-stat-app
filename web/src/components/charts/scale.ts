/**
 * Axis helpers for the SVG charts: "nice" tick values and linear mapping. Geometry only; no
 * statistic is computed here.
 */

const NICE_STEPS = [1, 2, 2.5, 5, 10];

/** Evenly spaced round tick values covering [min, max], about `target` of them. */
export function niceTicks(min: number, max: number, target = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / Math.max(1, target);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = (NICE_STEPS.find((s) => s * magnitude >= raw) ?? 10) * magnitude;
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= end + step / 2; v += step) {
    ticks.push(Number(v.toFixed(10)));
  }
  return ticks;
}

export function linear(domain: [number, number], range: [number, number]): (value: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (value) => r0 + ((value - d0) / span) * (r1 - r0);
}
