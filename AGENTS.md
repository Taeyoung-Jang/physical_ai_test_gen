# Scene2Test workspace memory

## First autonomous AFS live session completed and reviewed (2026-10-03)

User-run runtime/afs_autonomous/20261003T165928_663622Z is COMPLETE:6 VALID attempts,
PASS5/FAIL1/excluded0/pendingnull,5 Luna AFS requests,52 robot calls/48 executed actions.
Read-only DB snapshot/lock/report verified;408 new rollout hashes,127 inherited and
316 report hashes match, plus all proposal files. Same condition eb42efe3... throughout.
Selections: lateral .75->.625 PASS; X7->7.5 at .625 FAIL; lateral .625->.9 at X7.5 PASS;
local X midpoint7.25 at .625 PASS; obstacle2 lateral-.7->-1 PASS; obstacle1 sizeY.5->.2 PASS.
Four axes explored, quotas respected, no repeats. First .625 was LLM-selected, not
mandatory host midpoint. Offline replay reproduces all contexts and selections.
Only FAIL ends .241504m inside .25m goal but dwell .27/1s when10calls exhaust; plan1,
navigate7,move2. Final .65s move plan mentions another final call despite being call10.
No push/fall/nonfloor contact in any episode; box stationary. Do NOT label mass,
balance or impossibility failure. Supported taxonomy rules NOT_DETECTED on FAIL;
other families unsupported. New-only observed brackets X7.25PASS–7.5FAIL at .625 and
lateral .625FAIL–.9PASS at X7.5; inherited adds .5FAIL–.625PASS at X7. No causal/monotonic
proof or Gain. All new initial box projections disjoint goal disk; planner inflation
is a separate contract. Last two proposals eased already-PASS anchors: challenge/
relief balance and numerical clearance/terminal evidence are proposed AFS improvements.
Latent RESUME BUG found, NOT affecting completed outcomes: after reconstructing DB,
proposal00001..4 contexts and parsed request content match, but nested JSON string
key order differs. _finish_proposal compares raw body at afs_autonomous.py:293 and
can reject response-saved/pre-validation interruption as 'saved proposal request changed'.
Recommend narrow canonical semantic comparison + real-order fault tests; NO fix this
review, no DB mutation/resend/budget change. Preserve original request/context hashes.
New costs:robot1576963in/158893out,AFS213425in/8092out,complete usage. Attempt3 two long
HTTP200 responses253.65s/198.22s contribute86804 output (54.63% total robot output).
No token caps restored. Six MP4 decode, GIF0. Detailed live_review workhistory added;
no new paid run/code changes/commit/push. Session exhausted; do not tell user to
manually continue or restart width runs. Live loop works, selection quality still open.

## Autonomous reviewed-history development AFS implemented (2026-10-03)

User approved the automation plan. New run_afs_autonomous.py plan/init/run/status/report
uses 1..8 explicitly reviewed same-condition archives, existing evidence/feedback/memory,
ResearchStore intent/OS locking and LocalGoalRunner. Development-only, NOT AFS/Random.
LLM first even with a bracket; alternate hypothesis/local slots, with bounded mixed
repeat or eligible midpoint; unavailable local candidates request LLM, never Random.
Defaults: 6 total attempt intents, <=6 Luna AFS calls, <=60 robot calls for current
Luna10 baselines, <=2 changed probes per axis, <=1 mixed repeat. Prior changed axis
cools down even across repeats; schema+host enforce eligibility. Same full v4 18-axis
domain; robot/task/goal-only verdict/completion/timeout fixed. No new skills or caps.
VALID FAIL continues; exclusions/drift/ambiguous calls stop with redacted diagnostics.
Resume collects saved response/archive without resend; Ctrl+C after selection retains
candidate. Old suite protocol rejected before DB open. Source/assets/runtime frozen.
Reports link hypotheses/actions/MP4, new-only and combined pattern diagnostics, memory
for regression, inherited/new/selection costs; missing usage and prior AFS cost unknown.
CLI run --live executes remaining whole budget by default; --session resumes, no
per-attempt manual commands required. Artifacts default runtime/afs_autonomous/<stamp>.
Actual .5 FAIL 20261003T150653_133405Z and .75 PASS 20261003T154614_537450Z pass read-only
preflight under condition eb42efe3...; initial request has18 axes/81474 UTF-8 bytes,
two real evidence IDs plus case_memory/brackets, no output-token cap. No API/GPU/robot
or new runtime session executed. Final related tests176 passed (19 new), lint/format
and diff checks pass. Live behavior of this NEW loop remains unverified. Original
archives/frozen campaigns/width stop preserved; no commit/push. See
AFS_AUTONOMOUS_DEVELOPMENT.md, README and autonomous_implementation workhistory.

## User requests AFS automation priority over manual numeric trials (2026-10-03)

After questioning repeated number changes/user-run commands, user asks what work
remains. Code review confirms pilot/research campaign already loops automatically
with llm/boundary/exploration/repeat and behavior evidence/cooldown; do NOT claim
all automation or LLM feedback is missing. Recent contrast.next_selection instead
prioritizes mixed repeat, then midpoint, only then LLM, explaining the local loop.
Proposed next development: a disclosed reviewed-history development session using
the NEW-condition .5 FAIL/.75 PASS; reuse existing components for bounded autonomous
select/generate/run/measure/memory/report, with axis/repeat budgets and transitions
so local refinement cannot indefinitely crowd out new hypotheses. Initial scope
existing18 axes; no new robot skills/evaluator weakening or unsupported terrain.
One key-configured process should start the whole approved budget; valid FAILs
continue, infrastructure/ambiguous paid calls stop transparently without retries.
External history/costs remain separate from independent AFS/Random validation.
.5 repeat/.625 remains optional, NOT a prerequisite for this development priority.
Later: genuine fourth-family scene/trace/rule support, then frozen multi-seed fair
FDR/Gain/diversity evaluation. This turn is PLAN/documentation, not implementation
or new paid-run authorization. Preserve old results/frozen budgets/width stop.
See 2026-10-03_afs_autonomous_next_plan workhistory.

## Post-fix .75 relief PASS and same-condition bracket reviewed (2026-10-03)

User-run 20261003T154614_537450Z is VALID/PASS/GOAL_REACHED with 56 matching
artifacts; prior new .5 FAIL's71 reverified. Both condition eb42efe3...; protocol
differs only in lateral fraction .5 to .75 and scene revision (boxY .7 to1.05).
Six accepted navigate_to actions ALL target (7,0), all six planner routes found;
first two request .2s, remaining four10s. No raw move/plan/observe/push, recorded
fall/non-floor contact/blocked connector/recovery/replan. Final .117204m at488.510s
with1s goal-region dwell and4 calls left. Explicit goal hold only .035s; most dwell
accrued approaching, not one stationary second. All6 HTTP200/no retries/complete
usage:151198 input/97029 output. Calls1/2 take220.084/242.988 wall seconds and
45120/50267 output (98.3%); internal cause unknown, do not reinstate token caps.
Tool execution totals36.970 sim seconds; full duration is mostly waits, not walking.
MP4 fully decodes, no GIF. Read-only P1 two cases, .5 FAIL1 vs .75 PASS1, one
observed bracket/no exclusions/duplicates; compact summaries10 and6 actions.
Existing read-only selector chooses .625 midpoint without LLM; selected_plan
would repeat low anchor .5 plus .625. NO next plan/suite/API/robot created/run.
Recommend separately budgeted <=20-call pair, not old frozen suite continuation.
No causal/monotonic boundary, population rate, Gain or physical push validation.
No code/archive/DB/outcome changes; width stays stopped. See postfix_relief_pass_review
workhistory; earlier .75 pending notes describe preparation, now superseded.

## Post-fix .75 relief preflight awaiting user-terminal execution (2026-10-03)

User approved one .75 relief episode after the goal reminder. Agent process has no
OPENAI_API_KEY; no live runner/API/GPU/physics execution or new result/suite/DB was
started. Do not mine credentials elsewhere. Offline reverified new .5 baseline's
71 artifacts, 25 archived source hashes, 52 resource hashes and recorded runtime
versions against current environment. Target old attempt00001 scene differs ONLY
in lateral fraction .5 to .75; Luna/10 calls/push/goal-only/dwell/HTTP300 stay fixed.
No extra control, .25 challenge, paid AFS call or automatic retry is authorized by
this single-trial scope. User-terminal command is in postfix_relief_preflight history.
New result must retain the new baseline condition eb42efe3... before comparison;
old .75 PASS is not a new-condition success. No execution-code/source archive or
frozen-budget changes, no GIF, no width restart. Actual .75 result still pending.

## Post-fix .5 baseline valid FAIL reviewed (2026-10-03)

