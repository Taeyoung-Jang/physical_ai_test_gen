# Scene2Test workspace memory

## System-interface taxonomy candidates and component separation (2026-10-19)

User approved defining types for Agent/VLA/control stack as well as body failures.
New opt-in offline system-twelve-v1 adds goal_endpoint_rejection and
subgoal_completion_loop;FAMILIES6/EXPANDED10/defaultAFS profiles unchanged.
First requires VALIDFAIL/budget/finaloutside/repeatedexactgoalblocked_endpoint>=2
and final acceptedaction samegoalblock;second terminal>=3consecutive successful
navigate subgoalarrivals outside taskgoal,>=2samepoint(.02m). No normaldistinct
waypoints/singleblocked/PASS/exclusion/missingdata credit. Explicit middle
stale_rejected notphysicalexecution or missing acceptedtoolresult;trailingreject
doesnotpromote earlieraction toterminal. Oldprimary/ambiguity retained,newunique
onlyfallback. Repeatedintentionalturns diagnosticonly,not locomotionstall/newtype.
failure_layers preserves observedinterfaces+actual recordedAgent/planner/controller
contract;overallrootcause/Agent/planner/controller/body UNCONFIRMED,VLA notseparately
instrumented. Direct policy_state_contract diagnostic stores rawline/hash when
observedversion!=returnedstateversion+stale_rejected;notanotherfamily or FAILcause.
Actualattempt9 observation4/modeloutput5 confirms interfaceviolation,notVLA/bodyfault.
tools/reanalyze_system_failures.py accepts explicitruns or latestverifiedreportsnapshot
includingREADY,verifiesmanifest+savedepisodeidentity,neveropenssourceDB. Newseparate
report compares10/12,hashesdetectorcode,no sourceverdict/budget edits orprospective
targetclaim. New12notyetconnectedonlineAFS/schema;newconditionintegration separate.
120CPUtests pass18.85s,Ruff/format7files+diffclean. No paid/API/GPU/robot/newcampaign,
commit/push. See docs/EXPANDED_FAILURE_TYPES.md system-layer section. Prior frozen
session remainspreserved/source-drift;neverdirectresume/bypass aftersourcechange.
Final actual10attempt snapshot reanalysis saved runtime/system_failure_reanalysis/
20261019T155051_917992Z/report.html:9VALIDFAIL/1excluded unchanged;old10=3types/
5unclassified,new12candidateprofile=5types/3unclassified. Onlyattempt6 adds
subgoal_completion_loop,attempt9 adds goal_endpoint_rejection;attempt9 state4->5
contractviolation diagnosticonly. attempt3 endpointobservation secondary retains
manipulationprimary;attempt7 turns diagnosticonly. Original1475filehashesunchanged.
This is retrospectivecandidateclassification,NOT original4type milestone orGain.

## One-command trajectory smoke script (2026-10-19)

tools/run_trajectory_smoke.sh --dry-run prints only,no files/API/robot;--live runs
fresh10callcontrol using originalattempt4scene,currentretryrobotcode,then verified
VALIDPASS/FAIL+manifest gate,then new trajectory AFS atmost1request/1newattempt.
Total invocation<=20robotpolicycalls+1AFS;notfull12validbudget. New timestampPIDroot
runtime/trajectory_feedback;run.log retained and projectzz_log replacedlatest.
Explicitlive/keyrequired,existingoutputrefused,stageerrors/excludedcontrolstop,
noautomaticwholeepisoderetry/resume. Same TCP pre-send retry policy retained.
Script rerun starts freshpaidcontrol,notoldsessioncontinuation. Source/outputenv
AFS_TRAJECTORY_SOURCE_SCENE/AFS_TRAJECTORY_OUTPUT_DIR;fixedtrajectoryconfig.
Tests fakeuv+isolatedproject so actualzz_log preserved;embeddedPython+Bash syntax
checked. No paid/API/robot executed by Codex while preparing script.

## Trajectory and prediction-gap feedback opt-in implemented (2026-10-19)

User approved feedback-only first stage,NOT host ranking change or paid execution.
SearchBudget.pattern_feedback defaults off;trajectory-v1 requires cause-review-v3.
New trajectory_feedback.py summarizes goal-endpoint block/repetition,accepted actual
progress>=.05m peraction(summaryheuristic only),stagingarrival,manipulationrequest/
toolrejection,action-result goalentry/dwell+finalexit,last3actions/fullratefinalstate.
Missing/partial absence staysUNKNOWN;localrejectedpush still request,notphysicalproof.
Predicted type compared to fixed detectorstatus+gateobservations+actualprimary;
NOT_DETECTED notcausalrefutation and unclassifiedFAIL staysFAIL. LLM existing
change_rationale/measurement_plan asked why environmental change yields different
behavior;no newschema/extraLLMcall/rankbonus/hardban/label or goal/budget changes.
All supplied-memory episodes accumulated beyond historylimit,condition/taskbudget/
origin/current-historical separated;groups<=8/currentfirst,reps<=2,checks<=4.
Aggregate unseen provenance notnew permittedanchor/ref;alloldguardssurvive.
Context+selectionaudit/HTML savefeedback. New afs_trajectory_luna.json freshdev
proposal12valid/16attempts/20AFS/4peraxis/0repeats/Luna,NOToldsessionextension.
Actual readonly7archive comparison:10call5VALIDFAIL allblockedgoal+progressbudget
pattern;15call2diagnostics separategroup,attempt5entry.19sdwell/finaloutside.
587originalfilehashesunchanged. Pure actual10callcontext built4details/all5summary,
three predicted goaloccupied/collision/obstacleinterference NOT_DETECTED;request
285719UTF8bytes(notwiretokens/cost),nooutputtokencap/API/robot. No4types/Gainclaim.
Regression167CPUtests pass48.60s;final15trajectorytests pass9.39s inclsavedresponse
resume/noresend,defaultoff,partialdata,conditionbudgetsplit,hostunchanged,audit.
Ruff/format/diffclean. No runtimefork/newsession/paid/API/GPU/robot/commit/push.
Old frozen campaigns alreadydrift aftertransportretry:never directlyresume or bypass.
See AFS_REFERENCE_RECOVERY_AND_EVALUATION.md trajectory section. Next new-condition
development execution must be explicitly prepared; discovery quality notliveverified.

## Goal GPT pre-send connection retries implemented (2026-10-19)

