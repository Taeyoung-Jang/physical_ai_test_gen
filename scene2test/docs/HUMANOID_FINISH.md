# Finish the final humanoid repetition

From `scene2test`:

```bash
set -o pipefail
bash tools/finish_humanoid_repetitions.sh --live 2>&1 | tee -a zz_finish_humanoid_repetitions.log
```

The original root is `development/humanoid_reasoning_fallback3_20261024_v1`.
At preparation, 34/42 episodes are valid: AFS17 (12PASS/5FAIL), Random17
(16PASS/1FAIL). Two paired sets are complete; only seed253785482 continues,
with AFS4 and Random4 episodes remaining. No baseline or completed episode reruns.
The original AFS cap is nine requests: four already used (including the current
invalid response), five remain for four probes. More invalid requests may exhaust
that cap; the tool does not extend it or replace excluded robot episodes.

`finish_humanoid_repetitions.py` explicitly extends proposal rejection handling
to exactly two validation errors: missing required episode review, or unknown/
duplicate action version. Native source/resource/evidence, request/context, provider
and schema checks still run before either can be rejected. For a missing review,
feedback lists all required, supplied and missing evidence IDs. A new normal model
request must supply complete reviews; the host never fabricates a review, repairs
the original response or accepts a candidate lacking required evidence.

Each rejected response stays charged to the existing AFS request cap. Its original
response remains unchanged, with a separate hashed rejection and native ledger event.
The existing v1 recovery script and `action_reference_recovery.json` are preserved
and verified. The v2 policy is written to `required_review_recovery_v2.json` on live
execution and links its source hash to the old policy hash and original batch plan.
No shared executable sources, manifests, seeds, environment bounds, robot settings,
Random schedule, outcomes or budgets change. Report both recovery amendments in
methodology. Other validation/HTTP/ambiguous/exclusion errors still stop.

Default invocation prints a verified plan without API calls. Use `--status` for
saved evidence verification and the aggregate summary. Once complete, `--live`
also returns the verified summary without new API/robot calls.

```bash
bash tools/finish_humanoid_repetitions.sh --status
```

Results remain at the original root's `replication_summary.{json,txt}` and native
per-seed reports. Aggregate means and sample standard deviations are emitted only
when all three pairs complete; statistical superiority is not automatically claimed.
