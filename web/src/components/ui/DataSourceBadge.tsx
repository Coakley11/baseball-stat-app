"use client";

import { useBaseballClient } from "@/lib/api";

import { Badge } from "./primitives";
import styles from "./ui.module.css";

const EXPLANATION = "Sample data for interface development. Numbers are illustrative, not official statistics.";

/**
 * Always-visible marker while pages run on fixtures, so sample numbers never pass as real.
 * `panel`: sidebar note. `strip`: one line under the phone header.
 */
export function DataSourceBadge({ variant = "panel" }: { variant?: "panel" | "strip" }) {
  const client = useBaseballClient();
  if (client.source !== "mock") return null;
  if (variant === "strip") {
    return (
      <p className={styles.sourceStrip}>
        <strong>Sample data</strong> · numbers are illustrative, not official statistics
      </p>
    );
  }
  return (
    <div className={styles.sourceNote}>
      <Badge tone="dev">Sample data</Badge>
      <span>{EXPLANATION}</span>
    </div>
  );
}