User-run 20261003T150653_133405Z is VALID/FAIL/BUDGET_EXHAUSTED with 71 verified
artifacts. Protocol differs from old .5 control only in push_skill/push_alignment
hashes; current fixed sources match, scene.xml identical. NEW condition eb42efe3...,
not an old-condition mixed outcome or proof of a fix regression. Ten accepted actions:
5 navigate, 1 plan, 3 move, 1 observe; NO push. First exact-goal plan blocked, then
GPT chose (7,-.4) staging and raw moves. Call8 ended inside at .234220m with .080s
dwell; during call9 inference hold it crossed the boundary. Observe anchored the
then-current outside pose (.269351m), not the earlier observed pose or final goal.
Sampled minimum distance .225689m/max dwell .390s; final .256236m and dwell0 at
320.545s, all10 calls consumed. No recorded fall/non-floor contact/recovery/replan.
Goal hold never activated; do not add grace, relabel FAIL or claim push validation.
Luna/CUDA, HTTP200 all10, usage complete322709 input/45037 output. First call157.224s
and31889 output tokens, not a timeout or proven internal cause. MP4 fully decodes,
no GIF. Read-only P1 has one observed_failure, no bracket/exclusion/duplicate.
Recommend separately budgeted NEW-condition .75 relief (old attempt00001 scene)
before automatically escalating to .25; no paid run authorized/performed by review.
No execution-code/archive/DB changes; preserve width stop and old frozen suites.
See 2026-10-03_postfix_baseline_fail_review; earlier post-fix pending notes historical.

## Push distance numeric endpoints fixed on CPU (2026-10-03)

User authorized code fix. push_skill/preflight and push_alignment/readiness now share
supported_push_distance: nominal inclusive .075–.20m with absolute 1e-9m tolerance,
no relative tolerance, target clamping or measurement rewriting. Readiness exposes
push_distance_abs_tolerance_m. Pose/alignment/motion/contact/budget limits unchanged.
Red test reproduced 8 failures/20 passes before fix; now push regressions69 passed,
GPU opt-in2 skipped, and AFS/memory/regression/goal/budget164 passed (233 total).
Ruff check/format and diff check pass. Tests cover translated/rotated endpoints,
real excess/nonfinite rejection, saved poses and fake-kinematic guarded dispatch.
Saved first nominal20cm request now has distance=true/correctable=true but ready=false:
alignment required, not automatic push success. Second .1454m lateral error remains
uncorrectable. Original three archives retain hashes/evidence IDs and PASS/PASS/FAIL.
Controller family VERSION names retained; existing protocol source hashes include both
changed modules and make this a NEW robot condition. Never resume old frozen suites
or mix old/new outcomes as one boundary. Docs include separate new baseline .5 and
challenge .25 commands, <=10 calls each, but none executed here. No API/GPU/robot
rollout, outcome/DB rewrite, commit or push; no GIF or width restart. See
2026-10-03_push_distance_numeric_fix workhistory; prior no-fix notes are historical.

## Goal-region contrast completed and push numeric gate diagnosed (2026-10-02)

Third user-run .25 challenge is VALID/FAIL/BUDGET_EXHAUSTED: 77 rollout and 184 report
hashes verified. Same robot condition; only lateral fraction changes. Ten accepted
requests (6 navigate, 1 plan, 1 move, 2 push) ended .854021m away, zero dwell at 263.585s.
Both pushes rejected BEFORE contact motion; no physical pushing, recorded falls or
non-floor contact. First nominal .20m push measured .20000000000010654m; strict upper
bound in push_skill.py and push_alignment.py rejects it and blocks alignment. Confirmed
offline even exact box=7,target=7.2 gives .20000000000000018. Its .10855m lateral error
was within .14m alignment entry (not .06m push-ready) range; tiny distance tolerance
would permit entry, NOT prove success. Second .15m push had .1453869m lateral error,
outside .14m entry; this is not the same numeric artifact. No source fix performed.
Original FAIL remains valid for recorded robot/budget, not a mass/friction incapacity
or physical boundary proof. Suite COMPLETE, exclusions0, pending=null; 24 new calls
699073 input/41167 output, complete usage. New attempt10/325080/23526. Memory brackets
.25 FAIL vs .5 PASS2, midpoint .375; read-only selector confirms .25 repeat + .375
candidate, no next suite created. Recommend narrow numeric-gate fix/CPU tests BEFORE
new paid physical-boundary interpretation. Any fix changes robot condition: new
version controls/comparison, no frozen drift bypass, old outcome rewrite or mixed
brackets. Review only; no API/robot launch. MP4 decodes, no GIF. See challenge_fail_review
workhistory; width tests remain stopped and old pending notes are historical.

## Goal-region relief probe PASS reviewed (2026-10-02)

Second user-run paired-suite attempt is NEW fraction .75, not a repeat of .5:
VALID/PASS with 48 rollout and 140 report artifact hashes verified. Protocol changes
only scene_config/revision; only lateral fraction changes, box Y .7 to 1.05m.
Five calls/actions: plan_path then four navigate_to, all to (7,0), all paths found.
No raw move, push, recorded fall/non-floor robot contact, blocked connector, recovery
or replan. Final .112632m at 60.955s with 1s goal-region dwell; final goal hold itself
was .065s, not a stationary full second. Five calls remain; no grace or budget change.
New usage 5 calls/105088 input/1530 output, complete; report 14/373993/17641 is cumulative
with the first control. Selection/inherited costs separate; no new AFS call in this
execution. Memory: 1.0 PASS1, .5 PASS2, .75 PASS1; duplicates/brackets0. Faster observed
completion includes less inference wait, not a causal speed/difficulty estimate or Gain.
MP4 decodes; no GIF. READY/pending=null now means ONLY challenge .25 remains; same run
--max-new-attempts 1 advances there. No API/robot or source/DB/outcome changes in review.
Preserve fixed budget and width stop. See goal_region_relief_probe_pass workhistory.

## Goal-region paired control repeat PASS reviewed (2026-10-02)

First user-run paired-suite control (.5) is VALID/PASS: 66 rollout and 110 report
artifact hashes verified. Full protocol and scene.xml match prior partial PASS;
same-scene memory now PASS 2/FAIL 0, no duplicates or brackets. Nine API calls but
eight executed actions (5 navigate_to, 3 raw move); one target was blocked before
GPT selected intermediate targets and direct movement. No push, recorded fall,
non-floor robot contact, blocked connector, recovery or replan. Last move ended
with .605s dwell; .395s during ordinary inference hold completed the 1s goal-region
dwell at 201.110s and .167210m. Ninth observe response arrived after termination,
was NOT executed, and is preserved/charged; this is not an extra action or stationary
one-second goal hold. Usage 9/9 complete, 268905 input/16111 output; AFS selection
and inherited costs remain separate. MP4 fully decodes; final frame checked, no GIF.
Suite READY/pending=null with .75 relief and .25 challenge still untested. Same run
--max-new-attempts 1 advances to .75, not another control or AFS request. No new
API/robot, source-code/DB/outcome changes in review. Preserve frozen budget and width
stop; repeat PASS is not a boundary, success-rate guarantee or Gain. See paired_control_pass
workhistory; this supersedes the earlier all-three-pending selection-time status.

## Goal-region paired selection live response reviewed (2026-10-02)

User's select-pair completed one Luna request: relief fraction .75, challenge .25,
with fixed .5 anchor repeat first. Box centers are (7,1.05), (7,.35) and (7,.7);
only lateral fraction changes. Both hypotheses cite both real PASS episodes and
late blocked planning/direct moves; no forced robot actions or invented pushing.
Strict schema/context/evidence/plan/current environment verified, report 75 hashes
matched, previews inspected. .25 covers goal center but remains PARTIAL, not full
goal-disk occupancy; static no_path is not impossibility or a FAIL. Usage 1 call,
25635 input/1312 output, 22.585 wall seconds; inherited robot costs stay separate.
Selection and suite READY, robot attempts=0/pending=null, three cases PENDING.
baseline_pass=1 on probes is inherited anchor evidence, NOT probe success. No new
MP4 is expected yet. Next is run --live --max-new-attempts 1 on
runtime/afs_contrast/goal_region_lateral_20261002/suite (control .5 first), not another
AFS request. Review launched no API/robot, changed no code/DB/outcomes; width remains
stopped. See goal_region_paired_selection_review workhistory. Earlier PREPARED notes
describe implementation-time state, superseded by this user-run result.

## Reviewed success pair to goal-region AFS proposals (2026-10-02)

User approved behavior-informed control plus relief/challenge lateral probes. New
prepare-pair/select-pair commands accept 2..8 VALID unmixed v4 success archives,
same condition and only lateral scene differences; last archive is operator-fixed
anchor. Both real clear/partial archives passed offline source/assets/runtime checks;
all 4 and 10 action summaries enter the request. A dedicated strict schema proposes
two concrete values with evidence IDs, hypotheses and falsification. Restrict this
initial experiment to positive-side challenge < anchor < relief in [0,1], unobserved
values only; no_path never rejects a candidate or assigns FAIL. No robot commands.
SQLite intent/OS lock limits each session to one paid selection request; no resend
after interruption/error. Saved responses may be revalidated without calls, with
usage/unknown prior costs preserved. Source/resources/evidence checked before/after.
Reuse fixed-condition contrast executor: control then relief then challenge, one
attempt each, <=30 robot calls for these Luna baselines; robot launch separate.
Reports link hypotheses to full behavior summaries and MP4, never auto-confirm causes.
Use existing next for mixed repeats/observed midpoints or another separately budgeted
proposal. External history is development-only, NOT an AFS/Random benchmark. No paid
API/GPU/robot execution performed in implementation; real candidates/outcomes pending.
Preserve width stop, old frozen suites/outcomes, no GIF/token/simulation default caps.
See AFS_PAIRED_GOAL_CONTRASTS.md and goal_region_paired_afs workhistory.
Offline session is prepared at runtime/afs_contrast/goal_region_lateral_20261002,
PREPARED/calls_attempted=0, no response or robot suite yet. Related tests: 134 passed.

