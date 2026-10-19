import { Button } from "@/components/ui/primitives";
import { formatCount } from "@/lib/format";

import styles from "./questions.module.css";

/**
 * Previous / Next over the API's pages (`offset` + `total`). Shows where you are; nothing is
 * counted here beyond arithmetic on the offsets the API reported.
 */
export function TablePager({
  offset,
  shown,
  total,
  pageSize,
  onPage,
}: {
  offset: number;
  shown: number;
  total: number;
  pageSize: number;
  onPage: (offset: number) => void;
}) {
  if (total <= pageSize) return null;
  const from = shown === 0 ? 0 : offset + 1;
  const to = offset + shown;
  return (
    <nav className={styles.pager} aria-label="Table pages">
      <p className={styles.pagerStatus} aria-live="polite">
        Rows {formatCount(from)}–{formatCount(to)} of {formatCount(total)}
      </p>
      <div className={styles.pagerButtons}>
        <Button variant="secondary" disabled={offset <= 0} onClick={() => onPage(Math.max(0, offset - pageSize))}>
          Previous
        </Button>
        <Button variant="secondary" disabled={to >= total} onClick={() => onPage(offset + pageSize)}>
          Next
        </Button>
      </div>
    </nav>
  );
}