User approved2retries after budget15diagnostic attempt4 DNS ConnectError at13th
API selection(12actions); INCONCLUSIVE preserved,attempt5 notlaunched. New goal
Journal opt-in connect_retries2: atmost3TCPattempts,samebody/clientID,backoff1/2s.
Only ConnectError/ConnectTimeout+trace connection.connect_tcp.failed+no send/response
allows retry. TLS/untraced/ambiguous/write/read/HTTP/schema errors stop unchanged.
Other legacy journals/no-journalcall remain0retry. Record per-attempt redacted
failure/retryschedule and final connection_attempts/retry_count/failurehistory.
Notextra robot actions/modelusage estimates. Goal protocol pre-send-tcp-retry-v1,
timingv2; HTTPread unchanged,runner deadline read+53 insteadread+30 allows23s
connection/backoff overhead. Goal/budget/token/simcaps unchanged; waitingphysics
unchanged. Existing frozen campaigns now source-drift:never bypass or directresume.
New budget15 diagnosis must use freshoutput;no paid/API/GPU/robot run this turn.
See docs/ROBOT_API_DIAGNOSTICS.md and tests/test_robot_connection_retry.py.
Final CPU regression117passed/3explicitGPUskipped29.18s(PYTHONPATH=.:src required
for existing tests package imports); Ruff/format7files and diffcheck clean.

## Timeout-aware development continuation implemented (2026-10-19)

independent_luna_v2 seed17 has2VALIDFAIL cold starts(manipulation_failure,
human_safety_risk),1excluded firstrobotcall api_timeout,3attempts/1AFSspent.
Old PASS-only transfer plus excluded-relief cooldown can deadlock with noPASS.
New opt-in anchor_policy=failure-diversity-v4 allows mechanism_transfer from
VALIDPASS/FAIL,challenge PASS-only,relief FAIL-only. Exclusions still consume
attempts/axisquota/cost but do not create/age VALID behavior cooldown. Exact
excluded scene forbidden automatic replay. Predictions never measured labels.
Per-invocation max_new_afs_requests added; continuation CLI defaults1AFS/1attempt.
prepare_continuation default dryrun; --apply creates separate audited development
fork,keeps original state/ledger/proposals/evidence and spent budgets,requires
pendingnull/finalized requests/API-timeout exclusion; only explicit sourceallowlist,
robot resources/runtime unchanged. Not original prospective evaluation,not Gain.
Actual dryrun passed:17 remaining21attempts/23AFS/18validneeded;29/43 unchanged
24attempts/24AFS/20validneeded. No API/robot run. Related151CPUtests passed43.13s;
final10continuation tests passed14.86s. See docs/AFS_REFERENCE_RECOVERY_AND_EVALUATION.md.
New tools/run_discovery_continuation.py; never directly resume old frozen v2 with
new sources or reset its budgets. Development output target independent_luna_v2_development.
Actual --apply completed at that target: original251files hashes unchanged;
new seed17 NEEDS_ATTENTION/excluded_rollout preserved deliberately,allowedintents
mechanism_transfer+relief,excludedscene1notreplayed. Resume ONLY new development
CLI --live --continue-after-exclusion --max-new-attempts1 --max-new-afs-requests1.
No paid execution performed; do not rerun prepare --apply on existing destination.

## Failure intent and mode output schema aligned (2026-10-19)

User approved preventive fix after independent_luna_v1 proposal0 stopped before
robot: all3saved candidates relief+cross_mechanism; requiredsuccess_probe. Shared
FAILURE_INTENT_MODES now feeds request schema and unchanged-semantics host guard.
Directed profiles bind candidate objects via refs/nested anyOf: relief=>success_probe,
challenge/transfer=>cross_mechanism; relief-only schema mode has singletonenum.
Prompt states exact allowedpairs including combinations; detailed hosterror names
intent/requiredmode/gotmode. Old nondirected range/local contracts unchanged.
No normalization/filtering/reproposal/threshold/budget/model/token/simcap changes.
Actual savedresponse passesOLDschema/rejectedNEWschema, sameLuna/nocap;224original
campaignfile hashes unchanged by read-only replay. Existing2coldFAIL/1AFSspent remain
frozen; no oldDB/response/protocol/budget edits or driftbypass. Cannot resumev1with
samecommand aftersourcechange; future newversionfreeze or separatelyreviewedrecovery,
NOT automaticallycreated. Final141CPUtests pass39.07s,Ruff/format4files+diffclean.
No paid/API/robot/newcampaign/commit/push. Tests and scope recorded in
AFS_REFERENCE_RECOVERY_AND_EVALUATION intent/mode section.

## Independent cold start evaluation runner implemented (2026-10-19)

User approved next implementation, not paid execution. New independent_discovery.py
DiscoveryEvaluation/IndependentSeed + tools/run_discovery_evaluation.py init/run/
status/report. Separate independent mode/request policy; per-seed empty history,
only own new episodes in AFS context. Controls bind config/provenance only. Fixed
uniform seed/index bootstrap attempts charged to valid/attempt/cost metrics;
exclusions STOP and explicit continuation advances, never resends. All bootstrap
excluded=>no_valid_cold_start_evidence; allFAIL uses existing relief rules, absence
of eligible anchor=>no_eligible_observed_anchor, no external PASS/Random fallback.
Coldstarts count in form-cycle index, not single-axis quota; reports disclose it.
Manifest v2 binds condition/geometry/origin/environment+driver hashes; old prep v1
must re-freeze. Seed DBs bind manifest; no recovery history or cross-seed import.
Predeclared sequential seeds, global invocation attempt limit, fixed valid target,
no metric-success early stop. All seed metrics and primary union reported; joint
target-at-complete remainsnull until alltargetscomplete; Gain deferred. No threshold/
robot/goal/model/token/simcap edits. Actual archived PASS read-only plan passes same
e8ec8119 condition, empty evalhistory,60valid/72attempt/720robot/72AFS upperbounds.
Final121CPUtests pass32.06s; Ruff/format8files+diffclean. All6 distinct bootstrap
configs compile; actual-environment /tmp offline init/report READY/0attempt/0AFS.
See independent_discovery_runner workhistory. No paid/API/GPU/robot/newruntimecampaign/
oldarchiveDB/outcome/budget edit/commit/push. Next newfreeze/init then one bounded
live coldstart, not old frozen-session resume. See AFS_REFERENCE_RECOVERY_AND_EVALUATION.

## Reference roles recovery readiness and evaluation preparation (2026-10-19)