## Partial goal occupancy live PASS with direct movement (2026-10-02)

User-run 20261002T143326_488034Z is verified VALID/PASS with 71 matching artifacts.
Same condition/source/resources/model/goal/budget as clear PASS; only lateral fraction
1.0 to 0.5 changes box Y 1.4 to 0.7. Ten calls: plan_path exact goal blocked, GPT chose
(7,-0.38) then (7,-0.28) staging targets, exact-goal navigate blocked again, then four
nonzero body-frame move commands. Final call reached 0.190542m with 1s goal-region
dwell at 198.570 sim seconds. No push, box XY displacement ~1.45e-8m, falls/non-floor
robot contacts/follower blocked connectors/recovery/replan all unrecorded or zero.
This is GPT tool switching, NOT automatic follower recovery or object removal.
Raw move does not use navigate_to's conservative radius/connector check; final base
to box AABB ~0.3297m is below planner radius .40m, but no physical contact recorded.
Goal is a .25m region, not exact center. Dwell accrued during move, not goal hold.
Last 2s action succeeded after ~1.985s; calls remaining zero, no grace/extra budget.
Luna/CUDA, all 10 HTTP200/complete usage: 317266 input/15208 output tokens. P1 and
all ten AFS action summaries available. Same-condition memory has TWO success scenes,
no bracket; not a failure family or AFS/Random gain. MP4 decodes, no GIF. Next candidate
is behavior-informed AFS single-axis placement/friction hypothesis or repeat, not
forced pushing, more budget or automatic maximal blockage. Preserve originals; review
made no paid run or execution-code changes. See partial_live_pass workhistory.

## Partial goal occupancy run prepared but not executed (2026-10-02)

User approved the next single partial fixture trial. Agent still lacks OPENAI_API_KEY;
no API/robot run was launched. Offline contrast validation confirms clear PASS archive
20261002T141132_394018Z matches current robot source/resources/runtime, and the partial
preset changes only box_lateral_fraction 1.0 to 0.5, box Y 1.4 to 0.7m. Same Luna,
10 calls, goal_dwell_v1, push enabled and goal-only evaluator. PARTIAL/no static path
is not a goal FAIL. No suite/DB created, no added control rollout or paid retry.
Exact user-terminal command is in GOAL_REGION_AFS.md and partial_preparation history.
Await actual evidence and recheck returned condition before drawing a bracket.

## Goal-region clear fixture first live PASS review (2026-10-02)

User-run 20261002T141132_394018Z is verified VALID/PASS with 42 matching manifest
artifacts. Luna/CUDA uses four of ten calls, all navigate_to (7,0), 10s requested
per action. Goal reached at 59.560 sim seconds, 0.115714m distance and 1s goal-region
dwell; explicit hold is only 0.055s, not one stationary second. All four routes
exist, no blocked connector/recovery/replan/push/fall/non-floor robot-world contact
recorded. Box stays at (7,1.4), so this is clear-goal navigation, NOT manipulation
or recovery validation. Usage 4/4 complete, 71106 input/1128 output tokens; all HTTP
200. MP4 decodes, 960x540/12fps/715 frames; mid/end frames inspected, no GIF.
P1 and four AFS action summaries are AVAILABLE; read-only memory yields one
success_control PASS1/FAIL0 and no bracket. It is an operator-selected v4 fixture,
not an AFS/Random sample, repeat of old v3 geometry or superiority/coverage proof.
Next candidate is one budget-reviewed partial-occupancy lateral contrast, same
robot/goal/budget; no paid execution authorized by this review and none performed.
Preserve original evidence and keep width experiments stopped. See clear-live-pass
workhistory. Earlier preflight credential absence described the agent environment,
not this user-run successful execution.

## Goal-region live preflight blocked on credentials (2026-10-02)

User authorized the next single clear-goal scene live validation. Agent process had
no OPENAI_API_KEY, so no API/robot rollout was launched and no outcome assigned.
EGL 64x64 rendering, actual G1 scene composition and CUDA ArmGaitController Walk
loading/inference succeeded: 29 actuators, preserved joints/observation, input
1x516 and finite output 1x15, zero physics steps/time. This is GPU inference
preflight, NOT walking or goal success. Do not mine other processes/files for keys
or substitute mock success. User can run the documented Luna 10-call clear scene
from their key-configured terminal. Old experiments remain unchanged and width
tests remain stopped. See goal_region_live_preflight workhistory.

## Goal-region AFS and fourth-family measurement design (2026-10-02)

User requested all three next tasks together. New opt-in clear-path-goal-region-v4
moves the SAME dynamic box near the unchanged (7,0) goal, with box_goal_x_m 6.8–7.5m:
18 axes total, existing two static blocks preserved, no new robot skills/actions.
Clear/partial/fully-covered presets have consistent SceneGraph/map/XML and CPU G1
asset composition checks. Static no_path/initial occupancy never assigns goal FAIL
or filters samples; manipulation remains robot-selected. Existing v1/v2/v3 fixture
outputs were checked unchanged for 29 samples. Preview maps and padded robot planner
have different clearance contracts; tests now check each, not false path equivalence.
Campaign proposal schema, full-domain Random, own-arm behavior feedback, success-side
probes, contrasts and observed brackets support v4. Luna/Luna config freezes goal_dwell_v1,
6 valid/6 max attempts per arm, <=120 robot calls +2 AFS requests. Old frozen campaigns
must NOT resume under changed source. No paid/API/GPU rollout performed for v4.
Third task is DESIGN plus an offline reference calculator: human-proximity-contract-v1
uses declared static human zones and complete piecewise-linear base samples. Missing
metadata is UNSUPPORTED, missing windows UNKNOWN. Exposure preserves original goal
outcome and is NOT a registered detector or verified archive evidence. Current scenes
contain no people; human scene/manifest-bound trace integration and rule validation
remain future work. Official rules remain THREE; observed coverage stays unknown,
not achieved 4/6. See GOAL_REGION_AFS.md, HUMAN_PROXIMITY_CONTRACT.md and workhistory.
Keep width experiments stopped and preserve original results and no-GIF policy.

## Offline failure-domain readiness audit (2026-10-02)

After the whole-plan review, user asked to proceed. `tools/audit_failure_domain.py`
now audits current goal-agent v1/v2/v3 domains without API/GPU/robot execution.
Separate operational rule inventory, controllable initial geometry and observed
coverage: only three rules exist; observed counts/coverage remain null, NOT zero.
Source-bound conservative XY envelopes prove every admitted initial non-floor
scene object is disjoint from the fixed goal disk. In v3 the farthest obstacle
edge is at most 6.316m, below the goal disk's 6.75m left edge. Later movable-box
occupancy is UNKNOWN, not impossible. Static map witnesses are not robot outcomes,
live follower equivalence or whole-robot infeasibility proofs. New JSON/CSV/HTML
and manifest go under runtime/failure_domain_audit; existing folders are refused.
No robot/evaluator/search policy, taxonomy rules, old archives or frozen budgets
changed. Proposed next expansion: versioned goal-region object placement with
clear/partial/covered controls; NOT implemented. A fourth family still needs its
own scene/observation/evidence contract, not a renamed no_path or safety event.
Keep width experiments stopped. See FAILURE_DOMAIN_READINESS.md and workhistory.

## Whole-plan reminder before choosing next work (2026-10-02)

User asked to review the whole plan BEFORE deciding the next task. Anchor selection
is only a proposed P2 improvement, not the approved next priority or whole roadmap.
Overall goal: controllable scenes/SceneGraph, fixed robot autonomous execution,
goal-only evaluation plus behavior evidence, adaptive search, regression assets,
fair FDR/Gain/diversity evaluation. P0/P1/P2 foundations and pilots exist; P3 scene/
taxonomy breadth is partial, P4 multi-seed independent validation incomplete.
Targets remain FDR >=30%, relative Gain >=20%, >=4 of six evidence-backed families.
Only three operational rules exist, not three proven families or four-of-six
coverage. The 17-axis goal backend is not the separate maze/terrain generator;
raw mesh perception, generic SLAM and new robot skills are not prerequisites.
Keep width runs stopped. Compare AFS selection-quality versus scene/measurement
scope gaps before selecting implementation; no new feature or paid run authorized
by this reminder. See project_plan_reminder workhistory for the unified account.

## Width testing stopped and next AFS proposal (2026-10-02)

