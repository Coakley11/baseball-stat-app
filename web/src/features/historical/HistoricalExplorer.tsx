"use client";

import { useSearchParams } from "next/navigation";
import { useId } from "react";

import { RankingBars, type RankingBarItem } from "@/components/charts/RankingBars";
import { SeasonLineChart } from "@/components/charts/SeasonLineChart";
import {
  ActionRow,
  AnswerCard,
  Badge,
  ButtonLink,
  EmptyState,
  ExploreMore,
  LoadingState,
  MetricTiles,
} from "@/components/ui/primitives";
import {
  useBaseballClient,
  useBaseballQuery,
  type Catalog,
  type HistoricalExplorerResult,
  type PlayerSeason,
  type QueryState,
} from "@/lib/api";
import { formatStat, formatYearRange } from "@/lib/format";

import { metricOf, questionSummary, type ReadableParams } from "../shared/params";
import { qualificationLabel } from "../shared/qualification";
import { ParamIssueView, QueryErrorView } from "../shared/QueryProblem";
import { MetricSelect, QuestionBar, YearRangeFields } from "../shared/QuestionControls";
import shared from "../shared/questions.module.css";
import { useSearchParamUpdater } from "../shared/useSearchParamUpdater";
import styles from "./historical.module.css";
import { HISTORICAL_PATH, historicalHref, readHistoricalParams, type HistoricalUrlState } from "./params";
import { PlayerPicker } from "./PlayerPicker";
import { SeasonTable } from "./SeasonTable";

