"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import type { BaseballClient } from "./client";
import { createHttpClient } from "./http/httpClient";

/**
 * Picks the data source once per browser session.
 *
 * - Default: the real Python API, through the same-origin proxy (/api/baseball).
 * - Sample fixtures only when NEXT_PUBLIC_BASEBALL_DATA_SOURCE=mock *and* this isn't a
 *   production build. NODE_ENV is inlined at build time, so production bundles don't contain
 *   the fixtures at all; next.config.ts also refuses `next build` with mock set.
 */
export function createDefaultClient(): BaseballClient {
  if (process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_BASEBALL_DATA_SOURCE === "mock") {
    return lazySampleClient();
  }
  return createHttpClient();
}

/**
 * The fixture adapter, loaded on demand through the `baseball-sample-data` alias. Production
 * builds alias it to a data-free stub (next.config.ts), so no fixture is ever emitted there.
 */
function lazySampleClient(): BaseballClient {
  const loaded = import("baseball-sample-data").then((m) => m.createMockClient());
  return {
    source: "mock",
    capabilities: { playerSeasonRanking: true },
    getCatalog: async (options) => (await loaded).getCatalog(options),
    searchPlayers: async (text, options) => (await loaded).searchPlayers(text, options),
    getPlayer: async (id, options) => (await loaded).getPlayer(id, options),
    getHistoricalExplorer: async (query, options) => (await loaded).getHistoricalExplorer(query, options),
    getLeaderboard: async (query, options) => (await loaded).getLeaderboard(query, options),
  };
}

const BaseballClientContext = createContext<BaseballClient | null>(null);

export function BaseballClientProvider({ client, children }: { client?: BaseballClient; children: ReactNode }) {
  const [value] = useState<BaseballClient>(() => client ?? createDefaultClient());
  return <BaseballClientContext.Provider value={value}>{children}</BaseballClientContext.Provider>;
}

export function useBaseballClient(): BaseballClient {
  const client = useContext(BaseballClientContext);
  if (!client) throw new Error("useBaseballClient must be used inside <BaseballClientProvider>.");
  return client;
}
