"use client";

import { useSearchParams } from "next/navigation";
import { useId } from "react";

import { RankingBars } from "@/components/charts/RankingBars";
import {
  ActionRow,
  AnswerCard,
  Badge,
  ButtonLink,
  EmptyState,
  ExploreMore,
  LoadingState,
  PlayerCard,
  Podium,
  SectionHeader,
} from "@/components/ui/primitives";
import { useBaseballQuery, type Catalog, type LeaderboardResult, type QueryState } from "@/lib/api";
import { formatCount, formatStat, formatYearRange } from "@/lib/format";

import { historicalHref } from "../historical/params";
import { metricOf, questionSummary, type ReadableParams } from "../shared/params";
import { ParamIssueView, QueryErrorView } from "../shared/QueryProblem";
import { MetricSelect, QuestionBar, YearRangeFields } from "../shared/QuestionControls";
import shared from "../shared/questions.module.css";
import { useSearchParamUpdater } from "../shared/useSearchParamUpdater";
import { LEADERBOARDS_PATH, readLeaderboardParams, type LeaderboardUrlState } from "./params";

/**
 * Who leads over a span of seasons: the ranked metric and qualification rule up front, the top
 * three as cards, a top-10 visual, next steps, and the full ranking under Explore more.
 * Ranking, totals and qualification are the API's; this only presents them.
 */
export function Leaderboards() {
  const searchParams = useSearchParams();
  const catalog = useBaseballQuery("catalog", (client, options) => client.getCatalog(options));

  if (catalog.status === "error") {
    return <QueryErrorView error={catalog.error} retry={catalog.retry} resetHref={LEADERBOARDS_PATH} />;
  }
  if (catalog.status !== "success") return <LoadingState label="Loading Leaderboards" />;
  return <LeaderboardsWithCatalog catalog={catalog.data} params={searchParams} />;
}

function LeaderboardsWithCatalog({ catalog, params }: { catalog: Catalog; params: ReadableParams }) {
  const state = readLeaderboardParams(params, catalog);
  const update = useSearchParamUpdater();
  const { query } = state;
  const key = state.issue ? null : JSON.stringify(query);
  const result = useBaseballQuery(key, (client, options) => client.getLeaderboard(query, options));
  const metrics = catalog.leaderboards.metrics.flatMap((k) => metricOf(catalog, k) ?? []);

  return (
    <div className={shared.page}>
      <QuestionBar
        label="Your question"
        summary={questionSummary(state.rawRange, state.issue?.kind === "metric" ? undefined : metricOf(catalog, query.metric))}
        forceOpen={state.issue !== null}
      >
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
      </QuestionBar>

      <section aria-label="Result" aria-busy={result.status === "loading"} className={shared.answerStack}>
        <ResultArea state={state} result={result} catalog={catalog} />
      </section>

      <ExploreMore description="The full ranking, how the score works, and the controls still to come">
        {result.status === "success" && result.data.entries.length > 0 && <FullRanking result={result.data} catalog={catalog} />}
        {result.status === "success" && result.data.score && (
          <div>
            <h3 className={shared.subheading}>How the score works</h3>
            <p>{result.data.score.summary}</p>
          </div>
        )}
        <p className={shared.note}>
          Custom stat weights, at-bat minimums, the number of players shown and CSV export are still in the current app.
          They move here with the Baseball API.
        </p>
      </ExploreMore>
    </div>
  );
}

function ResultArea({ state, result, catalog }: { state: LeaderboardUrlState; result: QueryState<LeaderboardResult>; catalog: Catalog }) {
  if (state.issue) return <ParamIssueView issue={state.issue} pageLabel="Leaderboards" resetHref={LEADERBOARDS_PATH} />;
  if (result.status === "error") return <QueryErrorView error={result.error} retry={result.retry} resetHref={LEADERBOARDS_PATH} />;
  if (result.status !== "success") return <LoadingState label="Ranking players" />;
  const data = result.data;
  if (!data.answer || data.entries.length === 0) {
    const qualified = data.qualification.kind === "qualified" || data.qualification.kind === "manual";
    return (
      <EmptyState
        title={qualified ? "No qualified hitters" : "No players match"}
        message={
          qualified
            ? `Nobody reaches the at-bat minimum for ${formatYearRange(data.query.yearRange)} (${data.qualification.summary}). Try a longer span of seasons.`
            : `Nobody matches this question for ${formatYearRange(data.query.yearRange)}. Try other seasons or another stat.`
        }
        action={<ButtonLink href={LEADERBOARDS_PATH}>Start from the default question</ButtonLink>}
      />
    );
  }
  return <LeaderboardAnswer result={data} catalog={catalog} />;
}

