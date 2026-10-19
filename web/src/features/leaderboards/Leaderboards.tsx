"use client";

import { useSearchParams } from "next/navigation";
import { useId, useState } from "react";

import { RankingBars } from "@/components/charts/RankingBars";
import {
  ActionRow,
  AnswerCard,
  Badge,
  Button,
  ButtonLink,
  DownloadLink,
  EmptyState,
  ExploreMore,
  LoadingState,
  PlayerCard,
  Podium,
  SectionHeader,
} from "@/components/ui/primitives";
import { useBaseballClient, useBaseballQuery, type Catalog, type LeaderboardResult, type QueryState } from "@/lib/api";
import { formatCount, formatStat, formatYearRange } from "@/lib/format";

import { historicalHref } from "../historical/params";
import { metricOf, questionSummary, type ReadableParams } from "../shared/params";
import { ParamIssueView, QueryErrorView } from "../shared/QueryProblem";
import { MinimumsPanel } from "../shared/MinimumsPanel";
import { MetricSelect, QuestionBar, YearRangeFields } from "../shared/QuestionControls";
import shared from "../shared/questions.module.css";
import { ResultTableView } from "../shared/ResultTableView";
import { useSearchParamUpdater } from "../shared/useSearchParamUpdater";
import { formatWeights, LEADERBOARDS_PATH, readLeaderboardParams, sameWeights, type LeaderboardUrlState } from "./params";