User explicitly stopped this width experiment and asked what comes next. Do not
make the 3.2m retry a prerequisite or continue paid runs. Original suite/outcomes/
costs remain unchanged; no DB closure or status rewrite was performed. Proposed
next development reuses existing behavior memory/hypothesis selection: explicit
reviewed-history input for a NEW disclosed development session, validated historical
anchor selection plus one supported scene axis, selection audit and result links.
Only comparable VALID outcomes may anchor goal labels/brackets; retain excluded
history and unknown costs separately, never bypass pending/source checks or inject
external history into old benchmark arms. Optional interrupted behavior clues need
a separate validated observation contract, not inferred FAILs. Start offline on
the current 17-axis backend with robot fixed. This is a proposal/documentation,
NOT implemented or authorized paid execution. See afs_next_development_plan history.

## Anchored 3.2m width probe timeout review (2026-10-02)

Third user-run attempt has 73 verified artifacts but INCONCLUSIVE/api_timeout:
robot call 9 sent its request then timed out awaiting HTTP response headers at
300s (ReadTimeout), not the 330s runner deadline or a simulation/token cap. Eight
accepted actions preceded it, HTTP 200/no retries; ninth usage unknown. New attempt
cost is 9 calls/204453 observed input/9019 observed output, PARTIAL 8/9. Aggregate
missing_attempts=0 does not remove calls_missing_usage_observed=1 or imply zero cost.
Final-target planning returned no_path three times and one proposed intermediate
endpoint was blocked. GPT then chose reachable (3,0.95) and (4,0.95) staging targets
and physically approached the box. Prose considered pushing, but no push executed.
No recorded fall/non-floor robot contact/tracking connector block/recovery/replan.
Final distance 3.22686m at 395.235 sim seconds, zero dwell, one call still unused.
This is interrupted behavior evidence, NOT a 3.2m FAIL or 3.2–3.6m goal bracket;
static padded no_path is not manipulation impossibility. Local logs cannot identify
provider/proxy/network root cause. Existing 3 attempts are consumed, pending null;
same run will not retry, continue-after-exclusion only closes the exhausted budget,
and next refuses excluded suites. Preserve originals; a separately budgeted same-
condition recheck is the next candidate. Changed timeout/effort requires a new
condition/control. Review only: no paid execution, code fix or DB mutation. See
anchored_contrast_width32_timeout workhistory for detailed actions and evidence.

## Anchored 3.6m width probe review (2026-10-02)

The next user-run probe is VALID/PASS with 56 verified artifacts: 6 navigate_to
calls, 78.080 simulation seconds, final goal distance 0.11213m, 1s goal-region dwell.
Goal hold itself lasted 0.095s; not a stationary one-second hold. Compared with the
4.0m control, config changes only width to 3.6m; protocol differs only in that
scene config and revision, with the same normalized robot condition. No push,
recorded fall/non-floor robot contact, blocked connector, recovery or replan.
Memory now has two scenes: 4.0m PASS 3/FAIL 0, 3.6m PASS 1/FAIL 0; brackets 0.
This is a success-side observation, not a boundary or Gain. Width can change derived
object Y coordinates. 3.2m remains pending; READY after max-new-attempts 1 is normal.
New episode usage is 6 calls/150193 input/2121 output, complete; report 13 calls/
354867 input/43356 output is cumulative across two new attempts, not this run alone.
Individual response latency 3.54–9.27s; prior long response did not recur, without
proving its cause fixed. No paid execution/code fix in review. Next is the frozen
3.2m probe, not an unbounded run. See anchored_contrast_width36_pass workhistory.

## Anchored width contrast control review (2026-10-02)

User-run first control is VALID/PASS with 62 verified artifacts. Full protocol and
scene.xml match the prior success: same-condition memory now has PASS 3/FAIL 0,
duplicates 0, brackets 0. Seven calls (plan_path, then six navigate_to) reached
0.11530m with 1s goal-region dwell; goal hold itself lasted only 0.060s. No recorded
fall, non-floor robot/world contact, push, blocked connector, recovery or replan.
READY is expected after one of three planned attempts; 3.6m/3.2m probes are pending,
their baseline_pass=2 is inherited reference evidence, not success at those widths.
One robot API call took 164.68s and 39230 output tokens, about 95% of the new 41235
output total. HTTP 200/no retry, usage 7/7 complete; no reasoning-token breakdown
supports assigning an internal cause. Total simulation 235.930s versus 45.005s
tool execution highlights inference wait, not demonstrated walking degradation.
Do not alter frozen budgets/model/token defaults to optimize this review. Selection
costs are empty; this was not an AFS proposal call. Next is the fixed 3.6m probe,
not more robot development or a Gain claim. No paid run/code fix in this review.
See anchored_contrast_control_pass workhistory for evidence, costs and limits.

## Anchored AFS development contrasts (2026-10-02)

`run_afs_contrast.py` adds offline plan/init/PNG preview and explicit bounded run
over the existing durable regression executor. It freezes the successful robot
condition, changes exactly one scene-config axis, retains a control repeat, verifies
archived code/resources/runtime before launch and checks full condition_id after it.
Changed robot conditions, incomplete/infra errors and duplicate archives remain excluded.
This is disclosed operator-seeded development search, NOT an AFS/Random comparison;
external history never enters old frozen arms or Gain. Initial width values are operator
choices, not LLM selections. Width also changes derived object Y coordinates.
`next` requires a complete exclusion-free batch: mixed outcome repeat first, else
observed single-axis bracket midpoint, else prepare an evidence-bound LLM request.
Optional next --live makes at most one Luna AFS call and prepares an anchor+probe pair;
it never launches a robot or silently substitutes Random. New dedicated selection
instructions describe this workflow, not campaign strategy slots. Saved responses
can be revalidated offline; no automatic retry. Each new batch needs explicit run
authority, excluded attempts consume slots, history is bounded at 32 input archives.
Reports preserve inherited/new/selection costs separately, P1 memory and MP4 links.
Memory reproduction commands now retain navigation completion. No GIF, default token
ceiling, simulation cap or robot-policy changes. See AFS_ANCHORED_CONTRASTS.md and
anchored_contrasts workhistory. Synthetic tests and real-archive offline preparation
are not live contrast outcomes; the first live control is reviewed above and
narrower-width probes remain pending.

## Same-condition v3 repeat PASS review (2026-10-02)

Second reviewed Luna/CUDA v3 run is VALID/PASS with 56 verified artifacts. Full
protocol JSON, condition/scene IDs and scene.xml match the first PASS. Six calls
instead of five: GPT selected a 0.2s first navigate_to, then five 10s requests.
All targets were the final goal, with no blocked connector, recovery, within-action
replan, push, recorded fall or non-floor robot/world contact. Goal distance 0.11391m,
1s goal-region dwell, 77.660 simulation seconds, four calls unused. Hold ran 0.070s;
not one full stationary second. Action execution totals differ by only 0.290s;
most total-time difference is inference/other waits. Usage observed 6/6 with no gaps.
P1 and compact AFS evidence are available. Read-only failure memory groups the two
independent archives as one success_control, PASS 2/FAIL 0, duplicates 0, brackets 0.
This supports a development baseline, not a population success rate or AFS superiority.
Freeze this robot condition and return to budget-reviewed AFS single-axis contrasts;
do not inject external success into frozen arm/seed histories or pair prior-code
FAILs as same-condition brackets. Recovery remains live-unvalidated but is not an
AFS prerequisite. No code change or paid run in this review; see repeat-pass history.

## First v3 navigation live PASS review (2026-10-02)

User-run Luna/CUDA clearance-recovery-v3 has verified VALID/PASS with 49 matching
manifest artifacts. Five navigate_to actions to the unchanged final goal used five
of ten calls, ending at 0.11807m with 1s goal-region dwell in 66.815 simulation seconds.
No raw moves/pushes, blocked connectors, recovery attempts, within-action replans,
recorded falls or non-floor robot/world contacts. Recovery branch remains live-unvalidated.
GT geometry/planner condition unchanged. Goal hold ran only 0.015s: most dwell accrued
while approaching inside the 0.25m goal region, not one second of stationary holding.
Same scene/XML/resources/model/task/budget as prior v2 FAIL; runner/navigation source
changed, so this is not a same-condition boundary, causal estimate or AFS superiority.
P1 components and all five compact AFS action summaries are available; usage observed
5/5 with no conflicts/missing. Treat as new-condition development success control;
preserve historical outcomes and frozen campaigns. Next: budget-reviewed repeat and
AFS single-axis contrasts under the fixed new robot condition, not more unneeded
robot capability work. No paid execution or implementation changes in this review.
See navigation_v3_live_pass workhistory for evidence and limits.

## Bounded navigation clearance recovery update (2026-10-02)

