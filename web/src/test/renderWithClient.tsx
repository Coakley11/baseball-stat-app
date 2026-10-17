import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { BaseballClientProvider, type BaseballClient } from "@/lib/api";
import { createMockClient, type MockScenario } from "@/lib/api/mock/mockClient";

/**
 * Renders inside a provider. Default: the fixture adapter with no latency (UI behaviour tests).
 * Pass `client` (e.g. createRecordedClient()) to render real recorded API data.
 */
export function renderWithClient(ui: ReactElement, options: { scenario?: MockScenario | (() => MockScenario); client?: BaseballClient } = {}) {
  const client = options.client ?? createMockClient({ latencyMs: 0, scenario: options.scenario ?? "normal" });
  return { client, ...render(<BaseballClientProvider client={client}>{ui}</BaseballClientProvider>) };
}
