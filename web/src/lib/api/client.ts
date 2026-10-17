import type {
  Catalog,
  HistoricalExplorerQuery,
  HistoricalExplorerResult,
  LeaderboardQuery,
  LeaderboardResult,
  PlayerSummary,
} from "./types";

/**
 * Everything the WEB-M1 pages read. Pages talk to this interface only (through
 * `useBaseballClient`), so swapping the fixture adapter for the HTTP adapter changes no page
 * code. Methods reject with `BaseballApiError`.
 */
export interface BaseballClient {
  /** Where the data comes from. `mock` shows the sample-data notice. */
  readonly source: "mock" | "api";
  /** What this source can answer authoritatively; pages hide features it can't. */
  readonly capabilities: ClientCapabilities;
  getCatalog(options?: RequestOptions): Promise<Catalog>;
  searchPlayers(text: string, options?: RequestOptions & { limit?: number }): Promise<PlayerSummary[]>;
  getPlayer(id: string, options?: RequestOptions): Promise<PlayerSummary | null>;
  getHistoricalExplorer(query: HistoricalExplorerQuery, options?: RequestOptions): Promise<HistoricalExplorerResult>;
  getLeaderboard(query: LeaderboardQuery, options?: RequestOptions): Promise<LeaderboardResult>;
}

export interface ClientCapabilities {
  /**
   * Ranking one player's seasons (Historical Explorer "One player"). The real API doesn't
   * support it yet (handoff R8), so it is hidden there rather than computed in the browser.
   */
  playerSeasonRanking: boolean;
}

export interface RequestOptions {
  signal?: AbortSignal;
}
