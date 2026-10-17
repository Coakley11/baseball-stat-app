/**
 * SAMPLE DATA: canned Historical Explorer answers. Rank order, totals, qualification and the
 * answer sentences are written out here exactly as the Python API would return them; the mock
 * adapter only looks them up. Any other question is "not in the sample data".
 */
import type { HistoricalExplorerResult, QualificationInfo } from "../../types";
import { CATALOG, metricDefinition } from "./catalog";
import { PLAYERS } from "./players";
import { seasonRows } from "./seasons";

const RANGE = CATALOG.historical.yearRange;
const COLUMNS = ["AB", "H", "HR", "RBI", "SB", "BB", "BA", "OBP", "SLG", "OPS"];

const COUNTING: QualificationInfo = { kind: "not_applicable", summary: "", minAtBats: null, scope: "season" };
const QUALIFIED_SEASON: QualificationInfo = {
  kind: "qualified",
  summary: "Qualified seasons · at least 437 AB in the season",
  minAtBats: 437,
  scope: "season",
};

function player(id: string) {
  return PLAYERS.find((p) => p.id === id) ?? null;
}

const HR_ALL = seasonRows([
  "judgeaa01-2022", "raleica01-2025", "stantmi03-2017", "judgeaa01-2024", "schwaky01-2025",
  "ohtansh01-2025", "bautijo02-2010", "ohtansh01-2024", "olsonma02-2023", "alonspe01-2019",
  "davisch02-2013", "judgeaa01-2025", "judgeaa01-2017", "guerrvl02-2021", "perezsa02-2021",
]);

// Juan Soto's 2020 (1.185 OPS in 154 AB) is excluded by the per-season minimum, as in the app.
const OPS_ALL = seasonRows([
  "judgeaa01-2024", "judgeaa01-2025", "judgeaa01-2022", "harpebr03-2015", "yelicch01-2019",
  "troutmi01-2018", "cabremi01-2013", "judgeaa01-2017", "ohtansh01-2024", "vottojo01-2010",
  "ohtansh01-2025", "stantmi03-2017", "davisch02-2013", "guerrvl02-2021",
]);

const JUDGE_YEARS = ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025"].map((y) => `judgeaa01-${y}`);
const JUDGE_SHORT = ["judgeaa01-2016", "judgeaa01-2018", "judgeaa01-2019", "judgeaa01-2020", "judgeaa01-2023"];
const VLAD_YEARS = ["2019", "2020", "2021", "2022", "2023", "2024", "2025"].map((y) => `guerrvl02-${y}`);

