"use client";

import { Button, ButtonLink, EmptyState, ErrorState } from "@/components/ui/primitives";
import type { BaseballApiError } from "@/lib/api";

import type { ParamIssue } from "./params";

/**
 * One mapping from failures to designed states, shared by every question page.
 * - unavailable / unknown → error (alert) with Retry; the question stays in the URL.
 * - invalid_request / unsupported → an empty-style state with a way back to the default question.
 */
export function QueryErrorView({ error, retry, resetHref }: { error: BaseballApiError; retry: () => void; resetHref: string }) {
  switch (error.kind) {
    case "unavailable":
      return (
        <ErrorState
          title="Baseball data is unavailable right now"
          message="We couldn't reach the data service. Your question is saved in the address bar, so you can try again in a moment."
          action={<Button variant="primary" onClick={retry}>Try again</Button>}
        />
      );
    case "invalid_request":
      return (
        <EmptyState
          title="That question can't be answered"
          message={error.message}
          action={<ButtonLink href={resetHref}>Start from the default question</ButtonLink>}
        />
      );
    case "unsupported":
      return (
        <EmptyState
          title="Not available yet"
          message={error.message}
          action={<ButtonLink href={resetHref}>Start from the default question</ButtonLink>}
        />
      );
    default:
      return (
        <ErrorState
          title="Something went wrong"
          message={error.message}
          action={<Button variant="primary" onClick={retry}>Try again</Button>}
        />
      );
  }
}

/** A question in the URL that we won't send (unknown stat, impossible seasons). */
export function ParamIssueView({ issue, pageLabel, resetHref }: { issue: ParamIssue; pageLabel: string; resetHref: string }) {
  if (issue.kind === "metric") {
    return (
      <EmptyState
        title="Pick a stat to rank"
        message={`“${issue.value}” isn't a stat ${pageLabel} can rank. Choose one above.`}
        action={<ButtonLink href={resetHref}>Use the default stat</ButtonLink>}
      />
    );
  }
  return (
    <EmptyState
      title="Check the seasons"
      message={`“${issue.from}–${issue.to}” isn't a range of seasons we have. Use real years, with the first no later than the last.`}
      action={<ButtonLink href={resetHref}>Use the default seasons</ButtonLink>}
    />
  );
}
