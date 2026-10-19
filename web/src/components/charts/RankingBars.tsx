/**
 * Ranked horizontal bars as a semantic ordered list: every name and value is real text, so the
 * chart needs no separate table to be readable, and long names wrap instead of truncating.
 * One series, one colour; the answer's row is emphasised by a full-strength bar, bold text and
 * an "Answer" tag (never colour alone). Bar length is only `value / largest value shown`.
 */
import { useId } from "react";

import styles from "./charts.module.css";

export interface RankingBarItem {
  id: string;
  rank: number;
  label: string;
  sublabel?: string;
  value: number | null;
  /** Value as displayed (".311", "1,234"). */
  display: string;
  highlight?: boolean;
}

export function RankingBars({ title, items, valueLabel }: { title: string; items: RankingBarItem[]; valueLabel: string }) {
  const captionId = useId();
  const max = Math.max(0, ...items.map((i) => i.value ?? 0));
  return (
    <figure className={styles.figure} aria-labelledby={captionId}>
      <figcaption id={captionId} className={styles.caption}>
        {title}
      </figcaption>
      <ol className={styles.bars}>
        {items.map((item) => {
          const share = max > 0 && item.value !== null && item.value > 0 ? item.value / max : 0;
          return (
            <li key={item.id} className={styles.barRow} data-highlight={item.highlight || undefined}>
              <span className={styles.barRank} aria-hidden="true">
                {item.rank}
              </span>
              <span className={styles.barName}>
                <span className="sr-only">{`Rank ${item.rank}: `}</span>
                {item.label}
                {item.sublabel && <span className={styles.barSub}> {item.sublabel}</span>}
                {item.highlight && <span className={styles.barTag}>Answer</span>}
              </span>
              <span className={styles.barValue}>
                {item.display}
                <span className="sr-only"> {valueLabel}</span>
              </span>
              <span className={styles.barTrack} aria-hidden="true">
                <span className={styles.barFill} style={{ width: `${(share * 100).toFixed(1)}%` }} />
              </span>
            </li>
          );
        })}
      </ol>
    </figure>
  );
}