function LeaderboardAnswer({ result, catalog }: { result: LeaderboardResult; catalog: Catalog }) {
  const podiumId = useId();
  const chartId = useId();
  const { metric, qualification, query } = result;
  const answer = result.answer!;
  const podium = result.entries.slice(0, 3);
  const leader = result.entries[0]!;
  const range = formatYearRange(query.yearRange);

  return (
    <>
      <AnswerCard kicker={`Ranked by ${metric.name} · ${range}`} headline={answer.headline} detail={answer.detail} />

      <div className={shared.chips}>
        {qualification.kind !== "not_applicable" && qualification.summary && (
          <Badge tone={qualification.kind === "none" ? "warn" : "accent"}>{qualification.summary}</Badge>
        )}
        <Badge>
          {formatCount(result.totalRanked)} {qualification.kind === "qualified" ? "qualified hitters" : "players"} ranked
        </Badge>
      </div>

      <section aria-labelledby={podiumId} className={shared.tightSection}>
        <SectionHeader id={podiumId} title="Top 3" />
        <Podium>
          {podium.map((entry) => (
            <li key={entry.player.id}>
              <PlayerCard
                rank={entry.rank}
                name={entry.player.name}
                sub={`${entry.seasons} season${entry.seasons === 1 ? "" : "s"}`}
                value={formatStat(entry.stats[metric.key], metric.format)}
                valueLabel={metric.label}
                lead={entry.rank === 1}
              />
            </li>
          ))}
        </Podium>
      </section>

      <section className={shared.panel} aria-labelledby={chartId}>
        <h2 id={chartId} className="sr-only">
          Top 10 by {metric.name}
        </h2>
        <RankingBars
          title={`Top 10 by ${metric.name}, ${range}`}
          valueLabel={metric.label}
          items={result.entries.slice(0, 10).map((entry) => ({
            id: entry.player.id,
            rank: entry.rank,
            label: entry.player.name,
            value: entry.stats[metric.key] ?? null,
            display: formatStat(entry.stats[metric.key], metric.format),
            highlight: entry.rank === 1,
          }))}
        />
      </section>

      <NextActions result={result} catalog={catalog} leaderId={leader.player.id} leaderName={leader.player.name} />
    </>
  );
}

function NextActions({ result, catalog, leaderId, leaderName }: { result: LeaderboardResult; catalog: Catalog; leaderId: string; leaderName: string }) {
  const { query, metric } = result;
  const seasonMetric = catalog.historical.metrics.includes(metric.key) ? metric.key : catalog.historical.metric;
  return (
    <ActionRow label="Next steps">
      <ButtonLink variant="primary" href={historicalHref({ metric: seasonMetric, playerId: leaderId }, catalog)}>
        {leaderName}&apos;s best seasons
      </ButtonLink>
      <ButtonLink href={historicalHref({ yearRange: query.yearRange, metric: seasonMetric }, catalog)}>
        Best single seasons, {formatYearRange(query.yearRange)}
      </ButtonLink>
    </ActionRow>
  );
}

function FullRanking({ result, catalog }: { result: LeaderboardResult; catalog: Catalog }) {
  const columns = result.columns.map((key) => ({ key, def: metricOf(catalog, key) }));
  return (
    <div>
      <h3 className={shared.subheading}>Full ranking</h3>
      <div className={shared.tableScroll} role="region" aria-label="Full ranking" tabIndex={0}>
        <table className={shared.table}>
          <caption>
            Showing {formatCount(result.entries.length)} of {formatCount(result.totalRanked)} ranked, by {result.metric.name} over{" "}
            {formatYearRange(result.query.yearRange)}.
          </caption>
          <thead>
            <tr>
              <th scope="col">Rank</th>
              <th scope="col" className={shared.stickyCell}>
                Player
              </th>
              <th scope="col">Seasons</th>
              {columns.map(({ key, def }) => {
                const sorted = key === result.metric.key;
                return (
                  <th key={key} scope="col" className={sorted ? shared.sortedCol : undefined} aria-sort={sorted ? "descending" : undefined}>
                    {def?.label ?? key}
                    {sorted && <span aria-hidden="true"> ↓</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {result.entries.map((entry) => (
              <tr key={entry.player.id}>
                <td>{entry.rank}</td>
                <th scope="row" className={shared.stickyCell}>
                  {entry.player.name}
                </th>
                <td>{entry.seasons}</td>
                {columns.map(({ key, def }) => (
                  <td key={key} className={key === result.metric.key ? shared.sortedCol : undefined}>
                    {formatStat(entry.stats[key], def?.format ?? "count")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
