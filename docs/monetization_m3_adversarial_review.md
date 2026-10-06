# M3 adversarial review — findings before remediation

Reviewed frozen M2 `9bdada7d` as an attacker and as a failed/concurrent worker.

| Attack/failure | M2 finding | M3 action |
| --- | --- | --- |
| Metadata creates ownership | Blocked: webhook requires an existing server mapping; metadata can only conflict-check. | Add explicit empty/unknown/conflict tests. |
| Empty/unknown customer | Blocked before projection. | Preserve and test. |
| Cross-user customer race / multiple customers | Database uniqueness plus read-back verification fails closed. | Add race/conflict tests; retain one-to-one constraints. |
| Client chooses price/customer/plan | Service accepts only Pro intent and resolves price/customer server-side. | Add request-shape tests. |
| Success redirect replay | No projection occurs from redirect. | Preserve and test. |
| Duplicate Checkout | Customer creation is idempotent, but Checkout creation lacked a server key. | Add server-derived daily attempt idempotency key. |
| Concurrent webhook workers | Atomic database claim returns `in_progress`, but completion was not tied to lease owner. | Add random lease token required for completion/failure. |
| Worker crash | Five-minute expiry permits retry, but no owner token. | Tokenized reclaim; stale owner cannot finalize. |
| Event-ID collision | Fingerprint/type/time/mode conflict fails without overwrite. | Preserve and test original record immutability. |
| Old/equal-time ordering | `(created,event_id)` ordering is deterministic. | Add resurrection and equal-time tests. |
| Test/live crossing | Rejected before ledger claim. | Expand configuration/mode matrix. |
| Oversized body | Post-read 1 MB check exists; declared size was not rejected before read. | Reject oversized `Content-Length` before body read; keep post-read check. |
| Public secret leakage | Public status uses booleans only. | Inject recognizable secrets and test all public output. |
| Unsafe URLs | Nonempty URLs were accepted. | Validate HTTPS; allow HTTP only for loopback in explicit test mode. |
| RLS/function access | M2 revokes client writes/functions and limits entitlement reads to `auth.uid()`. | New forward-only migration reasserts grants and tokenizes privileged functions. |
| Dev override in live/preview | Requires explicit local/test runtime. | Expand rollout matrix test. |
| Cross-user reads | Entitlement RLS and adapter ownership check block it. | Add SQL/adapter tests. |
| PII persistence | Event ledger stores fingerprint/correlation only; customer table omits email. | Preserve. |
