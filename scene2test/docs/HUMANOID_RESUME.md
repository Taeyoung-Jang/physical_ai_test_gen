# Resume the incomplete humanoid repetitions

Run from `scene2test`:

```bash
set -o pipefail
bash tools/resume_humanoid_repetitions.sh --live 2>&1 | tee -a zz_resume_humanoid_repetitions.log
```

This command uses the original `development/humanoid_reasoning_fallback3_20261024_v1`
campaigns and seeds. It skips completed arms, preserves all previous native results,
and continues toward seven valid episodes per method in each of the three sets.
At preparation time, 28 of 42 measurement episodes were valid: 14 per method;
14 episodes remain (AFS 7, Random 7). The separate control is not rerun.

The new tool is an explicit amendment to AFS proposal rejection handling. It catches
only the exact `episode review cites unknown or duplicate action version` validation
error after the normal source, saved request/context, provider and schema checks.
The original response is never edited, split into guessed numbers or accepted.
Instead a `rejection.json` records cited and permitted versions, the tool hash,
and the validation error. The original request remains charged to the original
nine-request cap per seed. The next request receives this rejection in the existing
`proposal_feedback` field. No robot attempt is charged for an invalid AFS proposal.
The policy amendment is saved as `action_reference_recovery.json` and events are
appended to the native ledger. Report this recovery policy in the final methodology.

The shared experiment, provider, robot and validation sources are unchanged;
existing source guards are still enforced. No copied archives, frozen manifests,
robot budget, environment bounds, failure verdict or Random schedule are changed.
New proposals use OpenRouter Luna with medium reasoning, and robot execution retains
high-to-medium-to-low-to-none verified-length fallback and 20 calls per episode.
Future malformed action references can be rejected only while the original request
budget remains. Other schema errors, HTTP errors, ambiguous requests, infrastructure
exclusions and interruptions still stop; no episode replacement or budget reset.

Default invocation validates saved evidence and prints a plan without API calls:

```bash
bash tools/resume_humanoid_repetitions.sh
```

Status after running:

```bash
bash tools/resume_humanoid_repetitions.sh --status
```

Once complete, repeating `--live` produces the saved summary without further API
or robot calls. Summaries remain at the original root's `replication_summary.json`
and `replication_summary.txt`; native per-campaign HTML reports are regenerated.
Three complete pairs are required for the aggregate mean and sample standard
deviation. Goal failure and human safety remain separate, and completion alone
does not establish statistical superiority.
