"use client";

import { useSearchParams } from "next/navigation";
import { useId } from "react";

import { RankingBars, type RankingBarItem } from "@/components/charts/RankingBars";
import { SeasonLineChart } from "@/components/charts/SeasonLineChart";
import {
  ActionRow,
  AnswerCard,
  Badge,
  Button,
  ButtonLink,
  DownloadLink,
  EmptyState,
  ErrorState,
  ExploreMore,
  LoadingState,
  MetricTiles,
} from "@/components/ui/primitives";
import {
  TABLE_PAGE_SIZE,
  useBaseballClient,
  useBaseballQuery,
  type Catalog,
  type HistoricalExplorerResult,
  type PlayerSeason,
  type QueryState,
} from "@/lib/api";
import { formatCount, formatStat, formatYearRange } from "@/lib/format";

import { metricOf, questionSummary, type ReadableParams } from "../shared/params";
import { ParamIssueView, QueryErrorView } from "../shared/QueryProblem";
import { MinimumsPanel } from "../shared/MinimumsPanel";
import { MetricSelect, QuestionBar, YearRangeFields } from "../shared/QuestionControls";
import shared from "../shared/questions.module.css";
import { ResultTableView } from "../shared/ResultTableView";
import { TablePager } from "../shared/TablePager";
import { useSearchParamUpdater } from "../shared/useSearchParamUpdater";
import styles from "./historical.module.css";
import { HistoricalFilterPanel } from "./HistoricalFilterPanel";
import { filterParams, HISTORICAL_PATH, hasFilters, historicalHref, readHistoricalParams, type HistoricalUrlState } from "./params";
import { PlayerPicker } from "./PlayerPicker";

/**
 * Question controls → answer card → default visual → next actions → Explore more.
 * The question is the URL; every number and sentence on screen comes from the client's result.
 */
export function HistoricalExplorer() {
  const searchParams = useSearchParams();
  const catalog = useBaseballQuery("catalog", (client, options) => client.getCatalog(options));

  if (catalog.status === "error") {
    return <QueryErrorView error={catalog.error} retry={catalog.retry} resetHref={HISTORICAL_PATH} />;
  }
  if (catalog.status !== "success") return <LoadingState label="Loading Historical Explorer" />;
  return <ExplorerWithCatalog catalog={catalog.data} params={searchParams} />;
}