User approved all planned work start, not paid runs. cause-review-v3 opt-in/new
afs_reference_roles_luna: explicit anchor_behavior_refs checked against selected
anchor and evidence_refs; analysis_evidence_id/behavior_refs can cite differentFAIL.
Legacy/v2 unchanged; same12valid/16attempt/20AFS/Luna300s. v3 sees human-goal domain
constraint. recover-anchor-refs defaultdryrun, --apply newauditedfork only: append
unique anchor ID ALREADY in evidence_refs to missingbehavior_refs; no value/role/
analysis/context rebinding or APIresend. Source state/ledger/protocol/hash/model/
usage/priorVALID/budget/resources/runtime bound; explicit sourceallowlist,nodeletion.
Actual040453 dryrun passes first human_lateral0;3attempts4AFS spent preserved,
9morevalid/13attempt/16AFS remain; NO actualfork/API/robot created. Fork staysv2,
NOT silentv3 migration. Originals+normalizedhash verified onresume. New readiness
audit10families/8rules,conditionsseparate:humanX3.65..4.35 vsgoalX7/r.25/exposure1
=>goalpose+humanexposure PROVEN_DISJOINT with1.4m gap; NOT wholefamily impossible.
Latest3FAIL audit still1manipulationtype. New evaluation plan/freeze manifest only:
seeds17/29/43,20valid/24attempt each,total60/72,720robotcalls/72AFS proposed,
external evaluation history EMPTY; actual4controlarchive planpasses e8ec8119.
execution_readiness BLOCKED_INDEPENDENT_COLD_START_RUNNER_REQUIRED: independent
runner NOT yetimplemented; re-freeze after driver code. New human domain NOT built.
Regression PASS+latestmanipFAIL plan2repeats each=>4attempts/40calls,notexecuted.
152relatedCPUtests pass36.26s,Ruff/format/diffchecks. No paid/API/GPU/robot orsource
archiveDB/outcome/budget edits/commit/push. See AFS_REFERENCE_RECOVERY_AND_EVALUATION
docs and reference_roles_recovery_and_evaluation_prep workhistory. FDR/4types/Gain
final evaluation remains unachieved; no development-history pooling or goal relabel.

## Opt in LLM episode review and detector contracts implemented (2026-10-19)

After031027 live3VALIDFAIL/1api_timeout excluded/0types, user approved retrospective
LLM analysis + detector exclusions. New feedback_policy=cause-review-v2 only with
expanded branch+breadth, config afs_cause_review_luna keeps12valid/16attempt/20AFS/
4peraxis/0repeat/Luna300s/history4. SAME request returns episode_reviews BEFORE spaces:
facts/actionversions, hypothesis, alternative, uncertainty, nexttest implication.
Latest shown episode+shownFAIL required; PASS analyzed as strategy, exclusions notFAIL.
Each candidate cites reviewed evidence + measurement_plan. Host checks IDs/outcomes/
versions/reflinks, not prose truth or causal certainty. Eight detector requirements/
exclusions/thresholds + actual measured terminal gates/humancontract supplied. Explicit
box_only/not_applicable collision plan individually rejected; valid alternatives kept,
allrejected uses existing boundedAFScap, no robotattempt/FAIL/Random. unknown remains
uncertain. Reviews saved in rawresponse/selectionaudit/report, never metric labels.
146related syntheticCPUtests pass incl savedresponse resume no resend; real latest
3FAIL+priorPASS read-only plan passes e8ec8119 condition, no session/API/robot created.
No model/robot/goal/evaluator/threshold/tokencap changes. No extra analysis API call,
but more output can cost tokens. Actual discovery improvement unmeasured. Preserve
frozen031027 and COMPLETE numeric_recovery; newconfig/session only, no drift bypass.
No paid/API/GPU/robot/archiveDB/budget/outcomechange/commit/push. See cause_review_and_
detector_contract workhistory, AFS_BREADTH_SEARCH docs for freeplan/livecommands.

## Opt in action diagnostics and current set coverage priority implemented (2026-10-19)

New feedback_policy=action-diagnostics-v1 requires explicit expanded-ten + branch-v3;
legacy default retained. New afs_behavior_diversity_luna config keeps breadth12valid/
16attempt/20AFS/4peraxis/0repeat/Luna300s. Whole verified action windows yield blocked
navigation/first evidence/repeated endpoints/staging arrivals outside goal/push request
engagement; unavailable and censored remain distinct, no physical push success claim.
Past/current/cumulative measured families separated; missing_supported_families ranks
CURRENT session discoveries only. Existing metrics/rules/robot/goal unchanged. Whole
behavior feedback and overlapping historical/current pattern counts guide LLM to
different expected behavior, not new family labels or forced actions/hard gates.
133 related synthetic CPU tests pass32.29s incl saved response crash/resume no resend;
Ruff/format/diff clean. Actual7unclassified offline blocked counts2/2/2/3/4/2/2,
all no push request. Real FAIL0+PASS2 development_plan passes e8ec8119 condition,
160robotcall upper bound; no session created. Actual whole saved memory request has
historical3families/current0/missing8,4shown diagnostics,233503UTF8bytes NOT tokens;
never sent. No paid/API/GPU/robot or old DB/outcome/budget edit/commit/push. Preserve
COMPLETE160156_numeric_recovery; use NEW config/session, never drift bypass. Discovery
quality unmeasured. See action_diagnostics_and_current_coverage workhistory and
AFS_BREADTH_SEARCH.md new section for commands.

## Breadth recovered live search complete with FDR75 but one measured type (2026-10-19)

User-run160156_numeric_recovery now COMPLETE/validtarget12/pendingnull:12uniqueVALID,
3PASS9FAIL,0excluded,new-onlyFDR75%,primarygoal_completion_failure2episodes=>1type,
7unclassified;NOTjoint4types/Gain. AllFAIL10callBUDGET_EXHAUSTED;00004final.248276m
dwell.01of1s,00008final.245359m/dwell.05;00011.251203mOUTSIDE,notcompletiontype.
Small/large/combo4each;factorgroupsfloor3/object3/geometry3/layout3/human4. All12
verifiedunmixedPASSbranches,declaredaxesonly,samee8ec8119condition.117actions:
navigate85/move24/plan8,PUSH0;mass/frictionchangesNOTphysicalmanipulationproof.
RawAPI120completeusage3908846in263051out,AFS12/883313in43247out;includesold2robot
attempts/3AFS. Resumeadded10attempts/100robotcalls3248410in226587out,9AFS672004in
33123out. External60robot/1979590in116873out separate,externalAFScostunknown.
934rollout+796report+36proposalhashesmatch,12MP4present/GIF0,notdecodedthisreview.
Earlier bounds recovery works savedcombo00002PASSwithoutAFSresend;knowninvalid1m
candidate notclamped. Context3/9/11 already gives3knownhistorictypes+5missing;not
missingfeedback. Executionbreadthworks,mechanismdiversityunproven;review7unclassified
wholebehavior/terminalmeasurement and historicalnovelty vsnewset4type objective,
notinventlabels/forceactions/weakenrules/blindpaidruns. Goalmet:doNOTspendremaining
8AFS/4attemptslots orresumecompletedset. Reviewonly,docs/historychanges,noAPI/robot/
code/evaluator/DB/outcome/budgetchange/commit/push. See breadth_completed_live_review.

