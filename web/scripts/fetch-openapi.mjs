// Refreshes the pinned API schema (openapi/baseball-api.json) from a running Baseball API.
//
//   BASEBALL_API_COMMIT=<sha> [BASEBALL_API_ORIGIN=http://127.0.0.1:8601] npm run api:schema
//   npm run api:types        # then regenerate src/lib/api/generated/baseball-api.ts
//
// The commit is required because the API's /health "build" field reports the repository's
// deploy marker, not necessarily the commit that is actually running.
import { writeFile } from "node:fs/promises";

const origin = (process.env.BASEBALL_API_ORIGIN ?? "http://127.0.0.1:8601").replace(/\/+$/, "");
const commit = process.env.BASEBALL_API_COMMIT;
if (!commit) {
  console.error("Set BASEBALL_API_COMMIT to the API commit you are pinning (e.g. a9a80f7).");
  process.exit(1);
}

const response = await fetch(`${origin}/api/v1/openapi.json`);
if (!response.ok) {
  console.error(`GET ${origin}/api/v1/openapi.json -> ${response.status}`);
  process.exit(1);
}
const schema = await response.json();

await writeFile(new URL("../openapi/baseball-api.json", import.meta.url), `${JSON.stringify(schema, null, 2)}\n`);
await writeFile(
  new URL("../openapi/baseball-api.meta.json", import.meta.url),
  `${JSON.stringify({ api_commit: commit, api_version: schema.info?.version ?? null, fetched_at: new Date().toISOString().slice(0, 10) }, null, 2)}\n`,
);
console.log(`Pinned ${schema.info?.title} ${schema.info?.version} @ ${commit}: ${Object.keys(schema.paths ?? {}).length} paths.`);