/**
 * Who leads over a span of seasons: the answer the API wrote, the qualification rule, the top
 * three as cards, a top-10 visual, next steps, and the ranking table, score weights and CSV under
 * Explore more. Ranking, totals, qualification and wording are the API's; this only presents them.
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
  const client = useBaseballClient();
  const { query } = state;
  const key = state.issue ? null : JSON.stringify(query);
  const result = useBaseballQuery(key, (c, options) => c.getLeaderboard(query, options));
  const metrics = catalog.leaderboards.metrics.flatMap((k) => metricOf(catalog, k) ?? []);
  const exportUrl = client.capabilities.csvExport && !state.issue ? client.leaderboardExportUrl(query) : null;

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

      <ExploreMore description="The ranking table, how many players, score weights and the CSV download">
        {client.capabilities.paging && <TopNAndWeights catalog={catalog} state={state} onChange={(changes) => update(changes)} />}
        {client.capabilities.paging && (
          <MinimumsPanel
            key={JSON.stringify(query.minimums)}
            catalog={catalog}
            columns={catalog.leaderboards.minimumColumns}
            minimums={query.minimums ?? { ab: null, stats: {} }}
            status={result.status === "success" ? result.data.qualification.summary : null}
            onApply={(changes) => update(changes)}
          />
        )}
        {result.status === "success" && result.data.entries.length > 0 && (
          <div>
            <h3 className={shared.subheading}>Ranking table</h3>
            <ResultTableView
              table={result.data.table}
              catalog={catalog}
              label="Ranking table"
              caption={`Top ${formatCount(result.data.entries.length)} of ${formatCount(result.data.totalRanked)} ranked by ${result.data.metric.name} over ${formatYearRange(result.data.query.yearRange)}.`}
              rankedMetric={result.data.metric.key}
              sortDirection="descending"
            />
            {exportUrl && (
              <p className={shared.exportRow}>
                <DownloadLink href={exportUrl}>Download CSV</DownloadLink>
                <span className={shared.note}>The top {formatCount(result.data.entries.length)} shown here, as the Python app exports it.</span>
              </p>
            )}
          </div>
        )}
        {result.status === "success" && result.data.qualification.explanation && (
          <div>
            <h3 className={shared.subheading}>About the minimum</h3>
            <p>{result.data.qualification.explanation}</p>
          </div>
        )}
        <p className={shared.note}>
          The other Streamlit filters are still in the current app.
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
  if (data.entries.length === 0 || !data.answer) {
    const qualified = data.qualification.kind === "qualified" || data.qualification.kind === "manual";
    return (
      <EmptyState
        title={qualified ? "No qualified hitters" : "No players match"}
        message={
          qualified
            ? `Nobody reaches the at-bat minimum for ${formatYearRange(data.query.yearRange)}${data.qualification.summary ? ` (${data.qualification.summary})` : ""}. Try a longer span of seasons.`
            : `Nobody matches this question for ${formatYearRange(data.query.yearRange)}. Try other seasons or another stat.`
        }
        action={<ButtonLink href={LEADERBOARDS_PATH}>Start from the default question</ButtonLink>}
      />
    );
  }
  return <LeaderboardAnswer result={data} answer={data.answer} catalog={catalog} />;
}

function LeaderboardAnswer({
  result,
  answer,
  catalog,
}: {
  result: LeaderboardResult;
  answer: NonNullable<LeaderboardResult["answer"]>;
  catalog: Catalog;
}) {
  const podiumId = useId();
  const chartId = useId();
  const playerView = useBaseballClient().capabilities.playerSeasonRanking;
  const { metric, qualification, query } = result;
  const podium = result.entries.slice(0, 3);
  const leader = result.entries[0]!;
  const range = formatYearRange(query.yearRange);

  return (
    <>
      <AnswerCard kicker={answer.context} headline={answer.headline} detail={answer.detail} />

      <div className={shared.chips}>
        {qualification.summary && <Badge tone={qualification.kind === "none" ? "warn" : "accent"}>{qualification.summary}</Badge>}
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
                sub={entry.stats.AB !== null && entry.stats.AB !== undefined ? `${formatCount(entry.stats.AB)} AB` : undefined}
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
          title={`Top ${Math.min(10, result.entries.length)} by ${metric.name}, ${range}`}
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

      <NextActions result={result} catalog={catalog} leaderId={leader.player.id} leaderName={leader.player.name} playerView={playerView} />
    </>
  );
}

function NextActions({
  result,
  catalog,
  leaderId,
  leaderName,
  playerView,
}: {
  result: LeaderboardResult;
  catalog: Catalog;
  leaderId: string;
  leaderName: string;
  playerView: boolean;
}) {
  const { query, metric } = result;
  const seasonMetric = catalog.historical.metrics.includes(metric.key) ? metric.key : catalog.historical.metric;
  return (
    <ActionRow label="Next steps">
      {playerView && (
        <ButtonLink variant="primary" href={historicalHref({ metric: seasonMetric, playerId: leaderId }, catalog)}>
          {leaderName}&apos;s best seasons
        </ButtonLink>
      )}
      <ButtonLink
        variant={playerView ? "secondary" : "primary"}
        href={historicalHref({ yearRange: query.yearRange, metric: seasonMetric }, catalog)}
      >
        Best single seasons, {formatYearRange(query.yearRange)}
      </ButtonLink>
    </ActionRow>
  );
}

/** How many players (Top N) and the score's stat weights. Both are API parameters; Apply sends the weights. */
function TopNAndWeights({
  catalog,
  state,
  onChange,
}: {
  catalog: Catalog;
  state: LeaderboardUrlState;
  onChange: (changes: Record<string, string | null>) => void;
}) {
  const id = useId();
  const { limit, limitBounds, weights: defaults, weightStats, weightBounds, weightStep } = catalog.leaderboards;
  const current = state.query.weights ?? defaults;
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(weightStats.map((stat) => [stat, String(current[stat] ?? 0)])),
  );
  const parsed = Object.fromEntries(weightStats.map((stat) => [stat, Number(draft[stat])]));
  const valid = weightStats.every((s) => Number.isFinite(parsed[s]) && parsed[s]! >= weightBounds[0] && parsed[s]! <= weightBounds[1]) && weightStats.some((s) => parsed[s]! > 0);
  const changed = !sameWeights(parsed, current);
  const counts = [...new Set([limitBounds[0], 10, limit, 50, limitBounds[1]])].filter((n) => n >= limitBounds[0] && n <= limitBounds[1]).sort((a, b) => a - b);
  const apply = () => onChange({ w: sameWeights(parsed, defaults) ? null : formatWeights(parsed) });

  return (
    <div>
      <div className={shared.field} style={{ maxWidth: 260 }}>
        <label className={shared.label} htmlFor={`${id}-top`}>
          Players shown
        </label>
        <select
          id={`${id}-top`}
          className={shared.select}
          value={state.query.limit ?? limit}
          onChange={(e) => onChange({ top: Number(e.target.value) === limit ? null : e.target.value })}
        >
          {counts.map((n) => (
            <option key={n} value={n}>
              Top {n}
            </option>
          ))}
        </select>
      </div>

      <h3 className={shared.subheading} style={{ marginTop: "var(--space-5)" }}>
        Score weights
      </h3>
      <p className={shared.note} style={{ marginBottom: "var(--space-3)" }}>
        The Python app adds up the weighted stats for the Score ranking. Rate stats count ×100.
      </p>
      <div className={shared.weightGrid}>
        {weightStats.map((stat) => (
          <div key={stat} className={shared.weightField}>
            <label className={shared.label} htmlFor={`${id}-w-${stat}`}>
              {metricOf(catalog, stat)?.label ?? stat}
            </label>
            <input
              id={`${id}-w-${stat}`}
              aria-label={`Weight for ${metricOf(catalog, stat)?.label ?? stat}`}
              className={shared.input}
              type="number"
              inputMode="decimal"
              min={weightBounds[0]}
              max={weightBounds[1]}
              step={weightStep}
              value={draft[stat] ?? "0"}
              onChange={(e) => setDraft((d) => ({ ...d, [stat]: e.target.value }))}
            />
          </div>
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)", marginTop: "var(--space-3)", alignItems: "center" }}>
        <Button variant="primary" disabled={!valid || !changed} onClick={apply}>
          Apply weights
        </Button>
        <Button
          variant="ghost"
          disabled={sameWeights(parsed, defaults) && !state.query.weights}
          onClick={() => {
            setDraft(Object.fromEntries(weightStats.map((stat) => [stat, String(defaults[stat] ?? 0)])));
            onChange({ w: null });
          }}
        >
          Reset to defaults
        </Button>
        {!valid && <span className={shared.note}>Use values from {weightBounds[0]} to {weightBounds[1]}, with at least one above zero.</span>}
      </div>
    </div>
  );
}