## Numeric outlier candidates no longer discard valid breadth alternatives (2026-10-18)

User authorized fix after160156 boundsstop. BreadthProposal only: numeric bounds
violations become per-space numeric_out_of_bounds diagnostics(original index/value/
bounds),valid alternatives retained;no clipping/response rewrite/boundrelax. First
and second axes checked. Schema/nonfinite/evidence/context/axis/quota/role errors
still whole-stop;old modes strict. All numeric rejected=>NoEligibleEndpoint bounded
AFScap,no robot attempt/FAIL/Random. Request adds explicit instruction suffix only.
New recover-numeric CLI dryrun default,--apply creates separate auditedfork,never
API/robot. Requires saved complete pendingresponse,all prior attemptsVALID,unchanged
context/model/schema/settings/history/budget;only explicit sourceallowlist,resources/
runtime fixed. Preserve originals+pastattempts/proposals/costs+hashedstate/protocol/
ledger,verifyaudit onresume,savedcandidate revalidatedwithoutresend. No generic drift
bypass or context rebinding. Actual160156 dryrunpasses:selected first combo width3.6+
obstacle1Y.65,rejectsecond obstacle2Y1 outside.2.. .8;2attempts/3AFSspent remain,
target12=>10morevalid,14attempts/17AFSremaining.341relatedCPUtests pass126.50s;
Ruff/format8files+diffclean. No paid/API/GPU/robot/live result changes/commit/push.
See AFS_NUMERIC_RECOVERY.md and numeric_candidate_rejection_and_recovery history.
Actual offline fork now created at160156_325966Z_numeric_recovery:READY/pendingnull,
selectedcombo3.6/.65,2attempts/3AFSspent preserved. Original552file aggregatehash
863ffb026c16fe018e5d4dbe6cc8617bf6b1a6d91eec7b34f160243a0ced83f7 unchanged.
Do not rerun --apply or originalsession;next paidrun uses this recovery --session.
Actual recovery _fresh + savedraw selected_probe pre-dispatch revalidation MATCH,
APIkeyremoved,no proposer/runner/livecall;ready2attempts3AFS unchanged.

## Breadth live two valid failures and mixed-validity proposal stop reviewed (2026-10-18)

User-run160156_325966 NEEDS_ATTENTION/execution_or_validation_error,pendingproposal2.
2VALIDFAIL,0excluded,new-onlyFDR2/2interim,0measuredtypes/2unclassified;no joint/Gain.
PASS anchors:floor.8->.5 small20.69% FAIL final.460567m;boxfriction.5->1 large34.48%
FAIL final.414699m,bothdwell0/all8rulesNOT_DETECTED,2unsupported. NOT frictioncausality
or physicalpushproof. Newfactorallocationexecuted. Proposal2completedLuna response
has first valid combo(width4->3.6,obstacle1Y.5->.65) and second invalidobstacle2Y1m
outside.2.. .8. Wholeproposalvalidate stopsBEFORE candidate selection;firstcombo
passesallhostchecks in read-only singlecandidate offline replay,NOTpersisted/dispatched.
163rollout+9proposalhashesmatch;robot20/660436in36464out completeusage;AFS3/211309in
10124out,17requestsremain;2attempts spent,14remain. No blindresume:pendingresponse
willfailagain. Recommend explicit versionedper-candidate numericrejection +audited
savedresponse recovery if approved,NOTclamp1to.8/boundrelax/DBclear/resend/costreset.
No code/evaluator/budget/outcome/archivechange or paid/API/GPU/robot/commit/push.
See breadth_live_bounds_stop_review workhistory;no recovery prepared this review.

## Opt-in breadth execution allocation and two-axis combinations implemented (2026-10-18)

New exploration_policy=breadth-v1 ONLY with expanded failure-branch-v3 + bounded
rejection + minchange<.3; legacy default unchanged. Explicit least-used eligible
factor-group allocation (floor,object physics,obstacle geometry,layout,human),
small/large/combination cycle. Small>=configuredmin and<.3 fullrange;large>=.3;
combo2distinct axes from2groups,each>=minimum. Required extra_changes=[] or one
second axis; existing schemas reject it. Same unmixed PASS/FAIL anchor role,evidence,
full-scene duplicate,bounds,per-axisquota/cooldown remain;charge BOTH combo axes/groups.
Two consecutive valid PASSes on same predictedfamily pause it nextslot;sharedgroup
switch when alternatives available. Allocation mismatch bounded rejection within
same frozen requestcap,not Random/slotfallback or ambiguous resend. Missing measured
family priority within slot; novelty before proposal order. Audit all eligible ranks,
changed_axes,normalizedchanges,before/after,group/formcounts;fixed scene BEFORE robot.
New afs_breadth_luna config12valid/16attempts/20AFS/4peraxis/0repeat/Luna300s/history4;
max160robotcalls for inherited10callrobot. This is NEW budget,NOT extension of old
COMPLETE sessions. No robot/evaluator/goal/threshold/model/token/simcap changes.
Actual6valid134620 archives pass read-only developmentplan/current e8ec8119condition;
initialfloor/small,request~206KB,missing5supportedtypes.27newCPUtests pass inclcombo
savedresponse resume(noresend),allguard/quotas/PASSswitch/report;performanceunmeasured.
FinalrelatedCPU303pass(107.81s),Ruff/format7files+diffcheckclean.
No paid/API/GPU/robot/runtimeDBrun,oldarchive/outcome/budget edits or commit/push.
See AFS_BREADTH_SEARCH.md and breadth_allocation_and_combinations workhistory.

## Expanded-ten live session completed with three measured families (2026-10-18)

