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
  /**
   * Link to the API's CSV export of every ranked row for this question (the file is named by the
   * API's Content-Disposition). `null` when the source has no export.
   */
  historicalExportUrl(query: HistoricalExplorerQuery): string | null;
  /** As above for Leaderboards (the Top N in `query.limit`). */
  leaderboardExportUrl(query: LeaderboardQuery): string | null;
}

export interface ClientCapabilities {
  /**
   * Ranking one player's seasons (Historical Explorer "One player"), with the player's
   * below-minimum seasons marked. Sources that can't do it hide the view; the browser never
   * computes it.
   */
  playerSeasonRanking: boolean;
  /** Downloadable CSV exports (built by the Python API). */
  csvExport: boolean;
  /** Later pages of a ranked table (`offset`) and Historical Explorer's filters. */
  paging: boolean;
}

export interface RequestOptions {
  signal?: AbortSignal;
}