export const HISTORICAL_SCENARIOS: Record<string, HistoricalExplorerResult> = {
  "all|HR|desc": {
    query: { yearRange: RANGE, metric: "HR", order: "desc", playerId: null },
    metric: metricDefinition("HR"),
    qualification: COUNTING,
    answer: {
      headline: "Aaron Judge, 2022: 62 home runs",
      detail: "Aaron Judge's 62 home runs in 2022 are the most among the 9,718 seasons shown (2010–2025). Next: Cal Raleigh (2025), 60.",
      context: "2022 · NYY · RF",
    },
    topSeasonId: "judgeaa01-2022",
    keyMetrics: ["HR", "RBI", "BA", "OPS"],
    columns: COLUMNS,
    seasons: HR_ALL,
    totalCount: 9718,
    player: null,
    chart: { kind: "ranking", title: "Top 10 seasons by home runs", seasonIds: HR_ALL.slice(0, 10).map((s) => s.id) },
  },
  "all|OPS|desc": {
    query: { yearRange: RANGE, metric: "OPS", order: "desc", playerId: null },
    metric: metricDefinition("OPS"),
    qualification: QUALIFIED_SEASON,
    answer: {
      headline: "Aaron Judge, 2024: 1.159 OPS",
      detail: "Aaron Judge's 1.159 OPS in 2024 is the highest among the 2,412 seasons shown (2010–2025). Next: Aaron Judge (2025), 1.145.",
      context: "2024 · NYY · CF",
    },
    topSeasonId: "judgeaa01-2024",
    keyMetrics: ["OPS", "HR", "RBI", "BA"],
    columns: COLUMNS,
    seasons: OPS_ALL,
    totalCount: 2412,
    player: null,
    chart: { kind: "ranking", title: "Top 10 seasons by OPS", seasonIds: OPS_ALL.slice(0, 10).map((s) => s.id) },
  },
  "judgeaa01|HR|desc": {
    query: { yearRange: RANGE, metric: "HR", order: "desc", playerId: "judgeaa01" },
    metric: metricDefinition("HR"),
    qualification: COUNTING,
    answer: {
      headline: "Aaron Judge, 2022: 62 home runs",
      detail: "Aaron Judge's 62 home runs in 2022 are the most among the 10 seasons shown (2010–2025). Next: Aaron Judge (2024), 58.",
      context: "2022 · NYY · RF",
    },
    topSeasonId: "judgeaa01-2022",
    keyMetrics: ["HR", "RBI", "BA", "OPS"],
    columns: COLUMNS,
    seasons: seasonRows([
      "judgeaa01-2022", "judgeaa01-2024", "judgeaa01-2025", "judgeaa01-2017", "judgeaa01-2021",
      "judgeaa01-2023", "judgeaa01-2018", "judgeaa01-2019", "judgeaa01-2020", "judgeaa01-2016",
    ]),
    totalCount: 10,
    player: player("judgeaa01"),
    chart: { kind: "timeline", title: "Aaron Judge · home runs by season", seasonIds: JUDGE_YEARS },
  },
  "judgeaa01|OPS|desc": {
    query: { yearRange: RANGE, metric: "OPS", order: "desc", playerId: "judgeaa01" },
    metric: metricDefinition("OPS"),
    qualification: QUALIFIED_SEASON,
    answer: {
      headline: "Aaron Judge, 2024: 1.159 OPS",
      detail: "Aaron Judge's 1.159 OPS in 2024 is the highest among his 5 qualified seasons (2010–2025). Next: Aaron Judge (2025), 1.145.",
      context: "2024 · NYY · CF",
    },
    topSeasonId: "judgeaa01-2024",
    keyMetrics: ["OPS", "HR", "RBI", "BA"],
    columns: COLUMNS,
    seasons: seasonRows([
      "judgeaa01-2024", "judgeaa01-2025", "judgeaa01-2022", "judgeaa01-2017", "judgeaa01-2021",
      "judgeaa01-2023", "judgeaa01-2019", "judgeaa01-2018", "judgeaa01-2020", "judgeaa01-2016",
    ], JUDGE_SHORT),
    totalCount: 10,
    player: player("judgeaa01"),
    chart: { kind: "timeline", title: "Aaron Judge · OPS by season", seasonIds: JUDGE_YEARS },
  },
  "guerrvl02|HR|desc": {
    query: { yearRange: RANGE, metric: "HR", order: "desc", playerId: "guerrvl02" },
    metric: metricDefinition("HR"),
    qualification: COUNTING,
    answer: {
      headline: "Vladimir Guerrero Jr., 2021: 48 home runs",
      detail: "Vladimir Guerrero Jr.'s 48 home runs in 2021 are the most among the 7 seasons shown (2010–2025). Next: Vladimir Guerrero Jr. (2022), 32.",
      context: "2021 · TOR · 1B",
    },
    topSeasonId: "guerrvl02-2021",
    keyMetrics: ["HR", "RBI", "BA", "OPS"],
    columns: COLUMNS,
    seasons: seasonRows([
      "guerrvl02-2021", "guerrvl02-2022", "guerrvl02-2024", "guerrvl02-2023", "guerrvl02-2025",
      "guerrvl02-2019", "guerrvl02-2020",
    ]),
    totalCount: 7,
    player: player("guerrvl02"),
    chart: { kind: "timeline", title: "Vladimir Guerrero Jr. · home runs by season", seasonIds: VLAD_YEARS },
  },
  "guerrvl02|OPS|desc": {
    query: { yearRange: RANGE, metric: "OPS", order: "desc", playerId: "guerrvl02" },
    metric: metricDefinition("OPS"),
    qualification: QUALIFIED_SEASON,
    answer: {
      headline: "Vladimir Guerrero Jr., 2021: 1.002 OPS",
      detail: "Vladimir Guerrero Jr.'s 1.002 OPS in 2021 is the highest among his 6 qualified seasons (2010–2025). Next: Vladimir Guerrero Jr. (2024), .940.",
      context: "2021 · TOR · 1B",
    },
    topSeasonId: "guerrvl02-2021",
    keyMetrics: ["OPS", "HR", "RBI", "BA"],
    columns: COLUMNS,
    seasons: seasonRows([
      "guerrvl02-2021", "guerrvl02-2024", "guerrvl02-2025", "guerrvl02-2022", "guerrvl02-2023",
      "guerrvl02-2019", "guerrvl02-2020",
    ], ["guerrvl02-2020"]),
    totalCount: 7,
    player: player("guerrvl02"),
    chart: { kind: "timeline", title: "Vladimir Guerrero Jr. · OPS by season", seasonIds: VLAD_YEARS },
  },
};

/** Fixture lookup key. Only the default year range is covered. */
export function historicalScenarioKey(playerId: string | null, metric: string, order: string): string {
  return `${playerId ?? "all"}|${metric}|${order}`;
}