User-run134620_116429 COMPLETE/valid_rollout_target_complete/pendingnull:7attempts,
6uniqueVALID,3PASS3FAIL,1excluded;new-onlyFDR50%,3primarytypes(goal_occupied,
goal_completion_failure,manipulation_failure),0unclassified. NOT4types/Gain claim.
One primary per distinct failed scene;3FAIL can provide at most3types. Coverage
null/partial,observed lowerbound3/10;unreachable/perception unsupported. All7
candidates from unmixed presented PASS anchors,exactly1axis changed. Attempt2
obstacle1sizeY.5->.8 FAIL final.206025m/dwell.54of1s,NOT predicted collision.
Attempt4 width4->3.2 FAIL final.440355m/push unsupported_box_face,NOT physical
pushing incapacity or predicted locomotionstall. Attempt0 originalgoal_occupied
unchanged. Attempt1 first-call header timeout remains excluded,0actions/unknownusage;
resume advanced next candidate,not retry. Human lateral1->.2 actuallytested PASS,
not whole-route safety proof. Final6valid goal met:do NOTspend1remainingAFSslot or
extend frozen session. Next separatelybudgeted larger discovery/familyallocation,
not labelsrelaxation or blind completed resume.481rollout+521report+21proposal
hashes match;7MP4fullydecoded/GIF0. Robot61calls/57actions,60usageknown+1unknown,
observed1979590in116873out;AFS7/503474in33504out. Inherited57robot/1796453in128011out
separate,priorAFScostunknown. Samee8ec8119condition. Reviewonly,no paid/API/robot,
code/evaluator/DB/outcome/budgetchange or commit/push. See expanded_afs_live_complete_review
workhistory;earlierpartialnote below is historical and superseded for currentstatus.

## Expanded live first goal occupied and excluded first-call timeout reviewed (2026-10-18)

User-run134620_116429:NEEDS_ATTENTION/excluded_rollout/pendingnull,2attempts,
1VALID FAIL/1excluded;new-onlyFDR1/1=100%smallinterim,1primarygoal_occupied,noGain/
joint4typesclaim. Attempt0 fromunmixedPASS4cf81... boxlateral.5->0;10actions
navigate8/move1/push1,final1.044812m/dwell0. Terminalstalledtrue range.012524m,
excursion.028541m+fullgoalcover verifyUNCHANGED legacyrule,notpredictedlabel.
Lastpush rejectedalignment_out_of_range(gap1.0443,heading-.4002,face-1.5708);
distance.18valid/noalignmentattempt/no physicalpushproof. Secondarymanipdiagnostic
doesnotaddfamily. Attempt1 SAMEPASSanchor obstacle2lateral0->-.7,notFAILaccumulation;
firstrobotcall0headersReadTimeout300setting/301.0466elapsed,0actions/unknownusage.
NotrobotFAIL,not newtype; no providerrootcauseproof/retry. Proposal1contextmeasured
goalcompletion(import)+goaloccupied(new),missing6supported; actualfeedbackliveworks,
new-onlyremains1type.101newrollout+305reporthashesmatch;source0drift/fullenvironment
fingerprintmatches.2MP4decoded/GIF0. Robot11calls10actions/10usageknown1unknown,
327955in34055outobserved;AFS2/139222in10015out;inheritedrobot57costsseparate.
Reviewonly,no code/DB/outcome/budgetchanges/newpaidrun/commit/push.6attempt/AFSslots
remain,5morevalidneeded. SAMEsessionresume--continue-after-exclusion noweligible,
advancesnextsceneNOTretryexcludedscene;doNOTfreshconfigrestart or raise timeout.
See expanded_afs_live_partial_review workhistory forcommand/diagnostics/evidence.

## Expanded ten-type measurement connected to AFS selection (2026-10-18)

New explicit SearchBudget.taxonomy_profile scene-default(default) or expanded-ten-v1
(branch-v3only) shares classify_for_search/metric_options for history import,observe,
failure_objective and new-only metrics. New config afs_expanded_ten_luna.json keeps
6valid/8attempt/8AFS,2peraxis,0repeat,min10%,Luna300s,boundedreproposal;old configs6types.
ExpandedBranchPoint/Proposal accepts4newtargets;old schemas retain enums. Request
and host restrict to8supported targets+unclassified;unreachable/perception unsupported.
Next context includes measured primary/diagnostics/statuses/expanded evidence. Existing
missing-measured-family/target-count rank now uses10profile; predictions never labels.
Imported history notnew denominator. Budget,goal,robot,thresholds unchanged. 230related
CPUtests pass incl7new: schema/host,oldmodeguard,rank,observe/summary/resume,prediction
fall vs observedcompletion separation. Real081720 sixrollout plan passes samee8ec8119.
Actual reanalysis-memory context:1measuredgoalcompletion,7missing supported families;
manual contract check selects missingfall over knowngoalcompletion. NOT LLM proposal,
live fall or quality improvement;request202219UTF8bytes nottokens/wirecapture/cost.
No API/GPU/robot/simulation/newsession/oldDB/outcomeedits/commit/push. Old frozen
sessions preserved; future separate run uses NEW10config. Actualdiscovery quality
unverified,no4types/Gain claim. DocsAFS_EXPANDED_TEN.md+historycontaincommands.

## Ten-family expansion and offline reanalysis implemented (2026-10-18)

User approved expansion after real simulations, first definitions/detectors plus
saved-run reanalysis, NOT new paid simulation. Blueprint now targets4of10 alongside
FDR30%/Gain20%. ExistingFAMILIES6/default metrics/profiles retained; new explicit
EXPANDED_FAMILIES10 and expanded-goal-behavior-v1 add fall,locomotion_stall,
manipulation_failure,goal_completion_failure. Eight operational rules supported;
unreachable/perception remain unsupported. PASS/excluded never get failure primary.
Unique legacy primary preserved; legacy ambiguity unchanged. Else new priority
fall>goalcompletion>stall>manipulation selects1; others diagnostic only,not cause.
Fall sustained sampled G1Z<.45 or tilt>=60 for.5s,gap<=.25. Stall uses>=2s actual
execution/recent10s/net<=.05/excursion<=.1,not inference,stop/turn/arrival/roundtrip.
Manip last accepted tool result perobject failed/rejected; later success supersedes.
Completion only final fullrate insidegoal with contract-matching incomplete dwell;
NOT everybudgetFAIL. Missing staysUNKNOWN. Legacy6rules/thresholds unchanged.
tools/reanalyze_failure_types.py --session/--run validates archives and emits NEW
reports with old6 and expanded10 metrics. Actual081720 sixnewrollouts reanalyzed at
runtime/failure_type_reanalysis/20261018T130328_693125Z:3PASS3FAIL/FDR50% unchanged;
1primarygoal_completion_failure atattempt3(.218747m,dwell.655/1s); manipulation
rejection sameepisode diagnostic only. Other2FAIL unclassified; no4type achievement.
436source+5newreport artifact hashes match. 223related CPU tests passed incl11new,
Ruff/format/diff checks clean. No API/GPU/robot/new simulation/oldDB/outcome rewrite,
commit/push/GIF. Retrospective new counts are NOT prospective discovery/Gain.
Current liveAFS still uses6-family contract: integrating expanded feedback/selection
is NEXT stage, not yet done. Frozen sessions cannot resume newsource. See
EXPANDED_FAILURE_TYPES.md and expanded_ten_family_reanalysis history/command.