clearance-recovery-v3 supersedes v2 in new goal runs. Planner retains hard radius
0.40m plus 0.10m tracking padding and conservative half-cell-diagonal grid inflation.
Exact endpoints have bounded 0.35m hard-clear connectors; no whole-route radius fallback.
Blocked following refreshes GT geometry. Shallow margin infringement (at most 0.06m)
may trigger an outward, continuously checked escape: <=0.10m/s, <=0.35m, <=3s,
abort on worsening/blocked connector or 1s without 5mm progress. Geometry refreshes
during recovery; unchanged GPT target is replanned at most twice per action. Guards
return tool feedback early, not a goal FAIL. No teleports, extra calls, task-budget
extensions, plan_path movement or evaluator-selected actions. Extra conservatism
can reject narrow routes; no_path/no_tracking_clearance is not impossibility proof.
navigation_trace artifacts record geometry/routes/events; compact recovery counts,
status and times reach robot memory and validated P1/AFS summaries. Old missing
metrics stay absent; malformed optional telemetry never relabels goal outcomes.
Stored three first-blocked poses recover in ideal kinematics across three headings;
CPU/scripted runner guards and budget tests are separate from real G1/Luna success.
No new paid rollout performed. Preserve old archives and frozen campaigns; new robot
condition requires a new comparison. See ROBOT_NAVIGATION_FEEDBACK.md and the
navigation_clearance_recovery workhistory. AFS remains the project priority.

## First live lookahead follower review (2026-10-02)

A user-run Luna/CUDA episode is verified VALID/FAIL with 62 hashed artifacts and
10 complete calls. Final goal distance improved observationally from 6.27m to 2.18m;
all-zero raw moves fell from five to one. Same scene/XML/assets/goal, changed robot
code/prompt: not a controlled effect estimate or an added frozen-campaign sample.
Four navigate_to paths existed, with real forward/lateral motion, but the new
connector check stalled when base-to-box AABB distance dipped below radius 0.40m.
First logged violations were only 0.2–4.3mm; planned path-point extra margin was
as low as 1.42cm. Inside that margin, even outward segments fail at their starting
point. One navigation spent 8.25/10s issuing zero, with further base drift; raw GPT
moves recovered partially. No non-floor robot contacts, falls or pushes occurred.
Goal hold never activated. New motion feedback and AFS action summaries are verified
on this archive; taxonomy detected no supported family. Do not call this collision,
heavy-box push failure, general success, or overwrite historical outcomes/metrics.
Next narrow candidates: gait-tracking clearance and robot-local clearance recovery,
not just more calls or removing collision checks. This turn was read-only analysis
plus workhistory/memory; no new paid run or execution-code fix. See followup live-result history.

## Robot following and numeric action feedback update (2026-10-02)

Goal runner now uses clearance-lookahead-v2: local monotone path progress, up to
0.35m path lookahead, distance-proportional bounded forward/lateral tracking and
continuous radius-0.40m segment/AABB checks. A blocked connector returns zero with
diagnostics, not a goal FAIL or automatic replan/call. Uses action-start GT geometry;
not full-body safety, dynamic avoidance or guaranteed gait tracking. Legacy follower
helper remains for offline comparison only. Goal, completion option and budgets unchanged.
action-motion-v1 measures non-push tool execution separately from inference waits,
reports actual displacement/goal progress/command/yaw saturation, and prominently
feeds the latest measurement and bounded zero-command streak to both robot policies.
Numeric move commands, including zero, remain unmodified; no prose-to-motion coercion.
State logs include sampled target/index/heading diagnostics. New protocols hash/declare
the follower and feedback module; prompts are versioned. Optional validated measurements
survive P1/AFS action summaries; missing old data is not invented, outcomes/taxonomy unchanged.
CPU/ideal-kinematic and mock-loop regressions are separate from live G1/Luna evidence.
The first live validation is reviewed above; robust goal success remains unverified.
Preserve old archives/frozen campaigns and create
new comparisons; never resume them with changed code. See docs/ROBOT_NAVIGATION_FEEDBACK.md
inside scene2test. User remains focused on AFS; this is a narrow robot-internal follow-up.

## First live goal dwell option review (2026-10-02)

A user-run Luna/CUDA single-episode replay is verified VALID/FAIL at the 10-call
budget, with complete usage and MP4. Scene/XML/assets match the prior near-goal case,
but robot prompt/context/completion condition changed; it is NOT a same-condition
repeat or a new AFS/Random comparison. This time final distance was 6.27m and goal
dwell zero. All three navigation paths existed but following was turn-dominated near
spawn; then five move actions described lateral motion yet commanded all-zero velocity.
Recorded state commands agree; local typed parsing permits and preserves nonzero moves.
No falls, non-floor robot contacts or pushing were recorded. Goal hold never activated,
so live final-arrival/dwell success remains unverified despite working pipeline/diagnostics.
Operational taxonomy detected no supported family; do not invent collision/perception
labels or alter prior outcomes/coverage. Next narrow diagnostics: waypoint-following
stagnation and robot-side numeric-action feedback, not automatic paid retries or evaluator
invention of motion. See the goal dwell live-result workhistory. Preserve all evidence.

## Final navigation completion contract update (2026-10-02)

Opt-in `--navigation-completion goal_dwell_v1` adds robot-local pose hold after arrival
when GPT explicitly targets the final goal coordinate. Hold stays within that action's
requested duration and the simulation cap; no extra calls, time extension or post-budget
grace. Drift outside the goal region resets dwell and resumes following. Intermediate
targets, no-path and stop retain existing behavior; default is position_only_v1.
GoalEvaluator/task contract remains unchanged. New policy context and hashed protocol
declare completion behavior and goal progress; default mode is NOT exact old prompt/code
replay. `terminal_diagnostics.json`, action-end progress and report expose dwell/budget
interaction without relabeling outcomes. Optional action-end dwell fields survive AFS
evidence summarization; old missing measurements remain absent, not zero or new taxonomy.
Campaign/CLI/regression wiring freezes and checks the completion condition. Regression
inherits source behavior unless explicitly overridden; never resume old frozen suites
under changed code. CPU/scripted tests and read-only three-case regression planning are
verified; a first live run is reviewed above, but actual goal-hold validation is pending. Preserve old results. See
`scene2test/docs/GOAL_NAVIGATION_COMPLETION.md` for bounded next-run commands.

## Completed obstacle pilot review (2026-09-29)

A user-run Luna/Luna v3 pilot completed 6 valid rollouts per arm, zero exclusions,
120 robot calls and 2 AFS requests with fully observed usage. AFS 6 FAIL vs Random
5 FAIL/1 PASS gives observed relative Gain 20%, not statistical superiority: single
seed, one failure difference, and unique failure scenes are 5 each (AFS includes
one repeat). One operational obstacle_interference rule fired; six-family coverage
is still partial, not 4/6. Success-side probes widened the corridor then moved a
static block toward a wall. The latter got within 0.119m but failed the frozen goal:
navigate_to stops at 0.12m; the tenth action ended with only 0.775s of required 1s
goal dwell. Random PASS had a spare call and completed dwell during inference hold.
Audit this final-action/dwell interaction before broad conclusions; never relabel
old outcomes or silently change budgets. No AFS PASS/bracket yet. Near-goal repeats,
explicit terminal-contract review and evidence-backed follow-up are next priorities.
See the completed-result workhistory. This was read-only review, not a new paid run.

## Output token default update (2026-09-29)

User requested removal of the client-side max-token ceiling. Robot velocity/goal/push
and LLM AFS requests now omit `max_output_tokens` by default, including terrain/expanded
CLI defaults. Explicit legacy CLI/helper caps remain opt-in only. New robot protocols
record a null per-call cap and `provider_default_no_client_cap`; provider/model limits
still apply, so this is not unlimited generation. Keep inference effort, call budgets,
timeouts, outcome rules, incomplete-response diagnostics/usage and no-retry behavior
unchanged. Preserve historical caps/results; frozen old campaigns cannot resume with
changed source. No paid validation is implied by offline/mock tests.

## Usage audit, operational taxonomy and executable regression (2026-09-28)

`call_usage.py` merges manifest-bound decisions, pending responses and per-call journals
by observation ID/response ID; conflicts stay unknown and do not change goal outcomes.
New goal protocols hash `clear_path/obstacles.py`. Preserve old protocols and checkpoints;
use new offline reports rather than rewriting old campaign accounting.
`--with-taxonomy` enables `goal-behavior-v1`: terminal stagnation plus static navigation
contact, repeated blocked planning near obstacles, or sustained projected goal occupancy.
PASS never becomes failure; multiple detected families remain primary UNKNOWN. These
are operational temporal associations with UNCONFIRMED causality, not impossibility proof.
Unreachable/human-risk/perception remain UNSUPPORTED. Coverage reports a lower bound and
partial status, not complete six-family measurement or achieved 4/6. New obstacle campaign
opts in and feeds only its own arm/seed's classified evidence to AFS; v1/v2 default none.
`tools/run_behavior_regression.py` now has offline plan/init and explicit run --live,
fixed attempt budgets (excluded attempts consume slots), frozen scene/task/budget/assets,
current-code version comparisons, SQLite intent/checkpoints, conservative pending recovery,
no automatic resend, separate PASS/FAIL/mixed/excluded summaries and MP4 links. Source
archives and AFS budgets/history remain unchanged. This is not exact historical-code replay,
portable external-asset restoration, or a statistical improvement claim. Original archives
must be accessible for memory-index replay. New regression/AFS GPU/API validation remains
pending; CPU/synthetic tests and read-only analysis of saved real archives are separate.
See `scene2test/docs/BEHAVIOR_TAXONOMY_AND_REGRESSION.md`. These updates supersede historical
"no detector/no regression runner" statements below. No GIF or implicit 120s cap.

