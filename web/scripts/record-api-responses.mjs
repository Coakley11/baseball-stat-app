// Records real Baseball API responses for deterministic frontend tests.
//
//   BASEBALL_API_COMMIT=<sha> [BASEBALL_API_ORIGIN=http://127.0.0.1:8601] node scripts/record-api-responses.mjs
//
// Writes src/test/recorded/baseball-api.json: { api_commit, recorded_at, responses: { "<path?query>": {status, body} } }.
// Keys are the exact requests the HTTP adapter sends (lib/api/http), so tests can replay them.
// Every number in the file comes from the API over the real Lahman data; nothing is edited.
import { writeFile } from "node:fs/promises";

const origin = (process.env.BASEBALL_API_ORIGIN ?? "http://127.0.0.1:8601").replace(/\/+$/, "");
const commit = process.env.BASEBALL_API_COMMIT;
if (!commit) {
  console.error("Set BASEBALL_API_COMMIT to the API commit being recorded (e.g. a9a80f7).");
  process.exit(1);
}

const REQUESTS = [
  "health",
  // Historical Explorer (the adapter always sends start, end, metric, order, limit)
  "seasons?start=2010&end=2025&metric=HR&order=desc&limit=25",
  "seasons?start=2010&end=2025&metric=OPS&order=desc&limit=25",
  "seasons?start=2020&end=2025&metric=HR&order=desc&limit=25",
  // Leaderboards (start, end, metric, limit)
  "leaderboards?start=2020&end=2025&metric=score&limit=25",
  "leaderboards?start=2020&end=2025&metric=OPS&limit=25",
  "leaderboards?start=2020&end=2025&metric=HR&limit=25",
  "leaderboards?start=2010&end=2025&metric=HR&limit=25",
  // Player search and one player's summary
  "players/search?q=judge&limit=8",
  "players/judgeaa01/seasons",
  // Defaults the API applies when nothing is sent (checks the interim catalog)
  "seasons",
  "leaderboards",
  // Real errors and a real empty result
  "seasons?start=2010&end=2025&metric=WAR&order=desc&limit=25",
  "leaderboards?start=2030&end=2031&metric=HR&limit=25",
  "players/nobody99/seasons",
  "seasons?start=2010&end=2025&metric=HR&order=desc&limit=25&min_HR=100",
];

const responses = {};
for (const request of REQUESTS) {
  const res = await fetch(`${origin}/api/v1/${request}`);
  responses[request] = { status: res.status, body: await res.json() };
  console.log(`${res.status} ${request}`);
}

await writeFile(
  new URL("../src/test/recorded/baseball-api.json", import.meta.url),
  `${JSON.stringify({ api_commit: commit, recorded_at: new Date().toISOString().slice(0, 10), responses }, null, 1)}\n`,
);