## Branch AFS live session completed with FDR50 and no measured families (2026-10-18)

User-run081720_637822 session COMPLETE/valid_rollout_target_complete/pendingnull:
6uniqueVALID scenes,3PASS3FAIL,0excluded;observedFDR50%,not joint4families or Gain.
All6 verified unmixed PASS anchors/one-axis changes. Sequence: box1->.5PASS;
fromthatPASS obstacle2.7->0PASS; fromnewPASS obstacle1.7->0FAIL; fromfirstPASS
width4->3.2FAIL; fromsecondPASS box.5->0FAIL; fromsecondPASS obstacle2sizeY.5->.8PASS.
Thus no latest-FAIL accumulation; no causal independence claim.6AFS requests with
3/3/3/2/2/2 alternatives,0whole/partialrejections: live reproposal path not exercised.
AllFAIL budget10: attempt2 final.423851m/stalledtrue/only1recentblocked,not2;
attempt3 final.218747m inside but dwell.655/1s; push rejected unsupported_box_face,
no physical push proof;11whole non-support contacts but0qualifyingrecentcontacts.
Attempt4 final.979180m/fullgoalcovertrue but stalledfalse/range.27989m,0recentblocked.
3unclassified,4supported rulesNOT_DETECTED,human no terminalexposure; no relabeling.
436newrollout+460report+18proposal hashes verified;6MP4decoded/GIF0. Robot57calls
but54actions,completeusage1796453in128011out;AFS6/398599in26382out. Inherited43robot
calls1281340in107606out separate,priorAFScostunknown. Samee8ec8119condition.
Reviewonly,no code/evaluator/DB/budget/outcomechange or paidrun/commit/push.
Completed target: do not spend2remainingAFSslots/extend frozen session. Next priority
review6-family versus terminal/sequence contract +family-aware executed allocation
(human proposed once,neverselected), not more blind paid runs or relaxed labels.
See branch_afs_live_review workhistory for actual actions/costs/artifacts/limits.

## Bounded candidate reproposal implemented after duplicate live proposal (2026-10-18)

User-run075715 session spent1AFS/62945in1534out,0robot: obstacle2 lateral.7->-.7
from PASS recreated earlier PASS exactly across20axes, not min-step/cooldown.
Matchingcase5bdb9fe0...; original218sessionfiles SHA256 unchanged by offline replay.
New SearchBudget.reproposal_policy defaults stop; bounded-rejection-v1 opt-in only
for failure-branch-v3, enabled in afs_failure_branch_luna.json. No budget increase:
8AFS/8attempts/6valid. Completed valid-schema proposals with no eligible endpoint
get typed NoEligibleEndpoint diagnostics, hashed rejection.json/events, next-context
recent4 rejection feedback and explicit observed single-axis forbidden endpoints.
Ask2..4 alternatives; one valid point is accepted, only1executes. Mixed valid/bad
endpoints select valid without new call. All-rejected requests consume AFS cap but
no robot attempt/FAIL. Cap stops afs_request_budget. API/schema/ref/context/drift
errors still stop; NEVER resend ambiguous calls or relax filters/Random fallback.
Pending/selected response context stays stable until dispatch; resume tests cover
saved duplicate response and committed rejection without resend. HTML shows reasons.
Related212 CPU tests pass; real2PASS+3FAIL offline plan passes same e8ec8119 condition.
No new API/GPU/robot/runtime session, old DB/outcome edits or commit/push. Existing
075715 is frozen, no source drift bypass/recovery prepared; future run starts NEW
budget. Prior1request remains separate spent cost, two-session max1+8=9 requests.
Actual new policy discovery quality unverified, no FDR/4families/Gain achievement.
See AFS_BRANCH_ANCHORS.md and bounded_candidate_reproposal workhistory.

## PASS anchor branching and read-only phase audit implemented (2026-10-18)

New opt-in failure-branch-v3 requires anchor_case_id/rationale and actual anchor
behavior refs. Challenge/transfer use unmixed observed PASS; relief uses observed
FAIL; mixed/excluded/unpresented cases rejected. Candidates/min-step are based on
selected anchor, not latest FAIL; exactly one changed parameter verified. Catalog
respects presented history_limit. branch_audit persists and feeds next prediction
review/report. Old modes/robot/evaluator/taxonomy thresholds unchanged. New config
afs_failure_branch_luna:6valid/8attempts/8AFS,2peraxis,0repeat,10%min-step,Luna300s.
Actual2PASS+3FAIL offline plan passes same condition e8ec8119...; actual context
schema/manual contract check keeps box fraction1 from PASS instead of latest.25
while changing floor friction. Manual check NOT LLM proposal or live result.
Related202 CPU tests pass incl17new branch/phase tests; no paid/API/GPU/robot run.
New tools/audit_failure_phases.py compares whole actions with unchanged terminal
rules; actual4-run report runtime/failure_phase_audit/20261018T074329_464497Z.
Original3FAIL stay unclassified; excluded human timeout stays INCONCLUSIVE.
No labels relaxed, old DB/outcomes/budgets changed, commit/push or GIF. Preserve
all frozen sessions; use NEW separately budgeted branch session, never drift bypass.
Joint30% FDR/4families is across whole same-goal test set, not one episode; Gain20%
later. New selection quality remains unmeasured. See AFS_BRANCH_ANCHORS.md and
branch_anchors_and_phase_audit workhistory for commands, evidence and limits.

## Failure-directed live session partial results reviewed (2026-10-18)