## Multi-obstacle goal-agent AFS update (2026-09-28)

Opt-in `clear-path-obstacles-v3` extends corridor-v2 with two STATIC oriented blocks:
17 continuous axes total (existing five plus each block's X, lateral fraction,
local X/Y size, height and yaw). See `scene2test/docs/OBSTACLE_AFS.md`.
Disjoint X bands and rotated-AABB-based lateral placement prevent initial overlap;
there is no path-based rejection sampling. Width/size/yaw can also move block Y.
The graph stores world AABB size plus explicit local extents/rotation. XML, map,
robot observations/contact logging and preview share the same scene-owned IDs.
Maps/planner conservatively block low objects too; this does not add stepping/jumping.
Only the existing box is movable/pushable. No changes to robot decisions, goal,
action executors, planner or outcome semantics. This is NOT arbitrary maze/room/
terrain loading. Generic procedural/terrain support remains a separate backend.
Campaign sampling, constrained LLM axis schema, geometry audit and observed brackets
support v3. Extra scene-owned nodes are verified before normalization; residual
physics/robot differences still forbid brackets. New config uses Luna/Luna, 6+6
valid/max attempts, up to 120 robot calls + 2 AFS calls; no implicit paid execution.
CPU geometry/real-asset composition and synthetic integration are tested. One user-run
Luna/CUDA slalom fixture now has validated goal PASS evidence: internal plan_path +
navigate_to, no push, no recorded falls/non-floor robot-world contacts. This is one
development fixture, not an AFS-picked case or general success-rate/Gain evidence.
Review found pending-completed response usage omitted from the old decision-only token
sum and standalone source provenance missing obstacles.py. Both are now fixed for new
measurement/protocols as described above; old source evidence/outcomes are preserved.
Old v1/v2 scene outputs remain compatible, but code frozen
campaigns require their original environment; never bypass drift or relabel domains.
Next: budget-reviewed live validation of the new taxonomy/regression path and obstacle AFS;
no need to wait for comparison pilots to finish before development. Six-family coverage is unknown.

## Explicit AFS evidence-reference recovery (2026-09-28)

Behavior request schemas now constrain evidence_refs to the supplied ID enum;
host validation still rejects unknown IDs and records unknown/allowed values.
`run_afs_benchmark.py recover-evidence-refs` is offline/dry-run by default. It only
supports a stopped first proposal with one explicitly mapped, uniquely identifiable
single-character deletion in a hex evidence ID and completed VALID cold starts.
Apply requires a reviewed plan hash and a new disjoint output directory. Original
DB/request/response/rollouts remain unchanged; inherited costs/budgets are retained.
Source SQLite/WAL are queried from a private temporary copy under its campaign lock.
Only recovery-specific code changes are migrated and audited; unrelated code,
robot/resource/dependency changes are refused. The new fork remains code-frozen.
Inherited rollout paths still reference the original folder: preserve it.
Reports mark operator-assisted continuation and suppress prospective Gain claims,
even on completion. This is not automatic fuzzy correction or general drift bypass.
See scene2test/docs/AFS_EVIDENCE_RECOVERY.md. No paid retry or robot launch is implied.

## AFS search-quality update (2026-09-28)

User priority is AFS, not improving the robot as a prerequisite. New local campaigns
default to `selection_policy=hypothesis-v2`; see `scene2test/docs/AFS_SEARCH_V2.md`.
Feedback keeps the full bounded action timeline and selects up to 12 event/phase
details across the episode, instead of truncating the beginning. Selection audits
record purpose, LLM hypothesis order, endpoint novelty, exclusions and anchor evidence.
Behavior cooldown ignores support-contact count noise and uses ordered tool states,
coarse goal progress and audited object motion. These patterns are NOT failure families
or causal labels. Fixed exploration/repeat slots and equal budgets remain; boundary
slots first repeat mixed outcomes, then use an observed bracket or request a hypothesis.
Robot code/goal/prompt/budget and Random distribution are unchanged by this work.
With-memory reports add first success/bracket milestones, empirical bracket history,
pattern repetition, per-hypothesis measured outcomes and observed costs. Verified
INCONCLUSIVE archives retain available decision usage without becoming goal failures.
Existing checkpoints/evidence are not rewritten. New code needs a new frozen campaign;
novelty-v1 retains distance-first ranking only, not old-code bitwise reproduction.
Offline Luna evidence confirms late blocked endpoints/recovery reach the new context;
synthetic regressions pass. No new live AFS/GPU success or superiority evidence is implied.
Next AFS work: budget-reviewed new pilot, selection-quality evaluation, then geometry/
taxonomy and executable regression assets. Arbitrary historical-anchor LLM output,
calibrated failure probabilities and automatic causal adjudication remain open.

## Corridor geometry AFS update (2026-09-28)

Opt-in `clear-path-corridor-v2` adds corridor_width_m (1.6–4.0m) and
box_lateral_fraction (-1..1) to the three physics axes. This is a straight corridor
without v1's side bay, not a general maze/terrain loader. Fixed box dimensions/X,
spawn/goal, robot planner and action capabilities remain unchanged. Box Y equals
fraction * (width/2 - 0.55 - 0.05); width changes also move Y when fraction is nonzero.
See `scene2test/docs/CORRIDOR_AFS.md`. The existing campaign adapter now supports this
five-axis domain for Random/AFS proposal, novelty, observed brackets, repeats and resume.
Request schemas restrict axes per domain; v1 defaults and standalone suite remain three-axis.
SceneConfig/XML checks precede v2 campaign validity; only audited scene-owned nodes are
normalized for geometry pairing. Other robot/physics differences still forbid brackets.
Goal runner saves initial SceneGraph/map artifacts but supplies no reference route to policy.
Static no_path is not a goal FAIL or manipulation impossibility; no such filtering is added.
`tools/preview_corridor_scenes.py` creates PNG/HTML development previews, optionally
audits real G1 assets on CPU. No API/GPU inference or robot success is implied.
`config/behavior_afs_corridor_luna.json` is a NEW Luna/Luna campaign: six valid/six max
attempts per arm, two paired cold starts, up to 120 robot calls + two AFS proposals.
New geometry and synthetic wiring are locally tested; live Luna/G1 success is unverified.
One user-run live Luna wide-corridor archive passed integrity/goal checks as a valid
10-call budget FAIL. CUDA walking and all ten API actions ran; no falls or non-floor
robot contacts were recorded. Tight static routes plus gait tracking/hold deviation
led to blocked-start planning feedback, one recovery and another blocked endpoint.
This is not AFS/Random comparison or a successful baseline. See the workhistory review;
robot-local navigation robustness and verbose feedback input cost need attention.
Code changed: do not bypass frozen-source drift checks to resume pre-change campaigns.
Next: budget-reviewed AFS pilot including success-side probes, then broader geometry;
robot improvement is not a prerequisite. No jump/grasp skill added.

## Failure-discovery measurement priority (2026-09-27; initial P0/P1 and local P2 implemented)