/**
 * Question controls → answer card → default visual → next actions → Explore more.
 * The question is the URL; every number on screen comes from the client's result.
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
  const { query } = state;
  // One-player ranking only where the data source supports it (not the real API yet: R8).
  const playerView = useBaseballClient().capabilities.playerSeasonRanking;
  const playerUnavailable = !playerView && state.scope === "player";
  const needsPlayer = playerView && state.scope === "player" && query.playerId === null;
  const key = state.issue || needsPlayer || playerUnavailable ? null : JSON.stringify(query);
  const result = useBaseballQuery(key, (client, options) => client.getHistoricalExplorer(query, options));
  const metrics = catalog.historical.metrics.flatMap((k) => metricOf(catalog, k) ?? []);
  const playerName = result.status === "success" ? result.data.player?.name : undefined;
  const summary = questionSummary(
    state.rawRange,
    state.issue?.kind === "metric" ? undefined : metricOf(catalog, query.metric),
    state.scope === "all" ? "All players" : (playerName ?? "One player"),
    query.order === "asc" ? "Lowest first" : null,
  );

  return (
    <div className={shared.page}>
      <QuestionBar label="Your question" summary={summary} forceOpen={state.issue !== null || needsPlayer}>
        <YearRangeFields
          key={`${state.rawRange.start}-${state.rawRange.end}`}
          value={state.rawRange}
          bounds={catalog.years}
          onCommit={({ start, end }) => update({ from: start, to: end })}
        />
        <MetricSelect
          label="Rank by"
          metrics={metrics}
          value={state.issue?.kind === "metric" ? null : query.metric}
          onChange={(metric) => update({ metric })}
        />
        {playerView && (
          <ScopeChoice
            scope={state.scope}
            onChange={(scope) => update(scope === "all" ? { scope: null, player: null } : { scope: "player" })}
          />
        )}
        {playerView && state.scope === "player" && (
          <PlayerPicker
            selectedId={query.playerId}
            onSelect={(player) => update({ player, scope: null })}
            onClear={() => update({ player: null, scope: "player" })}
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

      <ExploreMore description="Order, every season returned, and the filters still to come">
        <AdvancedFilters state={state} onOrder={(order) => update({ order: order === catalog.historical.order ? null : order })} />
        {result.status === "success" && result.data.seasons.length > 0 && (
          <div>
            <h3 className={shared.subheading}>All seasons</h3>
            <SeasonTable result={result.data} catalog={catalog} />
          </div>
        )}
        <p className={shared.note}>
          Batting hand, position, franchise and league filters, split-season handling, stat minimums, Hall of Fame Case
          Mode, the relationship finder and CSV export are still in the current app. They move here with the Baseball
          API.
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
        message="Ranking a single player's seasons needs support from the baseball data service, which is coming. The best seasons by every player are available now."
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
  if (data.seasons.length === 0) {
    return (
      <EmptyState
        title="No seasons match"
        message={`Nothing in ${formatYearRange(data.query.yearRange)} matches this question. Widen the seasons or choose another stat.`}
        action={<ButtonLink href={HISTORICAL_PATH}>Start from the default question</ButtonLink>}
      />
    );
  }
  return <HistoricalAnswer result={data} catalog={catalog} playerView={playerView} />;
}

function HistoricalAnswer({ result, catalog, playerView }: { result: HistoricalExplorerResult; catalog: Catalog; playerView: boolean }) {
  const chartId = useId();
  const { answer, metric, qualification } = result;
  const byId = new Map(result.seasons.map((s) => [s.id, s]));
  const top = result.topSeasonId ? byId.get(result.topSeasonId) : undefined;
  const qualificationApplies = qualification.kind !== "not_applicable";
  const qualificationText = qualificationLabel(qualification);
  // Without an API answer, a title that states the question and claims nothing about the data.
  const headline = answer?.headline ?? `Best seasons by ${metric.name}, ${formatYearRange(result.query.yearRange)}`;

  const tiles = top
    ? result.keyMetrics.map((key) => {
        const def = metricOf(catalog, key);
        return { label: def?.label ?? key, value: formatStat(top.stats[key], def?.format ?? "count"), highlight: key === metric.key };
      })
    : [];

  return (
    <>
      <AnswerCard kicker={answer?.context ?? `Ranked by ${metric.name}`} headline={headline} detail={answer?.detail ?? undefined}>
        {tiles.length > 0 && <MetricTiles items={tiles} label={top ? `${top.player.name}, ${top.year}` : undefined} />}
      </AnswerCard>

      {qualificationApplies && qualificationText && (
        <div className={shared.chips}>
          <Badge tone={qualification.kind === "none" ? "warn" : "accent"}>{qualificationText}</Badge>
        </div>
      )}

      {result.chart && (
        <section className={shared.panel} aria-labelledby={chartId}>
          <h2 id={chartId} className="sr-only">
            {result.chart.title}
          </h2>
          <SeasonChart result={result} byId={byId} qualificationApplies={qualificationApplies} />
        </section>
      )}

      <NextActions result={result} top={top} catalog={catalog} playerView={playerView} />
    </>
  );
}

function SeasonChart({
  result,
  byId,
  qualificationApplies,
}: {
  result: HistoricalExplorerResult;
  byId: Map<string, PlayerSeason>;
  qualificationApplies: boolean;
}) {
  const chart = result.chart!;
  const { metric } = result;
  const seasons = chart.seasonIds.flatMap((id) => byId.get(id) ?? []);

  if (chart.kind === "timeline") {
    return (
      <SeasonLineChart
        title={chart.title}
        valueLabel={metric.label}
        formatTick={(v) => formatStat(v, metric.format)}
        hollowLabel={qualificationApplies ? "Below the at-bat minimum" : undefined}
        points={seasons.map((s) => ({
          year: s.year,
          value: s.stats[metric.key] ?? null,
          display: formatStat(s.stats[metric.key], metric.format),
          highlight: s.id === result.topSeasonId,
          hollow: qualificationApplies && !s.qualified,
        }))}
      />
    );
  }

  const items: RankingBarItem[] = seasons.map((s, i) => ({
    id: s.id,
    rank: i + 1,
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
        <ButtonLink variant="primary" href={historicalHref({ ...query, playerId: null }, catalog)}>
          Best seasons by every player
        </ButtonLink>
      )}
      <ButtonLink href={leadersLink}>Leaders over {formatYearRange(query.yearRange)}</ButtonLink>
    </ActionRow>
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

function AdvancedFilters({ state, onOrder }: { state: HistoricalUrlState; onOrder: (order: "asc" | "desc") => void }) {
  const id = useId();
  return (
    <div>
      <h3 className={shared.subheading}>Advanced filters</h3>
      <div className={shared.field} style={{ maxWidth: 260 }}>
        <label className={shared.label} htmlFor={id}>
          Order
        </label>
        <select
          id={id}
          className={shared.select}
          value={state.query.order}
          onChange={(e) => onOrder(e.target.value === "asc" ? "asc" : "desc")}
        >
          <option value="desc">Highest first</option>
          <option value="asc">Lowest first</option>
        </select>
      </div>
    </div>
  );
}
