"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import type { BaseballClient } from "./client";
import { createMockClient } from "./mock/mockClient";

/**
 * Picks the data source once per browser session.
 *
 * NEXT_PUBLIC_BASEBALL_DATA_SOURCE:
 * - unset / "mock": the fixture adapter (the only one in WEB-M1).
 * - "api": reserved for the HTTP adapter that will call the Python API once its contracts
 *   are published. Until then it falls back to fixtures, so the sample-data notice stays on.
 */
export function createDefaultClient(): BaseballClient {
  return createMockClient();
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