function ExplorerWithCatalog({ catalog, params }: { catalog: Catalog; params: ReadableParams }) {
  const state = readHistoricalParams(params, catalog);
  const update = useSearchParamUpdater();
  const client = useBaseballClient();
  const { query } = state;
  // One-player ranking only where the data source supports it.
  const playerView = client.capabilities.playerSeasonRanking;
  const playerUnavailable = !playerView && state.scope === "player";
  const needsPlayer = playerView && state.scope === "player" && query.playerId === null;
  const blocked = state.issue !== null || needsPlayer || playerUnavailable;
  const result = useBaseballQuery(blocked ? null : JSON.stringify(query), (c, options) => c.getHistoricalExplorer(query, options));
  const metrics = catalog.historical.metrics.flatMap((k) => metricOf(catalog, k) ?? []);
  const playerName = result.status === "success" ? result.data.player?.name : undefined;
  // One player: a bound the user didn't choose is the player's career bound, which the API
  // reports back; until it has, the box is empty ("Career").
  const resolved = result.status === "success" ? result.data.query.yearRange : null;
  const shownRange = {
    start: state.rawRange.start || (resolved ? String(resolved.start) : ""),
    end: state.rawRange.end || (resolved ? String(resolved.end) : ""),
  };
  const summaryRange = shownRange.start === "" && shownRange.end === "" ? { start: "Career", end: "Career" } : shownRange;
  const summary = questionSummary(
    summaryRange,
    state.issue?.kind === "metric" ? undefined : metricOf(catalog, query.metric),
    state.scope === "all" ? "All players" : (playerName ?? "One player"),
    query.order === "asc" ? "Lowest first" : null,
    hasFilters(query.filters, query.minimums) ? "Filtered" : null,
  );

  return (
    <div className={shared.page}>
      <QuestionBar label="Your question" summary={summary} forceOpen={state.issue !== null || needsPlayer}>
        <YearRangeFields
          key={`${shownRange.start}-${shownRange.end}`}
          value={shownRange}
          bounds={catalog.years}
          placeholder={state.scope === "player" ? "Career" : undefined}
          onCommit={({ start, end }) => update({ from: start, to: end, page: null })}
        />
        <MetricSelect
          label="Rank by"
          metrics={metrics}
          value={state.issue?.kind === "metric" ? null : query.metric}
          onChange={(metric) => update({ metric, page: null })}
        />
        {playerView && (
          <ScopeChoice
            scope={state.scope}
            onChange={(scope) => update(scope === "all" ? { scope: null, player: null, page: null } : { scope: "player", page: null })}
          />
        )}
        {playerView && state.scope === "player" && (
          <PlayerPicker
            selectedId={query.playerId}
            onSelect={(player) => update({ player, scope: null, page: null })}
            onClear={() => update({ player: null, scope: "player", page: null })}
          />
        )}
      </QuestionBar>

      <section aria-label="Result" aria-busy={result.status === "loading"} className={shared.answerStack}>
        <ResultArea
          state={state}
          result={result}
          catalog={catalog}
          needsPlayer={needsPlayer}
          playerUnavailable={playerUnavailable}
          playerView={playerView}
        />
      </section>

      <ExploreMore description="Filters, every season returned, and the CSV download">
        {client.capabilities.paging ? (
          <HistoricalFilterPanel
            catalog={catalog}
            filters={query.filters ?? { bats: [], positionSource: "season", positions: [], teams: [], combine: false }}
            order={query.order}
            onChange={(next) => update({ ...filterParams(next), page: null })}
            onOrder={(order) => update({ order: order === catalog.historical.order ? null : order, page: null })}
          />
        ) : (
          <OrderOnly order={query.order} onOrder={(order) => update({ order: order === catalog.historical.order ? null : order, page: null })} />
        )}
        {client.capabilities.paging && (
          <MinimumsPanel
            key={JSON.stringify(query.minimums)}
            catalog={catalog}
            columns={catalog.historical.filters.minimumColumns}
            minimums={query.minimums ?? { ab: null, stats: {} }}
            status={result.status === "success" ? result.data.qualification.summary : null}
            onApply={(changes) => update({ ...changes, page: null })}
          />
        )}
        {result.status === "success" && result.data.seasons.length > 0 && (
          <SeasonsTable state={state} first={result.data} catalog={catalog} onPage={(page) => update({ page: page > 1 ? String(page) : null })} />
        )}
        {result.status === "success" && result.data.qualification.explanation && (
          <div>
            <h3 className={shared.subheading}>About the minimum</h3>
            <p>{result.data.qualification.explanation}</p>
          </div>
        )}
        <p className={shared.note}>
          Hall of Fame Case Mode, the relationship finder and the scatterplot are still in the current app.
        </p>
      </ExploreMore>
    </div>
  );
}

function ResultArea({
  state,
  result,
  catalog,
  needsPlayer,
  playerUnavailable,
  playerView,
}: {
  state: HistoricalUrlState;
  result: QueryState<HistoricalExplorerResult>;
  catalog: Catalog;
  needsPlayer: boolean;
  playerUnavailable: boolean;
  playerView: boolean;
}) {
  if (state.issue) return <ParamIssueView issue={state.issue} pageLabel="Historical Explorer" resetHref={HISTORICAL_PATH} />;
  if (playerUnavailable) {
    return (
      <EmptyState
        title="One-player rankings aren't available yet"
        message="Ranking a single player's seasons needs support from the baseball data service. The best seasons by every player are available now."
        action={<ButtonLink href={historicalHref({ ...state.query, playerId: null }, catalog)}>Best seasons by every player</ButtonLink>}
      />
    );
  }
  if (needsPlayer) {
    return (
      <EmptyState
        title="Choose a player"
        message="Search for a player above to see their seasons ranked, or switch back to all players."
      />
    );
  }
  if (result.status === "error") return <QueryErrorView error={result.error} retry={result.retry} resetHref={HISTORICAL_PATH} />;
  if (result.status !== "success") return <LoadingState label="Finding seasons" />;
  const data = result.data;
  if (data.seasons.length === 0 || !data.answer) {
    return (
      <EmptyState
        title="No seasons match"
        message={`Nothing in ${formatYearRange(data.query.yearRange)} matches this question. Widen the seasons, clear a filter or choose another stat.`}
        action={<ButtonLink href={HISTORICAL_PATH}>Start from the default question</ButtonLink>}
      />
    );
  }
  return <HistoricalAnswer result={data} answer={data.answer} catalog={catalog} playerView={playerView} />;
}