Follow `scene2test/docs/FAILURE_CASE_MEASUREMENT_PLAN.md` for the user-requested focus on
AFS prioritization and behavior validation/regression assets from `.blueprint/Failure_Case_Goal.md`.
Targets: FDR >=30%, relative gain over Random >=20%, evidence-backed coverage >=4 of 6 types.
These are research targets, not achieved results. `tools/measure_failure_discovery.py` now imports
goal-agent-v5 archives offline and writes separate JSON/CSV/HTML measurements. See
`scene2test/docs/FAILURE_DISCOVERY_MEASURES.md`. Manifest/contract checks, duplicate exclusions,
FDR/Gain and a detector-gated six-family coverage calculator are implemented. The importer has
no family detectors, so real coverage remains unmeasured. Imported method/domain labels are
declarations, not proof of a prospective fair benchmark. Automated regression execution remains planned.
P1 `--with-memory` adds time-resolved phase/contact/fall/action evidence, audited box motion,
success/failure/mixed repeat cases, same-condition single-axis observed brackets, and selective
hashed evidence bundles/reproduction templates. See `docs/BEHAVIOR_FAILURE_MEMORY.md` inside scene2test.
Observation windows include inference, not an invented exact action start. Missing measurements
remain unsupported/unknown; events do not assign failure families or causal labels.
MP4 is referenced by default, optionally copied with `--bundle-video`; GIF/API transcripts are excluded.
External robot code/assets are listed but not bundled/verified; this is not an executed regression suite.
Keep goal outcome separate from contact/safety/behavior events;
unknown/unsupported measurements are not zero. Compare equal valid rollout budgets including
cold start and repeats, disclose invalid attempts/cost, and do not count legacy guard stops or
incomplete archives as goal failures. The original v1 behavior-AFS goal-agent supports three
physical axes; see the opt-in corridor update above for the supported five-axis extension.
Expanded terrain generator support is not goal-agent backend support. Reuse client
contracts/storage/archive via adapters without making server rewrites or robot skill development
prerequisites. P2 `tools/run_afs_benchmark.py` now provides opt-in local campaign init/run/status/report/resolve
with frozen config/code/resources, per-method/seed valid budgets, P1 feedback into the existing LLM
proposal schema, full-domain Random, separately charged paired cold start, exploration/repeat/boundary slots,
SQLite intent + atomic observe checkpoints, and conservative ambiguous-call recovery (no automatic resend).
See `scene2test/docs/BEHAVIOR_AFS_CAMPAIGN.md`. Reuses ClientRepository transactions and observation contracts;
this local scene adapter is NOT an HTTP registry plugin. Interrupted/legacy/incomplete records remain excluded.
Initial validation used synthetic archive/fault-injection tests and real-resource initialization.
A reviewed partial live pilot (2026-09-28) now has four valid goal FAILs per arm and two validated
LLM success-side proposals. Mass reduction followed by box-friction reduction was executed; one
light-box rollout moved the box about 0.19 m but did not reach the goal. This is closed-loop execution
evidence, not a complete benchmark, a PASS/FAIL boundary, or AFS superiority. The declared eight-valid
budget per arm remains incomplete; coverage is unmeasured. Infrastructure exclusions are preserved.
The earlier INCONCLUSIVE token-loss gap is addressed by the search-quality update above
for verified archives with recorded usage. Unreturned calls/incomplete manifests and old
checkpoint costs remain unknown. Growing robot feedback history remains a robot-side cost item.
P2 now revalidates pending proposal evidence/context on resume and after inference, and checks frozen
code/resources again before launch. Condition-drift stops commit atomically with observations; usable
saved responses cannot be abandoned before validation. Spawned children are reaped on metadata/wait
errors. P0 excludes recorded API/policy call counts exceeding the declared episode budget.
`tools/run_afs_pilot.py` wraps initialization/resume, two initial rollout checks, remaining fixed-budget
execution and P1-inclusive reports. Default is plan-only; --live plus a local key permits paid runs.
It stops on the first newly observed excluded rollout or operational error, never on a valid goal FAIL,
and never auto-resolves/resends ambiguous operations. Each invocation has separate pilot_runs logs.
Example config is 8 valid rollouts per arm, max 12 attempts per arm, up to 240 robot calls + 8 AFS requests;
live execution requires explicit --live and a locally set API key. No implicit paid launch from init/report.
An opt-in `config/behavior_afs_luna_smoke.json` sets both robot and AFS to gpt-6-luna:
three valid rollouts/three total attempts per arm, two paired cold starts per arm,
at most 60 robot calls plus one AFS proposal. This tests first-proposal wiring, not the
full strategy cycle or model/search superiority. Episode settings remain unchanged.
Default Astra config and existing campaigns are preserved; do not resume an Astra campaign
with changed models. Luna synthetic campaign wiring tests pass; live campaign validation
remains open. The separate corridor robot run described above is not campaign evidence.
See `scene2test/docs/LUNA_PILOT_AND_SCENARIO_PLAN.md` for commands and capability boundaries.
Next: budget-reviewed live pilot, then taxonomy/geometry and regression execution. Core/media manifest
separation/finalization improvements, family detectors and additional behavior measures remain open.

## Goal-outcome AFS implementation (2026-09-26)

User defines failure as the evaluated robot system not achieving its original goal
using any method available to it, under a declared fixed episode budget. Follow
`scene2test/docs/GOAL_OUTCOME_AFS_DESIGN.md` for the design and
`scene2test/docs/GOAL_OUTCOME_AFS_IMPLEMENTATION.md` for implemented scope.
It specifies independent goal evaluation, recoverable contact/fall/skill events,
and behavior-informed success-side/boundary/contrast/novelty/repeat exploration.
The isolated goal runner defaults to goal_outcome_v1: contacts/falls/skill errors
are recoverable observations; valid noncompletion at budget/robot stop is FAIL,
infrastructure interruptions are INCONCLUSIVE. legacy_guarded is opt-in and is not
bitwise reproduction of old code. Behavior AFS v2 accepts 1–4 one-sided/paired spaces,
reserves repeats/exploration and requires new-profile PASS/FAIL anchors. Preserve old
outcomes; never relabel interrupted old traces as completed goal-only trials.
Tests exercise CPU MuJoCo with scripted state/controller doubles, not new GPU/VLM
success evidence. Local three-axis auto-campaign/resume now has an initial P2 implementation;
new geometry and image-based AFS remain open.
The isolated goal runner records MP4 only: GIF encoding and full-frame accumulation
are disabled by user request after a suspected GIF-finalization OOM. Preserve old artifacts.
Do not restore the removed default120s limit. Static no_path does not prove a scene
unsolvable when manipulation is available. Robot capability development remains
separate from AFS evaluation/search work.

Last refreshed: 2026-09-28 (UTC); earlier capability notes retain their historical scope.


## G1 scene-search pilot update

`procedural_world/search.py` and `tools/run_scene_search.py` implement a separate trusted
local scene-bundle search pilot: bounded obstacle translation, graph/map/XML regeneration,
Random/Sobol and feedback-driven ExtraTrees AFS, equal valid-rollout budgets and resumable
HTTP submission. This does not add an adaptive plugin to failure_client's general method
registry or a remote scene-mutation API. See scene2test/docs/G1_SCENE_SEARCH.md for protocol
and claim boundaries. A small single-seed experiment cannot establish AFS superiority.

## G1 navigation integration update

simulation_server now supports navigation@1.0 for registered procedural-world bundles.
Trusted local ingestion verifies artifacts and derived graph/map, then the worker composes
static geometry with the G1 XML while checking joint/actuator order and geometry identity.
The gt-waypoint-v2 baseline uses ground-truth pose/map, lookahead tracking and static
clearance checks over the existing CUDA GR00T gait. Five staged fixtures/worlds have
recorded GPU goal-reaching evidence; this is not a general random-world success rate.
See scene2test/docs/G1_NAVIGATION.md. Keep legacy stand/locomotion separate. No LLM,
sensor navigation, dynamic obstacle avoidance or AFS integration is implied. Preserve
all initial failures and final artifacts. Runtime scene changes require new revisions.

## Procedural world update (historical standalone generator scope)

scene2test/src/procedural_world now generates seeded static maze/room environments,
legacy-schema SceneGraphs, conservative circular-footprint navigation maps and
standalone robot-free MuJoCo XML from one SceneSpec. See docs/PROCEDURAL_WORLDS.md
inside scene2test. This is not Server scene registration, G1 navigation, sensor
perception or adaptive AFS integration. Default footprint values are assumptions.
Maintain shared object IDs/world-meter coordinates/revisions across outputs. Preserve
the separate legacy Panda path. Next integration is scene loading with G1 assets,
then navigation/path following and scene-based AFS. Do not postpone scene integration
behind unrelated dynamics-only search or infer full-body feasibility from a 2D path.

## Current scope update (supersedes historical scope and priorities below)

scene2test now also contains a G1/MuJoCo simulation_server and failure_client.
Client orchestration, recovery and exports exist, but built-in methods do not
implement adaptive G1 search; legacy adapters import precomputed candidates.
Legacy Panda AFS/LAM and local mesh-backed scene3d remain distinct execution paths.
G1 CUDA locomotion has saved validation evidence. Optional path_hold is a separate
controller condition, not proof of general navigation or VLA capability.
app.py remains local-AFS oriented. g1-local-nav is independent: obey its AGENTS.md
and do not merge it with scene2test. Record work in .workhistory.
Read scene2test/docs/PROJECT_INTEGRATION_AUDIT.md and PROJECT_ROADMAP.md for current
scope and priorities: valid-rollout budgets/provenance, adaptive search and fair
baselines, service/scene extensions, reporting. The one-project statement and
priority backlog below describe historical Panda work, not the whole repository.

## What this repository is

This workspace contains one Python project, `scene2test`, for automated regression and
failure-condition discovery for robot pick-and-place behavior. It represents workspaces as a
shared 3D `SceneGraph`, perturbs or augments scenes, runs a Franka Panda in PyBullet, evaluates
continuous safety/robustness margins, and records counterexamples and reports.

The project has two related pipelines:

1. The original Scene2Test Active Failure Search (AFS) pipeline searches an 8-dimensional scene
   mutation space with a learned surrogate and an acquisition function.
2. The v2 LAM-Guided pipeline observes a replaceable action policy, profiles its behavioral
   weaknesses, generates policy-conditioned 3D failure cases, reruns the policy, and refines
   PASS/FAIL boundaries.

This is a simulation/research prototype. It does not control real robot hardware, train a VLA,
or perform dynamic grasp/contact validation in its main oracle.

## Repository map and source of truth

