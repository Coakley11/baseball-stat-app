/**
 * SAMPLE DATA: canned Leaderboards answers for 2020–2025. Totals, ranks, qualification and
 * sentences are written out as the Python API would return them; nothing is summed or ranked
 * in TypeScript. Illustrative numbers only. Corey Seager's walks are deliberately missing.
 */
import type { LeaderboardEntry, LeaderboardResult, QualificationInfo, StatLine } from "../../types";
import { CATALOG, metricDefinition } from "./catalog";
import { playerRef } from "./players";
import { leaderboardTable } from "./table";

const RANGE = CATALOG.leaderboards.yearRange;
type Seed = Omit<LeaderboardResult, "table">;

const finishAll = (seeds: Record<string, Seed>): Record<string, LeaderboardResult> =>
  Object.fromEntries(Object.entries(seeds).map(([k, v]) => [k, { ...v, table: leaderboardTable(CATALOG.leaderboards.columns, v.entries) }]));

type Totals = [seasons: number, AB: number, H: number, HR: number, RBI: number, SB: number, BB: number | null,
  BA: number, OBP: number, SLG: number, OPS: number, score: number];

// 2020–2025 totals; `score` is the default weighting (HR + RBI + SB), as the API reports it.
const TOTALS: Record<string, Totals> = {
  ramirjo01: [6, 3240, 897, 182, 581, 191, 380, 0.277, 0.353, 0.510, 0.863, 954],
  ohtansh01: [6, 3041, 852, 240, 541, 157, 452, 0.280, 0.378, 0.584, 0.962, 938],
  judgeaa01: [6, 2689, 818, 258, 574, 47, 541, 0.304, 0.425, 0.633, 1.058, 879],
  alonspe01: [6, 3168, 790, 211, 604, 13, 341, 0.249, 0.334, 0.502, 0.836, 828],
  olsonma02: [6, 3237, 852, 199, 571, 11, 444, 0.263, 0.357, 0.508, 0.865, 781],
  schwaky01: [6, 3000, 693, 230, 521, 26, 541, 0.231, 0.353, 0.506, 0.859, 777],
  sotoju01: [6, 2870, 815, 188, 515, 64, 715, 0.284, 0.425, 0.530, 0.955, 767],
  guerrvl02: [6, 3296, 942, 168, 521, 26, 404, 0.286, 0.366, 0.497, 0.863, 715],
  freemfr01: [6, 3370, 1012, 132, 534, 46, 450, 0.300, 0.388, 0.502, 0.890, 712],
  harpebr03: [6, 2700, 770, 150, 470, 60, 480, 0.285, 0.395, 0.540, 0.935, 680],
  rileyau01: [6, 2900, 800, 171, 480, 9, 230, 0.276, 0.337, 0.502, 0.839, 660],
  wittbo02: [4, 2560, 768, 107, 378, 153, 160, 0.300, 0.350, 0.512, 0.862, 638],
  acunaro01: [6, 2052, 590, 116, 302, 199, 297, 0.288, 0.382, 0.530, 0.912, 617],
  tatisfe02: [6, 2380, 650, 140, 360, 110, 230, 0.273, 0.345, 0.530, 0.875, 610],
  seageco01: [6, 2400, 700, 130, 370, 10, null, 0.292, 0.365, 0.515, 0.880, 510],
};

function entries(order: string[]): LeaderboardEntry[] {
  return order.map((id, i) => {
    const t = TOTALS[id];
    if (!t) throw new Error(`Fixture totals missing: ${id}`);
    const [, AB, H, HR, RBI, SB, BB, BA, OBP, SLG, OPS, score] = t;
    const stats: StatLine = { AB, H, HR, RBI, SB, BB, BA, OBP, SLG, OPS, score };
    return { rank: i + 1, player: playerRef(id), stats };
  });
}

const COUNTING: QualificationInfo = { kind: "not_applicable", summary: null, explanation: null, minAtBats: null, scope: "span" };

