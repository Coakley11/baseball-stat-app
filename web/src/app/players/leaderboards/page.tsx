import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/ui/primitives";
import { Leaderboards } from "@/features/leaderboards/Leaderboards";

export const metadata: Metadata = {
  title: "Leaderboards",
  description: "Who leads over a span of seasons, in one stat or a custom score.",
};

export default function LeaderboardsPage() {
  return (
    <>
      <PageHeader eyebrow="Players" title="Leaderboards" purpose="Who leads over a span of seasons, in one stat or a custom score." />
      <Suspense fallback={<LoadingState label="Loading Leaderboards" />}>
        <Leaderboards />
      </Suspense>
    </>
  );
}
