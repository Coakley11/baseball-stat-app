// Records real Baseball API responses for deterministic frontend tests.
//
//   BASEBALL_API_COMMIT=<sha> [BASEBALL_API_ORIGIN=http://127.0.0.1:8601] node scripts/record-api-responses.mjs
//
// Writes src/test/recorded/baseball-api.json: { api_commit, recorded_at, responses: { "<path?query>": {status, ...} } }.
// Keys are the exact requests the HTTP adapter sends (lib/api/http), so tests can replay them.
// JSON responses keep their body; CSV responses keep their exact text plus content-type and
// content-disposition. Every value in the file comes from the API over the real Lahman data;
// nothing is edited.
import { writeFile } from "node:fs/promises";

const origin = (process.env.BASEBALL_API_ORIGIN ?? "http://127.0.0.1:8601").replace(/\/+$/, "");
const commit = process.env.BASEBALL_API_COMMIT;
if (!commit) {
  console.error("Set BASEBALL_API_COMMIT to the API commit being recorded (e.g. 5ca7a26).");
  process.exit(1);
}

/** "path?k=v&…" exactly as the adapter builds it (URLSearchParams encoding, same key order). */
const q = (path, params) => `${path}?${new URLSearchParams(params).toString()}`;
const HE = { start: 2010, end: 2025, metric: "HR", order: "desc" };

const REQUESTS = [
  "health",
  "catalog",
  // Historical Explorer: start, end, metric, order, [filters], [player_id], limit, [offset], [include_below_minimum]
  q("seasons", { ...HE, limit: 25 }),
  q("seasons", { ...HE, metric: "OPS", limit: 25 }),
  q("seasons", { ...HE, start: 2020, limit: 25 }),
  q("seasons", { ...HE, limit: 25, offset: 25 }),
  q("seasons", { ...HE, bats: "L", positions: "SS", position_source: "season", limit: 25 }),
  q("seasons", { ...HE, metric: "OPS", player_id: "judgeaa01", limit: 25, include_below_minimum: true }),
  q("seasons", { ...HE, player_id: "guerrvl02", limit: 25, include_below_minimum: true }),
  // Leaderboards: start, end, metric, [weights], limit
  q("leaderboards", { start: 2020, end: 2025, metric: "score", limit: 25 }),
  q("leaderboards", { start: 2020, end: 2025, metric: "score", limit: 10 }),
  q("leaderboards", { start: 2020, end: 2025, metric: "score", weights: "HR:2,RBI:1", limit: 25 }),
  q("leaderboards", { start: 2020, end: 2025, metric: "OPS", limit: 25 }),
  q("leaderboards", { start: 2020, end: 2025, metric: "HR", limit: 25 }),
  q("leaderboards", { start: 2010, end: 2025, metric: "HR", limit: 25 }),
  // Players
  "players/search?q=judge&limit=8",
  "players/judgeaa01",
  // Defaults the API applies when nothing is sent
  "seasons",
  "leaderboards",
  // Real errors and a real empty result (min_HR isn't sent by the adapter; tests substitute it)
  q("seasons", { ...HE, metric: "WAR", limit: 25 }),
  q("leaderboards", { start: 2030, end: 2031, metric: "HR", limit: 25 }),
  "players/nobody99",
  q("seasons", { ...HE, limit: 25, min_HR: 100 }),
  // CSV exports (the API builds the file and names it)
  q("seasons", { ...HE, start: 2025, bats: "B", positions: "C", position_source: "season", format: "csv" }),
  q("leaderboards", { start: 2020, end: 2025, metric: "OPS", limit: 25, format: "csv" }),
];

const responses = {};
for (const request of REQUESTS) {
  const res = await fetch(`${origin}/api/v1/${request}`);
  const type = res.headers.get("content-type") ?? "";
  if (type.startsWith("text/csv")) {
    responses[request] = {
      status: res.status,
      contentType: type,
      contentDisposition: res.headers.get("content-disposition"),
      text: await res.text(),
    };
  } else {
    responses[request] = { status: res.status, body: await res.json() };
  }
  console.log(`${res.status} ${request}`);
}

await writeFile(
  new URL("../src/test/recorded/baseball-api.json", import.meta.url),
  `${JSON.stringify({ api_commit: commit, recorded_at: new Date().toISOString().slice(0, 10), responses }, null, 1)}\n`,
);
