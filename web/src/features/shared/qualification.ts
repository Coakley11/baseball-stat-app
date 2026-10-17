import type { QualificationInfo } from "@/lib/api";
import { formatCount } from "@/lib/format";

/**
 * The qualification chip text. The API's own copy when it provides it (handoff R4). Until then,
 * only what its structured fields state: the minimum in force and whether it is automatic or
 * set manually. No rule is described or inferred beyond those fields.
 */
export function qualificationLabel(q: QualificationInfo): string | null {
  if (q.summary) return q.summary;
  if (q.kind === "qualified" && q.minAtBats) return `At least ${formatCount(q.minAtBats)} AB (automatic qualification minimum)`;
  if (q.kind === "manual" && q.minAtBats) return `At least ${formatCount(q.minAtBats)} AB (set manually)`;
  if (q.kind === "none") return "No at-bat minimum";
  return null;
}