Session20261018T032610_668533Z:4attempts,3VALID FAIL(BUDGET_EXHAUSTED),1excluded
api_timeout; NEEDS_ATTENTION/pendingnull,4attempt/AFS slots remain,validtarget6.
269 rollout hashes match;4MP4decode/GIF0. FDR3/3=100% observed but0measured families,
3unclassified; no joint30%/4types or Gain achievement. Changes sequential: box
lateral1->.25 FAIL(.748m); obstacle2 .7->0 FAIL(.651m); width4->1.8 FAIL(4.057m);
human1->0 excluded at6th API after5actions, response-header ReadTimeout300.34s.
First3 ten actions each. Attempt0 push request rejected alignment_out_of_range,
no alignment/push motion; gap1.0978/heading.153/face1.571, distance valid.2m; NOT
float endpoint bug, mass inability or physical pushing validation. Classifier
conditions not met:0partial goal occupancy;1/2not terminal-stalled; old blocked
tools outside window, no recent qualifying contact/proximity. Do not relabel.
Latest-anchor accumulation retains box.25 in subsequent probes: different axes
NOT independent mechanisms. Next proposal: PASS-anchor branching + taxonomy/phase
contract review, not blindly spending remaining trials or weakening detectors.
No code/DB/outcome changes or paid run in review. Robot36calls/35actions,35usage
known+1unknown, observed1021617in104103out;AFS4/176697in6902out. See
failure_directed_live_review workhistory. Existing session is frozen/preserved.

## Failure-directed v2 selection implemented (2026-10-18)

User emphasizes PASS valid but AFS must seek goal failures, not merely fill smoke
budget or change paths. New opt-in failure-directed-v2 requires real episode behavior
refs, vulnerability vs conjecture, failure_prediction, change_rationale, intent,
predicted family; point-only schema, old modes/contracts retained. Host ranks intent,
missing MEASURED family, family-target attempt counts, axis counts, proposal order,
novelty. Predictions NEVER become measured labels. All eligible axes allowed (not
v1 least-used-only mask), existing cooldown/quota/min10%/duplicate guards remain.
Relief only with actual FAIL +3attempt cooldown; priority if noPASS and>=2FAIL;
otherwise transfer/challenge. Recent4 prediction outcomes feed next request; PASS
is goal-failure-not-observed, FAIL mechanism unconfirmed, exclusion unresolved.
Configs afs_failure_directed_luna.json6valid/8attempts, _20_luna20valid/24attempts.
Robot/goal/evaluator/model/timing unchanged; actual two current PASS archives pass
offline plan and full20axis request:2real refs,0FAIL,challenge/transfer only,about86KB.
Remaining attempt vs valid-target counts separated; imported PASS does not consume
new valid target. Final focused17tests pass after this last metadata change.
224 related tests passed; no paid/API/GPU/robot/session creation, commit/push.
Existing recovery session must NOT resume new source; preserve it, use NEW version
session with reviewed PASS histories. Historical AFS selection costs unknown remain
separate. New algorithm's actual discovery quality unverified, no30%/4families/Gain
claim. See AFS_FAILURE_DIRECTED.md and failure_directed_selection history.

## Discovery recovery next probe valid PASS reviewed (2026-10-18)

Session20261018T014205_556509Z_point_recovery attempt1 VALID/PASS,57 artifact hashes
match, MP4 decodes/GIF0. New point proposal obstacle2 lateral-.7->+.7 ONLY; human
remains1 at edge, NOT center timeout replay.6navigate_to(7,0), first2*.3s then4*10s,
no push/other tools,0blocked/non-support contacts recorded. Final.116875m/dwell1s,
sim81.85 includes waits, holdonly.035s/4callsleft.6HTTP200/complete148993in6773out,
latencies2.74..22.45s, no proof prior timeout fixed. NewAFS19513in964out; totalAFS2,
robot7 includes1timeout unknown usage. READY/pendingnull,2attempts/1validPASS/0FAIL/
1excluded;6attempts/AFSrequests remain,5morevalid needed. Failed center not feedback
FAIL/anchor. Pipeline works; same-side route-change hypothesis may ease rather than
challenge, not failure discovery evidence. Do not edit frozen selector mid-session;
finish smoke then review challenge quality. Review only,no paid run/code/DB edits.
See discovery_first_valid_pass_review workhistory. Next normal run --live --session
can use remaining budget; no continue-after-exclusion flag needed for current READY.

## Robot timeout offline comparison added (2026-10-18)

User authorized improvements after recovered human-center attempt0 INCONCLUSIVE.
Added tools/audit_robot_api.py ONLY plus tests/docs, no robot/search src changes or
frozen condition edits. Reads verified manifests/journals, source-bound FIRST-call
reconstruction sizes/hash (NOT wire capture/tokens), transport failure phase, IDs,
settings; no raw request/image/key export, network/API/robot/retry. Failed request
82286 reconstructed bytes vs prior clear PASS83343, both high reasoning/image,
history0. Failure301.03s vs success6.54s; no size blowup proof or provider/root-cause
claim. Report runtime/robot_api_audit/20261018T024723_577469Z/report.html. See
ROBOT_API_DIAGNOSTICS.md and robot_api_offline_diagnostics history. Attempt remains
excluded, unknown usage not zero, no paid resume performed. Continue-after-exclusion
advances to NEXT axis (center human quota consumed), not retry same scene, budgets
unchanged. Do not claim timeout fixed or silently change reasoning/timeouts.

## Single point proposal support and explicit offline recovery (2026-10-18)

Autonomous requests now prefer PointSpace axis/value, with legacy strict low<high
ranges still accepted via EndpointProposal nested anyOf. Other tools keep their
range-only contracts. Same bounds/evidence/quota/cooldown/min-step/novelty guards;
no auto-clamping or equal-range repair in normal execution. Prompt fixes scene
BEFORE rollout, no AFS intervention during execution. recover-point CLI dry-run
default, --apply creates separate first-proposal-only recovery fork; preserves
original request/context/response bytes and hashes, records normalized proposal
and lock-bound audit, inherits spent AFS call/cost/budget, no context rebinding.
Only explicit equal low/high conversion allowed, no robot/resource/runtime drift
or generic source bypass. Actual source 20261018T014205_556509Z response proposes
human_lateral_fraction0; first proposal spent19067in/1162out, zero robot attempts.
See AFS_DISCOVERY_MODE.md and single_point_proposal_recovery workhistory for status
and separate live command. No paid robot/API execution in implementation.
Actual offline recovery now prepared at runtime/afs_autonomous/
20261018T014205_556509Z_point_recovery: READY/pendingnull/attempts0, selectedhuman
lateral0, original55file hashes unchanged, candidate pre-dispatch revalidation MATCH.
Inherited AFS1spent19067in/1162out, <=7new AFS requests left, original8attempt cap.
261 related tests passed, Ruff/format/diff clean. Next user command run --live
--session this recovery, NOT fresh original --config/--run or old source resume.

## Discovery selection and valid target budgets implemented (2026-10-18)