function HistoricalAnswer({
  result,
  answer,
  catalog,
  playerView,
}: {
  result: HistoricalExplorerResult;
  answer: NonNullable<HistoricalExplorerResult["answer"]>;
  catalog: Catalog;
  playerView: boolean;
}) {
  const chartId = useId();
  const { metric, qualification } = result;
  const byId = new Map(result.seasons.map((s) => [s.id, s]));
  const top = result.topSeasonId ? byId.get(result.topSeasonId) : undefined;

  const tiles = top
    ? result.keyMetrics.map((key) => {
        const def = metricOf(catalog, key);
        return { label: def?.label ?? key, value: formatStat(top.stats[key], def?.format ?? "count"), highlight: key === metric.key };
      })
    : [];

  return (
    <>
      <AnswerCard kicker={answer.context} headline={answer.headline} detail={answer.detail}>
        {tiles.length > 0 && <MetricTiles items={tiles} label={top ? `${top.player.name}, ${top.year}` : undefined} />}
      </AnswerCard>

      {qualification.summary && (
        <div className={shared.chips}>
          <Badge tone={qualification.kind === "none" ? "warn" : "accent"}>{qualification.summary}</Badge>
        </div>
      )}

      {result.chart && (
        <section className={shared.panel} aria-labelledby={chartId}>
          <h2 id={chartId} className="sr-only">
            {result.chart.title}
          </h2>
          <SeasonChart result={result} byId={byId} />
        </section>
      )}

      <NextActions result={result} top={top} catalog={catalog} playerView={playerView} />
    </>
  );
}

function SeasonChart({ result, byId }: { result: HistoricalExplorerResult; byId: Map<string, PlayerSeason> }) {
  const chart = result.chart!;
  const { metric } = result;
  const seasons = chart.seasonIds.flatMap((id) => byId.get(id) ?? []);

  if (chart.kind === "timeline") {
    return (
      <SeasonLineChart
        title={chart.title}
        valueLabel={metric.label}
        formatTick={(v) => formatStat(v, metric.format)}
        hollowLabel="Below the minimum"
        points={seasons.map((s) => ({
          year: s.year,
          value: s.stats[metric.key] ?? null,
          display: formatStat(s.stats[metric.key], metric.format),
          highlight: s.id === result.topSeasonId,
          hollow: !s.qualified,
        }))}
      />
    );
  }

  const items: RankingBarItem[] = seasons.map((s, i) => ({
    id: s.id,
    rank: s.rank ?? i + 1,
    label: s.player.name,
    sublabel: [s.year, s.team].filter(Boolean).join(" · "),
    value: s.stats[metric.key] ?? null,
    display: formatStat(s.stats[metric.key], metric.format),
    highlight: s.id === result.topSeasonId,
  }));
  return <RankingBars title={chart.title} items={items} valueLabel={metric.label} />;
}

function NextActions({
  result,
  top,
  catalog,
  playerView,
}: {
  result: HistoricalExplorerResult;
  top: PlayerSeason | undefined;
  catalog: Catalog;
  playerView: boolean;
}) {
  const { query, metric } = result;
  const leaderboardMetric = catalog.leaderboards.metrics.includes(metric.key) ? metric.key : catalog.leaderboards.metric;
  const leaderboardParams = new URLSearchParams({
    from: String(query.yearRange.start),
    to: String(query.yearRange.end),
    metric: leaderboardMetric,
  });
  const leadersLink = `/players/leaderboards?${leaderboardParams.toString()}`;
  if (!playerView) {
    return (
      <ActionRow label="Next steps">
        <ButtonLink variant="primary" href={leadersLink}>
          Leaders over {formatYearRange(query.yearRange)}
        </ButtonLink>
      </ActionRow>
    );
  }
  return (
    <ActionRow label="Next steps">
      {query.playerId === null && top ? (
        <ButtonLink variant="primary" href={historicalHref({ ...query, playerId: top.player.id }, catalog)}>
          All of {top.player.name}&apos;s seasons
        </ButtonLink>
      ) : (
        <ButtonLink variant="primary" href={historicalHref({ ...query, playerId: null, filters: undefined }, catalog)}>
          Best seasons by every player
        </ButtonLink>
      )}
      <ButtonLink href={leadersLink}>Leaders over {formatYearRange(query.yearRange)}</ButtonLink>
    </ActionRow>
  );
}