- `README.md`: best high-level overview of both pipelines.
- `.blueprint/00_blueprint.md`: original problem statement and AFS design intent.
- `.blueprint/01_blueprint.md`: LAM-Guided extension design intent.
- `scene2test/`: executable project; run commands from this directory.
- `scene2test/src/`: implementation. Prefer code and tests over stale prose when they disagree.
- `scene2test/config/`: robot, task, oracle, scene generation, and LAM-guided settings.
- `scene2test/tests/test_p1_*.py` through `test_p13_*.py`: phase completion scripts. Many are
  executable `main()` scripts rather than pytest-discovered tests.
- `scene2test/docs/GAP_ANALYSIS.md`: most useful implementation-vs-blueprint audit, but it was an
  untracked work-in-progress when this memory was written.
- `scene2test/PLAN.md`: P0-P10 implementation history; `EXECUTION.md` and
  `LAM_GUIDED_WORKFLOW.md` document v2 usage.
- `scene2test/data/` and `scene2test/reports/`: scenes, run logs, generated meshes, GIFs, and
  derived reports. Treat most timestamped outputs as generated artifacts, not hand-authored code.

There was no pre-existing `AGENTS.md`. `CLAUDE.md` was empty at the time of inspection.

## Original AFS pipeline

The central contract is `src/scene_graph.py`: every procedural or RGB-D source should emit the
same `SceneGraph` containing support surfaces, objects/roles, relations, unknown regions, and
metadata. Downstream code is intended to be source-agnostic.

The implemented flow is:

`SceneGraph -> 8D mutation sampling -> 16D feature vector -> PyBullet kinematic check -> six-margin Physical Oracle -> surrogate training -> acquisition/top-K diversity -> repeat -> logs/reports`

Important implementation facts:

- Mutation dimensions: `target_dx`, `target_dy`, `obstacle_angle`,
  `obstacle_dist_to_target`, `human_zone_x`, `human_zone_y`, `tray_occupied`, and
  `occlusion_ratio`.
- The feature vector is actually 16D: eight scene features plus the normalized eight mutation
  parameters. Ignore the stale 39D statement in `scene2test/README.md`.
- `RFSurrogate` (ExtraTrees regressors, one per output) is the default; `GPSurrogate` is the
  comparison implementation. They predict six margins, not a direct PASS/FAIL label.
- The six margin keys are `reach`, `clearance`, `collision`, `safety`, `goal`, and `perception`.
  Robustness is their minimum. Verdict priority is safety `BLOCKED`, then `FAIL` for robustness
  <= 0, `WARN` within `decision.warn_band`, otherwise `PASS`.
- AFS cold-start uses LHS/boundary seeds until `min_train_size` (default 15), then scores a
  candidate pool (default 1000) using failure probability, uncertainty, safety priority,
  novelty/redundancy, coverage, and diverse top-K selection.
- Modes are `cold`, `warm`, `random`, and CLI-level `compare`. Warm mode reuses a cross-scene
  surrogate from `scene_library.py`.
- The main simulator/oracle is deterministic and kinematic (IK and geometry queries). The
  animation tool has a separate `--physics` mode for visual observation, but that does not make
  the main search oracle dynamics-aware.

## LAM-Guided v2 pipeline

The implementation is mostly isolated under `src/lam_guided/` and is gated by
`lam_guided_failure.enabled` or CLI `--enabled`, preserving the original AFS path.

The conceptual loop is:

`observe policy -> encode behavior -> profile vulnerability -> generate/filter failure candidates -> execute -> Policy + Physical Oracles -> FailureMemory -> boundary refinement/reporting`

Important implementation facts:

- `src/policies.py` provides the `ActionModel` protocol, deterministic `RuleLAMProxy` baseline,
  and noisy heuristic `MiniActionModel`. The mini model is not a neural LAM/VLA.
- Current behavior representation has 8 features and the vulnerability profile has 7 axes.
- Implemented failure families are `semantic_distractor`, `occluder`, `path_blocker`, and
  `human_safety_intrusion`.
- `PolicyOracle` detects policy-level failures such as wrong-object grounding/picking, safety
  noncompliance, instability, and recovery failure. A separate physical check evaluates margins.
- `GeneratedAssetBank` supports procedural assets and offline mesh assets. `asset_gen.py` can use
  Shap-E optionally and falls back to procedural defaults when unavailable.
- Boundary refinement currently targets semantic-distractor distance and path-blocker offset.
- `src/policies_vla.py` plus `src/lam_guided/closed_loop.py` define an RGB closed-loop policy path,
  a GPU-free `StubReachPolicy`, and a lazy-loading `OpenVLAPolicy` wrapper. The wrapper existing
  is not evidence that the real OpenVLA-7B model has completed an end-to-end run.
- Current LAM-guided candidate selection is independent of original AFS. In the actual loop it
  assigns `family_prior + coverage` scores and then performs family-stratified selection. An
  `_score_candidate` helper mentions novelty/redundancy but is not used by `run()`.

## Known gaps and claim boundaries

Do not describe the following as complete without new evidence:

- Track B is not a production RGB-D perception pipeline. The GT path copies supplied object
  poses; the mask path has a known pixel-to-valid-point indexing bug; object detection,
  segmentation, role inference, semantic extraction, and AFS/LAM end-to-end wiring are absent.
- LAM-Guided candidates are not merged into the original AFS pool, and guided scoring does not
  reuse the AFS surrogate or uncertainty.
- Blueprint families 5/6 (`destination_confusion`/occupied and grasp-difficult objects) are not
  implemented.
- Action subgoals are produced but not sequentially executed as reach/grasp/place/release; the
  open-loop rollout is effectively a selected-object IK reach, so full place/release success is
  not validated.
- The LAM-Guided A/B/C comparison needed to quantify guided gain has not been implemented.
- OpenVLA-7B real-model E2E validation, rendering-domain-gap mitigation, and Franka/WidowX
  embodiment calibration remain open.
- Reported experiment numbers in markdown are prototype results, not a substitute for rerunning
  the relevant command with a recorded environment and seed.

The priority backlog captured in `docs/GAP_ANALYSIS.md` is: first quantify LAM-guided gain, make
the pixel-to-SceneGraph path genuine at least with PyBullet segmentation, and run real OpenVLA;
then add missing families/full subgoal execution/occlusion boundaries; finally merge AFS and
guided search and expand features.

## Environment and commands

- Package metadata requires Python `>=3.11`; Ruff targets Python 3.12. Root documentation says
  Python 3.11 while `scene2test/README.md` says 3.12+, so treat `pyproject.toml` as authoritative.
- Dependency manager: `uv`. A project-local `.venv` existed during inspection.
- Apple Silicon uses `pybullet-arm64`. Prefer headless runs with `PYBULLET_MODE=DIRECT`; macOS
  PyBullet GUI rendering is unreliable. GIF/video output additionally needs ffmpeg.
- Core install: `cd scene2test && uv sync`; optional extras are `--extra vla` and `--extra gen3d`.
- Generate scenes: `uv run python src/scene_generator.py --n 20 --output-dir data/scene_library --seed 0`.
- Run AFS: `PYBULLET_MODE=DIRECT uv run python src/active_failure_search.py --scene data/scene_library/scene_00001.json --mode cold --rounds 5 --tests-per-round 20`.
- Run LAM-guided: `PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py --scene data/scene_library/scene_00001.json --action-model mini --rounds 4 --batch-size 8 --enabled`.
- Dashboard: `uv run streamlit run app.py`.
- Broad pytest command: `PYBULLET_MODE=DIRECT uv run pytest tests/ -v`, but also run the phase
  scripts directly when validating P1-P13 because pytest does not discover all `main()` checks.
- Running integration scripts writes timestamped logs and reports. For read-only exploration or
  review, do not run them unless those workspace mutations are acceptable.

## Working-tree caution and active direction

Always inspect `git status` before editing and preserve user changes and generated evidence.
When this memory was written, `main` matched `origin/main` but the worktree was dirty with
user-owned LAM/VLA integration work plus new logs and `docs/GAP_ANALYSIS.md`. The code changes
were separating LAM selection from VLA execution in `RolloutTrace`/`PolicyOracle`, adding a
`lam_vla` execution mode to `lam_guided_loop.py`, and changing OpenVLA Apple Silicon handling to
MPS float32 with float64-buffer patching. Do not revert or overwrite that work.

Refresh this memory when architecture, validated capabilities, or the gap backlog materially
changes; avoid recording transient run IDs or machine-specific generated paths here.


## Terrain course work in progress

New procedural_world/terrain*.py, config/terrain_course.yaml and setup_terrain_scenes.py
provide composable slopes/stairs/friction/roughness/bottlenecks/variable-size boxes with
2.5D maps and traversable_surface graph nodes. Isolated run_terrain_validation.py and
simulation_server/terrain_worker.py test CUDA gait with ground-relative height and support
contact metrics. Generation is not proof of G1 traversability; planning limits are assumptions.
Legacy common worker/navigation_worker are unchanged. IMPORTANT: common-server terrain
registration guards/integration are incomplete pending approval of shared worlds.py changes.
Do not register terrain bundles in the legacy navigation server. Use the isolated runner.
See scene2test/docs/TERRAIN_SCENES.md and .workhistory/2026-09-08_terrain_scene_setup.md.
