/**
 * Design-system primitives. Server-safe (no hooks), so pages can use them anywhere.
 * Each one presents values it is given; none computes a statistic.
 */
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import styles from "./ui.module.css";

function cx(...names: (string | false | null | undefined)[]): string {
  return names.filter(Boolean).join(" ");
}

/* ---------------------------------------------------------------- headers */

export function PageHeader({ eyebrow, title, purpose }: { eyebrow?: string; title: string; purpose?: string }) {
  return (
    <header className={styles.pageHeader}>
      {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
      <h1 className={styles.pageTitle}>{title}</h1>
      {purpose && <p className={styles.pagePurpose}>{purpose}</p>}
    </header>
  );
}

export function SectionHeader({
  id,
  title,
  description,
  action,
}: {
  id?: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={styles.sectionHeader}>
      <h2 id={id} className={styles.sectionTitle}>
        {title}
      </h2>
      {action}
      {description && <p className={styles.sectionDescription}>{description}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------- card */

export function Card({ muted = false, className, ...rest }: ComponentProps<"div"> & { muted?: boolean }) {
  return <div className={cx(styles.card, muted && styles.cardMuted, className)} {...rest} />;
}

/* ------------------------------------------------------------ answer card */

export function AnswerCard({
  kicker,
  headline,
  detail,
  tone = "default",
  children,
}: {
  kicker?: ReactNode;
  headline: string;
  detail?: ReactNode;
  tone?: "default" | "warn";
  children?: ReactNode;
}) {
  return (
    <section className={cx(styles.answer, tone === "warn" && styles.answerWarn)} aria-label="Answer">
      {kicker && <p className={styles.answerKicker}>{kicker}</p>}
      <p className={styles.answerHeadline} role="heading" aria-level={2}>
        {headline}
      </p>
      {detail && <p className={styles.answerDetail}>{detail}</p>}
      {children && <div className={styles.answerExtra}>{children}</div>}
    </section>
  );
}

/* ----------------------------------------------------------- metric tiles */

export interface MetricTileItem {
  label: string;
  value: string;
  highlight?: boolean;
}

/** Two per row on phones, auto-fit on wider screens; never shrinks into slivers. */
export function MetricTiles({ items, label }: { items: MetricTileItem[]; label?: string }) {
  if (items.length === 0) return null;
  return (
    <dl className={styles.tiles} aria-label={label}>
      {items.map((item) => (
        <div key={item.label} className={cx(styles.tile, item.highlight && styles.tileHighlight)}>
          <dt className={styles.tileLabel}>{item.label}</dt>
          <dd className={styles.tileValue}>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------ player card */

export function RankBadge({ rank }: { rank: number }) {
  const medal = rank === 1 ? styles.rank1 : rank === 2 ? styles.rank2 : rank === 3 ? styles.rank3 : undefined;
  return (
    <span className={cx(styles.rankBadge, medal)}>
      <span className="sr-only">Rank </span>
      {rank}
    </span>
  );
}

/** A ranked player: rank badge (number always printed), name, context line and the value. */
export function PlayerCard({
  rank,
  name,
  sub,
  value,
  valueLabel,
  lead = false,
}: {
  rank: number;
  name: string;
  sub?: string;
  value: string;
  valueLabel: string;
  lead?: boolean;
}) {
  return (
    <div className={cx(styles.playerCard, lead && styles.playerCardLead)}>
      <RankBadge rank={rank} />
      <div className={styles.playerBody}>
        <p className={styles.playerName}>{name}</p>
        {sub && <p className={styles.playerSub}>{sub}</p>}
      </div>
      <p className={styles.playerValue}>
        <span className={styles.playerValueNumber}>{value}</span>
        <span className={styles.playerValueLabel}>{valueLabel}</span>
      </p>
    </div>
  );
}

/** Ordered list of PlayerCards: one column on phones, three across from 720px. */
export function Podium({ children }: { children: ReactNode }) {
  return <ol className={styles.podium}>{children}</ol>;
}

/* ---------------------------------------------------------------- buttons */

type ButtonVariant = "primary" | "secondary" | "ghost";

export function Button({ variant = "secondary", className, type = "button", ...rest }: ComponentProps<"button"> & { variant?: ButtonVariant }) {
  return <button type={type} className={cx(styles.button, styles[variant], className)} {...rest} />;
}

export function ButtonLink({ variant = "secondary", className, ...rest }: ComponentProps<typeof Link> & { variant?: ButtonVariant }) {
  return <Link className={cx(styles.button, styles[variant], className)} {...rest} />;
}

/** 1–4 next steps. Stacks full-width on narrow phones. */
export function ActionRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <nav aria-label={label} className={styles.actions}>
      {children}
    </nav>
  );
}

/* ------------------------------------------------------------------ badge */

export type BadgeTone = "neutral" | "accent" | "good" | "warn" | "dev";

const BADGE_TONES: Record<BadgeTone, string | undefined> = {
  neutral: styles.badgeNeutral,
  accent: styles.badgeAccent,
  good: styles.badgeGood,
  warn: styles.badgeWarn,
  dev: styles.badgeDev,
};

export function Badge({ tone = "neutral", children, title }: { tone?: BadgeTone; children: ReactNode; title?: string }) {
  return (
    <span className={cx(styles.badge, BADGE_TONES[tone])} title={title}>
      {children}
    </span>
  );
}

/* ----------------------------------------------------------- explore more */

/**
 * Everything advanced (filters, full tables, secondary charts, export) behind one native
 * disclosure, closed by default. Keyboard and screen-reader support come from <details>.
 */
export function ExploreMore({
  title = "Explore more",
  description,
  children,
  defaultOpen = false,
}: {
  title?: string;
  description?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className={styles.explore} open={defaultOpen || undefined}>
      <summary className={styles.exploreSummary}>
        <svg className={styles.exploreChevron} width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className={styles.exploreTitle}>
          {title}
          {description && <span className={styles.exploreDescription}>{description}</span>}
        </span>
      </summary>
      <div className={styles.exploreBody}>{children}</div>
    </details>
  );
}

/* ----------------------------------------------------------------- states */

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className={styles.skeleton} role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}…</span>
      <div className={styles.skeletonBlock} style={{ height: 132 }} aria-hidden="true" />
      <div className={styles.skeletonBlock} style={{ height: 72 }} aria-hidden="true" />
      <div className={styles.skeletonBlock} style={{ height: 240 }} aria-hidden="true" />
    </div>
  );
}

export function EmptyState({ title, message, action }: { title: string; message?: ReactNode; action?: ReactNode }) {
  return (
    <section className={styles.state} aria-label={title}>
      <p className={styles.stateTitle} role="heading" aria-level={2}>
        {title}
      </p>
      {message && <div className={styles.stateMessage}>{message}</div>}
      {action && <div className={cx(styles.actions, styles.stateActions)}>{action}</div>}
    </section>
  );
}

export function ErrorState({ title, message, action }: { title: string; message?: ReactNode; action?: ReactNode }) {
  return (
    <section className={cx(styles.state, styles.stateError)} role="alert">
      <span className={styles.stateIcon}>
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path d="M8 4.5v4.2M8 11.2v.3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
        Error
      </span>
      <p className={styles.stateTitle} role="heading" aria-level={2}>
        {title}
      </p>
      {message && <div className={styles.stateMessage}>{message}</div>}
      {action && <div className={cx(styles.actions, styles.stateActions)}>{action}</div>}
    </section>
  );
}