const LEADERBOARD_SEEDS: Record<string, Seed> = {
  score: {
    query: { yearRange: RANGE, metric: "score" },
    metric: metricDefinition("score"),
    qualification: COUNTING,
    answer: {
      headline: "José Ramírez leads 2020–2025 in weighted score: 954",
      detail: "Ahead of Shohei Ohtani (938) and Aaron Judge (879). Score adds up HR + RBI + SB over 2020–2025.",
      context: "Ranked by weighted score",
    },
    entries: entries([
      "ramirjo01", "ohtansh01", "judgeaa01", "alonspe01", "olsonma02", "schwaky01", "sotoju01", "guerrvl02",
      "freemfr01", "harpebr03", "rileyau01", "wittbo02", "acunaro01", "tatisfe02", "seageco01",
    ]),
    totalRanked: 1604,
    score: {
      weights: [{ metric: "HR", weight: 1 }, { metric: "RBI", weight: 1 }, { metric: "SB", weight: 1 }],
    },
  },
  HR: {
    query: { yearRange: RANGE, metric: "HR" },
    metric: metricDefinition("HR"),
    qualification: COUNTING,
    answer: {
      headline: "Aaron Judge leads 2020–2025 in home runs: 258",
      detail: "Ahead of Shohei Ohtani (240) and Kyle Schwarber (230). Total home runs over 2020–2025.",
      context: "Ranked by home runs",
    },
    entries: entries([
      "judgeaa01", "ohtansh01", "schwaky01", "alonspe01", "olsonma02", "sotoju01", "ramirjo01", "rileyau01",
      "guerrvl02", "harpebr03", "tatisfe02", "freemfr01", "seageco01", "acunaro01", "wittbo02",
    ]),
    totalRanked: 1604,
    score: null,
  },
  // Ronald Acuña Jr. (2,052 AB) falls under the span minimum, so he is not ranked here.
  OPS: {
    query: { yearRange: RANGE, metric: "OPS" },
    metric: metricDefinition("OPS"),
    qualification: {
      kind: "qualified",
      summary: "Qualified hitters · at least 2,349 AB over 2020–2025",
      explanation: null,
      minAtBats: 2349,
      scope: "span",
    },
    answer: {
      headline: "Aaron Judge leads 2020–2025 in OPS: 1.058",
      detail: "Ahead of Shohei Ohtani (.962) and Juan Soto (.955). OPS from each player's combined totals over 2020–2025.",
      context: "Ranked by OPS",
    },
    entries: entries([
      "judgeaa01", "ohtansh01", "sotoju01", "harpebr03", "freemfr01", "seageco01", "tatisfe02", "olsonma02",
      "ramirjo01", "guerrvl02", "wittbo02", "schwaky01", "rileyau01", "alonspe01",
    ]),
    totalRanked: 142,
    score: null,
  },
};

// 2010–2025 home runs (the Historical Explorer default range). Only HR totals are in the sample,
// so this answer's table has a single stat column (columns are always the API's choice).
const HR_2010: [id: string, seasons: number, HR: number][] = [
  ["stantmi03", 16, 429], ["troutmi01", 15, 404], ["freemfr01", 16, 367], ["harpebr03", 14, 363],
  ["schwaky01", 11, 340], ["judgeaa01", 10, 315], ["cabremi01", 14, 300], ["davisch02", 11, 290],
  ["olsonma02", 10, 280], ["ohtansh01", 8, 280],
];

const LONG_RANGE_SEEDS: Record<string, Seed> = {
  HR: {
    query: { yearRange: { start: 2010, end: 2025 }, metric: "HR" },
    metric: metricDefinition("HR"),
    qualification: COUNTING,
    answer: {
      headline: "Giancarlo Stanton leads 2010–2025 in home runs: 429",
      detail: "Ahead of Mike Trout (404) and Freddie Freeman (367). Total home runs over 2010–2025.",
      context: "Ranked by home runs",
    },
    entries: HR_2010.map(([id, , HR], i) => ({ rank: i + 1, player: playerRef(id), stats: { HR } })),
    totalRanked: 4213,
    score: null,
  },
};

export const LEADERBOARD_SCENARIOS = finishAll(LEADERBOARD_SEEDS);
const LONG_RANGE_SCENARIOS = finishAll(LONG_RANGE_SEEDS);

const BY_RANGE: Record<string, Record<string, LeaderboardResult>> = {
  [`${RANGE.start}-${RANGE.end}`]: LEADERBOARD_SCENARIOS,
  "2010-2025": LONG_RANGE_SCENARIOS,
};

/** The canned answer for a question, if the sample data has one. */
export function findLeaderboardScenario(range: { start: number; end: number }, metric: string): LeaderboardResult | undefined {
  return BY_RANGE[`${range.start}-${range.end}`]?.[metric];
}