New opt-in discovery-v1 reuses autonomous loop, no local/repeat slots; LLM every
selection, least-used eligible axes, existing cooldown/quota, min10% full axis
change with audited endpoint rejection. Old alternating-v1 remains default.
Separate valid_rollout_target and max_attempts; exclusions consume cap and STOP
for review, never automatically replace/retry. TARGET_NOT_REACHED if cap first.
Configs smoke6valid/8attempts and20valid/24attempts, <=80/240 robot calls at10 each,
<=8/24 AFS requests. New-only joint discovery metrics in summary/report; input
history taxonomy is classified separately for discovery mode. Still reviewed-history
development, NOT independent AFS/Random/Gain or multi-seed evaluation. Human clear
20261018T004636_410637Z passes offline plan preflight. No paid/API/robot execution,
new runtime DB, old outcome/budget edits or commit/push. See AFS_DISCOVERY_MODE.md
and discovery_selection_and_valid_budget history. Four-family discovery unproven;
human rule terminal5s scope unchanged. Run smoke before new20 session.

## Human scene and joint measurement first implementation (2026-10-18)

User authorized implementation. Added opt-in clear-path-human-v5 (v4 plus human X
3.65..4.35 and lateral fraction,20 axes) with a fixed0.4x0.4x1.6m static proxy in
a disjoint band. Shared XML/map/graph/robot geometry role and human_proxies.json
manifest/source provenance; G1 joints unchanged. goal-behavior-v2 explicitly adds
human_safety_risk to original3 rule versions; default v1 retains3. Verified scene
config/XML/graph/metadata/audited qpos layout, complete terminal sampled5s window,
<=.25s gaps/termination lag and fixed .4m base/.6m protected radius, .5s continuous
exposure required. PASS retains diagnostic; exclusions/missing/overlapping labels
stay conservative. This is temporal association, not cause or real safety standard.
Standalone caller-declared calculator still cannot count as a family. Actual new
human/G1/VLM rollout evidence remains absent. Domain audit supports explicit profile
and v5 envelopes; inventory4 is NOT observed4/6. AFS schema/host both allow20 axes,
measured human evidence enters compact feedback; memory bundles preserve metadata.
Joint FDR/diversity observed field and family count/lower bound/unclassified FAIL
appear in common JSON/CSV/HTML reports; partial coverage stays null.
Fixed autonomous resume request comparison via parsed strict nested JSON while
retaining whole-body model/instructions/schema/values/list order guards and original
artifact hashes. Sorted second-response crash reproduced failure before fix; recovery
after fix uses saved response with no resend. Source changes require new controls;
never migrate/resume old frozen robot conditions by bypassing drift.
Final related CPU/synthetic tests347 passed; Ruff and diff checks pass. Two CPU
actual G1 composition previews at runtime/human_scene_validation/20261018T003120_486877Z
(29 actuators, no robot/API/GPU runs, PNGs inspected, GIF0). No four-family discovery
or FDR performance achievement claimed. Still pending: discovery-only scheduler,
family-aware allocation,20-valid/24-attempt independent campaign and live smoke.
Existing autonomous local/midpoint scheduling is still present; current implementation
is first bundle per docs/HUMAN_SCENE_MEASUREMENT.md. No commit/push or archive/DB edits.

## Joint FDR and diversity delivery plan (2026-10-17)

User requested replanning, not implementation or paid execution. Current plan is
docs/FDR_DIVERSITY_DELIVERY_PLAN.md: validate three existing operational families,
integrate declared static human proxy/manifest-bound traces as fourth candidate,
then discovery-only AFS (no automatic midpoint), precise evidence, resume fix and
joint reporting; offline tests, bounded development smoke, frozen evaluation follow.
Human exposure plus PASS stays a safety event, not failure; ambiguous/missing labels
stay UNKNOWN, no guaranteed fourth family or causal claim. Unreachable/perception
remain deferred. All four types must have distinct verified failed-scene evidence.
Proposed—not approved—budgets: smoke<=8 attempts; first evaluation20 valid<=24 attempts,
6 FAIL+4 families milestone; expand to3 predeclared seeds60 valid<=72 attempts,
18 FAIL+4 families at total60, with all per-seed results. Max10 robot calls/episode
implies240/720 robot calls and<=24/72 AFS requests; no token/sim caps. No external
development history in evaluation, no result-driven seed selection/early success stop.
Current autonomous max_attempts<=16/attempt-only requires versioned implementation,
not config editing alone. Gain/precise boundaries/old width resumes remain deferred.
Only plan, roadmap and history changed; no code, outcomes, DB, budgets or live runs.

## Broad failure discovery before boundary refinement (2026-10-17)

User clarifies earlier small changes intentionally sought failure boundaries and now
wants that objective set aside. Keep joint FDR>=30% / >=4-of-6 family priority, Gain
later. Plan initial discovery across the admitted domain, including large changes;
defer automatic midpoint/local boundary narrowing and repeated fine adjustment.
Small steps were not intrinsically defective; useful failure relief differs from
repeatedly easing an already-PASS anchor. Keep evidence grounding, genuine family
measurement, fixed robot/goal/validity and bounded confirmation of useful discoveries.
Current code STILL alternates local/hypothesis slots and accepts exactly one changed
axis: this turn changes plans/docs only, not execution or old frozen sessions. Broad
single-axis moves need not wait for unimplemented multi-axis proposals. No paid run.
See broad_discovery_priority history. Preserve width stop and original outcomes.

## FDR and diversity first, Gain later (2026-10-17)

User prioritizes metric1 FDR>=30% and metric3 >=4/6 evidence-backed families TOGETHER;
metric2 Random-relative Gain follows afterward. Do not require more Random runs now.
Saved evidence remains: completed 20260929T163123 pilot AFS6/6 FAIL (5 unique scenes,
one repeat), one operational obstacle_interference attribution at attempt00004,
five failures unclassified; coverage null/partial, lower bound1/6, NOT four families.
Latest autonomous 20261003T165928 new-only5PASS/1FAIL has descriptive FDR1/6 and no
primary family; its FAIL has three NOT_DETECTED and three UNSUPPORTED rules.
Robot conditions differ (6225836a... vs eb42efe3...), so never pool those results.
Both representative reports and raw logs/MP4 remain; seven selected report hashes
rechecked. Existing evidence is reusable, not joint target achievement. Current
three-rule support needs genuine measurement/scene expansion, not label invention.
This turn records priority/evidence only: no code/evaluator/DB/budget changes or paid
execution; preserve width stop and all originals. See fdr_diversity_priority_and_evidence history.

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