/** The ranked table (Explore more): the API's columns, Previous / Next over its pages, and its CSV. */
function SeasonsTable({
  state,
  first,
  catalog,
  onPage,
}: {
  state: HistoricalUrlState;
  first: HistoricalExplorerResult;
  catalog: Catalog;
  onPage: (page: number) => void;
}) {
  const client = useBaseballClient();
  const paging = client.capabilities.paging;
  const page = paging ? state.page : 1;
  const pageQuery = { ...state.query, offset: (page - 1) * TABLE_PAGE_SIZE };
  const later = useBaseballQuery(page > 1 ? JSON.stringify(pageQuery) : null, (c, options) => c.getHistoricalExplorer(pageQuery, options));
  const exportUrl = client.capabilities.csvExport ? client.historicalExportUrl(state.query) : null;

  let shown: HistoricalExplorerResult | null = first;
  let pending: QueryState<HistoricalExplorerResult> | null = null;
  if (page > 1) {
    if (later.status === "success") shown = later.data;
    else {
      shown = null;
      pending = later;
    }
  }

  return (
    <div>
      <h3 className={shared.subheading}>Seasons</h3>
      {shown && shown.table.rows.length === 0 ? (
        <EmptyState
          title="That page is past the last season"
          message={`There are ${formatCount(shown.totalCount)} seasons in this result, so there is nothing at row ${formatCount(shown.offset + 1)}.`}
          action={<Button variant="primary" onClick={() => onPage(1)}>Back to the first page</Button>}
        />
      ) : shown ? (
        <>
          <ResultTableView
            table={shown.table}
            catalog={catalog}
            label="Seasons"
            caption={`Rows ${formatCount(shown.offset + 1)}–${formatCount(shown.offset + shown.table.rows.length)} of ${formatCount(shown.totalCount)} seasons, ranked by ${shown.metric.name} (${shown.query.order === "asc" ? "lowest" : "highest"} first).`}
            rankedMetric={shown.metric.key}
            sortDirection={shown.query.order === "asc" ? "ascending" : "descending"}
          />
          {paging && <TablePager offset={shown.offset} shown={shown.table.rows.length} total={shown.totalCount} pageSize={TABLE_PAGE_SIZE} onPage={(offset) => onPage(offset / TABLE_PAGE_SIZE + 1)} />}
        </>
      ) : pending?.status === "error" ? (
        <ErrorState title="This page of seasons didn't load" message={pending.error.message} action={<Button variant="primary" onClick={pending.retry}>Try again</Button>} />
      ) : (
        <LoadingState label="Loading more seasons" />
      )}
      {exportUrl && (
        <p className={shared.exportRow}>
          <DownloadLink href={exportUrl}>Download CSV</DownloadLink>
          <span className={shared.note}>Every ranked season for this question ({formatCount(first.rankedCount)}), as the Python app exports it.</span>
        </p>
      )}
    </div>
  );
}


function OrderOnly({ order, onOrder }: { order: "asc" | "desc"; onOrder: (order: "asc" | "desc") => void }) {
  const id = useId();
  return (
    <div className={shared.field} style={{ maxWidth: 260 }}>
      <label className={shared.label} htmlFor={id}>
        Order
      </label>
      <select id={id} className={shared.select} value={order} onChange={(e) => onOrder(e.target.value === "asc" ? "asc" : "desc")}>
        <option value="desc">Highest first</option>
        <option value="asc">Lowest first</option>
      </select>
    </div>
  );
}

function ScopeChoice({ scope, onChange }: { scope: "all" | "player"; onChange: (scope: "all" | "player") => void }) {
  const name = useId();
  return (
    <fieldset className={`${shared.field} ${styles.scopeField}`}>
      <legend className={shared.label}>Whose seasons</legend>
      <div className={shared.segmented}>
        <label>
          <input type="radio" name={name} checked={scope === "all"} onChange={() => onChange("all")} />
          All players
        </label>
        <label>
          <input type="radio" name={name} checked={scope === "player"} onChange={() => onChange("player")} />
          One player
        </label>
      </div>
    </fieldset>
  );
}
