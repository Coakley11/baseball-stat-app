import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/ui/primitives";
import { HistoricalExplorer } from "@/features/historical/HistoricalExplorer";

export const metadata: Metadata = {
  title: "Historical Explorer",
  description: "The best single seasons for any years and stat, back to 1871.",
};

export default function HistoricalExplorerPage() {
  return (
    <>
      <PageHeader eyebrow="Players" title="Historical Explorer" purpose="The best single seasons for any years and stat, back to 1871." />
      <Suspense fallback={<LoadingState label="Loading Historical Explorer" />}>
        <HistoricalExplorer />
      </Suspense>
    </>
  );
}
