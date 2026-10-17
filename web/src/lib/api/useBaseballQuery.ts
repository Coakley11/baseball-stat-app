"use client";

import { useCallback, useEffect, useState } from "react";

import type { BaseballClient, RequestOptions } from "./client";
import { BaseballApiError, toBaseballApiError } from "./errors";
import { useBaseballClient } from "./provider";

export type QueryState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; error: BaseballApiError; retry: () => void }
  | { status: "success"; data: T };

type Settled<T> = { key: string; attempt: number } & ({ ok: true; data: T } | { ok: false; error: BaseballApiError });

/**
 * Runs one client call per distinct `key` and returns its state. `key` must change whenever
 * the question changes (callers use the serialised query); `null` means "nothing to ask yet".
 * Earlier requests are aborted, so a slow answer never overwrites a newer one.
 */
export function useBaseballQuery<T>(
  key: string | null,
  run: (client: BaseballClient, options: RequestOptions) => Promise<T>,
): QueryState<T> {
  const client = useBaseballClient();
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    run(client, { signal: controller.signal }).then(
      (data) => {
        if (!controller.signal.aborted) setSettled({ key, attempt, ok: true, data });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setSettled({ key, attempt, ok: false, error: toBaseballApiError(error) });
      },
    );
    return () => controller.abort();
    // `run` is re-created every render; `key` is the identity of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, key, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  if (key === null) return { status: "idle" };
  if (!settled || settled.key !== key || settled.attempt !== attempt) return { status: "loading" };
  return settled.ok ? { status: "success", data: settled.data } : { status: "error", error: settled.error, retry };
}
