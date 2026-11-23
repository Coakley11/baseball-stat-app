# Pro presentation prototype — regression record

Branch `feature/pro-presentation`, CI branch `ci/pro-presentation`; baseline Dev `00cb48b`. CI compares
every suite on the candidate and on the baseline and lists new / pre-existing / fixed failures.

| CI run | Candidate | Suites | New failures | Outcome |
|---|---|---|---|---|
| 45074542814 | `180a711` (+CI) | 8 + pro | 6 | Real: Material icons on the badge/page (owner rule: emoji only) and the pricing caption AMI's page help quotes. Fixed in `0f236c5`. |
| 45076690269 | `0f236c5` (+CI) | 8 + pro | 1 | `test_live_draft_create_and_mode_sticky.StartTimeoutTests::test_stale_in_flight_expires` (draftsource_b) — timing-sensitive, see below |
| 45082452207 | `5bbb761` (owner decisions) | 8 + pro | 3 (+ flaky) | Real: Live Draft completion-panel tests — the new "Analyze Draft" Pro note read `st.session_state`, which the panel's test double lacks. Fixed in `18d4860` (uses the panel's session; labels can never break a page). |
| 45084740647 | `18d4860` (+CI) | 8 + pro | 1 | Only the flaky `test_stale_in_flight_expires`; 8 of 9 suites 0 new, `pro` suite green on both sides. **No actual regression.** |

## The one remaining comparison difference is a flaky timing test, not a regression

`test_stale_in_flight_expires` (Live Draft start-timeout handling):

- The prototype does not change `live_draft_create.py` or the test (no diff against `00cb48b`).
- In the AMI A2 CI run 45071469118 the same test **failed on the baseline and passed on the
  candidate**; in 45076690269 it **passed on the baseline and failed on the candidate** — it flips
  between runs of identical code.
- Locally it passed 3/3 on the prototype and 3/3 on the A2 candidate.

The test was not changed or skipped. It is listed for a separate fix (make its clock deterministic) in
`docs/MAINTENANCE_ISSUES_2026-11-22.md` (branch `plan/maintenance-20261122`).

## Pre-existing failures (also fail on Dev, not caused by the prototype)

Confirmed locally on the unmodified A2 candidate (Dev + AMI-only changes):

- `tests/test_fantasy_trade_center_workflow.py::…::test_archive_offer_hides_from_inbox_not_history`
- `tests/test_draft_archive_callbacks.py::…::test_live_draft_save_click_records_trace_before_persist`
- `tests/test_draft_archive_navigation.py` (4 tests)
- `tests/test_draft_archive_visibility.py::…::test_team_claim_without_invite_stays_hidden`
- `tests/test_ami_assistant_help.py::…::test_every_listed_control_exists_on_its_page` — one missing
  label on Dev ("Categories / skills to strengthen"); the prototype keeps every other help label intact
  (verified label by label against Dev).
