"""Host-computed context binding and explicit trusted-local legacy recovery."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Literal

from . import behavior as b
from . import provider

NUMERIC_REJECTION_INSTRUCTIONS = """Read allowed_axes bounds for BOTH changes.
Numeric out-of-bounds values
reject the entire candidate, not other valid alternatives; no clipping or range expansion.
Other schema/evidence/context/axis/quota errors still stop the whole response.
"""

SELECTION_POLICIES = {
    "independent_evaluation_endpoint": (
        "behavior-campaign-feedback-v1",
        """Selection policy: independent-evaluation-endpoint-v1.
Only newly executed episodes from THIS predeclared seed are supplied. There is no
external warm history or access to other seeds. Uniform cold starts have already
consumed attempt slots and valid outcomes count in the evaluation denominator.
Seek goal failures and missing measured primary families under the frozen rules.
The host executes at most ONE eligible novel candidate per response. The explicit
branch, breadth allocation and cause-review contracts below govern selection.
All requests, attempts and exclusions consume their frozen caps. No local midpoint,
automatic repeat, random fallback, or metric-success early stop is scheduled.
Scene proposals are fixed BEFORE execution; do not command the robot or change its
goal, policy, evaluator, thresholds, model or call budget. Predicted families and
causal hypotheses never become measured labels. Random-relative Gain is deferred.
""",
    ),
    "autonomous_development_endpoint": (
        "behavior-campaign-feedback-v1",
        """Selection policy: autonomous-development-endpoint-v1.
This is externally seeded DEVELOPMENT search, not an AFS/Random comparison.
The host executes at most ONE novel endpoint of your ranges, with other values
fixed at latest.parameters. Rank by search_selection.mode_priority, your range
order, then endpoint novelty. Follow development_search.selectable_axes: the full
allowed_axes domain is unchanged, but some axes have exhausted their session quota
or are temporarily cooling down. The JSON schema also restricts selectable axes.
Explain behavior evidence, competing explanations and falsification. A different
axis is NOT proof of a different failure family. Do not merely amplify a failure.
The bounded host loop alternates hypothesis requests with at most one local
mixed-outcome repeat or measured bracket midpoint. Ineligible local steps lead
to a new hypothesis request, never silent Random. No automatic anchor repeat is
added to each probe. All attempts, repeats and exclusions consume the frozen total
budget. Robot action selection remains autonomous; no actions are supplied by AFS.
""",
    ),
    "anchored_contrast_endpoint": (
        "behavior-campaign-feedback-v1",
        """Selection policy: anchored-contrast-endpoint-v1.
This is operator-seeded DEVELOPMENT search with disclosed external history, not
an AFS/Random benchmark. Propose one to four single-axis hypothesis ranges.
The host selects at most ONE unobserved endpoint across those ranges, keeping
all other values at latest.parameters. It ranks eligible endpoints by declared
search_selection.mode_priority, your space order, then minimum normalized distance
to observed scenes (ties choose low first). Duplicate and nearby repeated-failure
cooldown filtering apply. No eligible endpoint is an error, not a Random fallback.
The host prepares that probe plus one repeat of its anchor as a fixed two-attempt
suite; it does not execute both endpoints. Robot execution requires separate approval.
Before requesting you, mixed outcomes take priority for a one-attempt repeat;
otherwise an observed single-axis PASS/FAIL bracket supplies a midpoint plus anchor
repeat without an LLM call. No automatic exploration slot or indefinite loop exists.
Behavior timelines and patterns are evidence, not causes or failure families.
Seek success-side and alternative-mechanism probes instead of escalating one failure.
All-FAIL evidence is not a boundary. Do not change or prescribe robot behavior.
""",
    ),
    "campaign_hypothesis_endpoint": (
        "behavior-campaign-feedback-v1",
        """Selection policy: campaign-hypothesis-endpoint-v2.
The host selects at most ONE endpoint per proposal, not both endpoints and
not one endpoint per space. Other axes remain fixed at latest.parameters, the
search_selection.anchor_case_id. Rank spaces in your preferred experimental order.
Both endpoints of a space must serve its stated hypothesis; put competing questions
in separate spaces. Explain the expected observation and its falsification, not just
a desired FAIL label. No calibrated failure probabilities are assumed.
After exact-duplicate and nearby similar-behavior cooldown filtering, the host ranks
by search_selection.mode_priority, then your space order, then greatest minimum
normalized distance to observed scenes within that space (ties choose low first).
Thus novelty cannot override a higher-priority experimental purpose. A requested
mode with no eligible candidate is skipped explicitly in the saved selection audit;
no eligible endpoint is an error, never an automatic Random replacement.
No comparable success: prioritize success_probe. Repeated similar failures:
prioritize cross_mechanism, not repeatedly stronger versions of the same failure.
Full action_timeline summarizes every recorded decision, including late tool errors
and subsequent recovery attempts. Detailed intervals are selected representatives;
omitted detail does not mean no event. behavior_pattern is a coarse similarity
heuristic, NOT a failure family or a causal label.
Separate fixed exploration/repeat slots remain charged to the rollout budget.
The boundary slot repeats a mixed-outcome case if present; otherwise it samples
an untested observed-bracket midpoint, or requests a new hypothesis. The
boundary_probe label alone does not trigger midpoint selection. Never claim a
boundary from all-FAIL evidence or prescribe robot actions.
""",
    ),
    "standalone_suite": (
        "behavior-afs-context-v2",
        """Selection policy: standalone-suite-v1.
The host compiles candidate scene files, not robot executions. For each space it
normally generates both low and high endpoints with other axes fixed at the latest
scene values. For boundary_probe with an observed bracket on that axis, it instead
generates the measured bracket's midpoint, which need not be inside your proposed range.
The suite also includes configured explicit repeats and independent exploration.
Duplicate and neighborhood-cooldown filters can exclude probes. Generated candidates
are plans, not completed trials or a guarantee that both endpoints will be executed.
""",
    ),
    "campaign_single_endpoint": (
        "behavior-campaign-feedback-v1",
        """Selection policy: campaign-single-endpoint-v1.
The host considers low and high endpoints from all your proposed spaces, each with
other axes fixed at the latest scene values. It selects at most ONE endpoint per
proposal for the next rollout, not both endpoints and not one endpoint per space.
After duplicate and neighborhood-cooldown filtering, it chooses the endpoint whose
minimum distance to previously observed scenes is largest. Distance is the maximum
absolute axis difference normalized by that axis's full allowed range; ties retain
proposal order (spaces in order, low before high). This is a novelty heuristic, not
a learned failure-probability ranking. No eligible endpoint means a surfaced error,
not an automatic replacement. Do not rely on paired execution of your range or
claim an untested endpoint has an outcome.
Observed-bracket midpoints, independent exploration and explicit repeats are managed
by separate host strategy slots when configured; they are not extra rollouts caused
by this proposal. The boundary_probe label alone does not trigger midpoint selection.
""",
    ),
}


def _bind_intent_modes(schema, intents, *, ctx=None):
    """Bind whole candidates using nested anyOf, not unsupported if/then or allOf.

    Preserve previously bound evidence, axis, anchor and taxonomy restrictions.
    """
    if not intents or any(i not in b.FAILURE_INTENT_MODES for i in intents):
        raise ValueError("nonempty supported failure-search intents required")
    items = schema["properties"]["spaces"]["items"]
    ref = items.get("$ref", "")
    if not ref.startswith("#/$defs/"):
        raise ValueError("expected a single directed candidate definition")
    name = ref.removeprefix("#/$defs/")
    template = schema["$defs"][name]
    references = []
    v4 = ctx and ctx.get("failure_objective", {}).get("anchor_policy") == "failure-diversity-v4"
    groups = (
        [(b.FAILURE_INTENT_MODES[i], [i]) for i in intents]
        if v4
        else [
            (mode, [i for i in intents if b.FAILURE_INTENT_MODES[i] == mode])
            for mode in dict.fromkeys(b.FAILURE_INTENT_MODES[i] for i in intents)
        ]
    )
    for mode, group_intents in groups:
        candidate = deepcopy(template)
        candidate["properties"]["mode"]["enum"] = [mode]
        candidate["properties"]["intent"]["enum"] = group_intents
        if v4:
            candidate["properties"]["anchor_case_id"]["enum"] = [
                a["case_id"]
                for a in ctx["anchor_catalog"]
                if group_intents[0] in a["allowed_intents"]
            ]
        variant_name = name if not references else f"{name}IntentMode{len(references)}"
        schema["$defs"][variant_name] = candidate
        references.append({"$ref": f"#/$defs/{variant_name}"})
    schema["properties"]["spaces"]["items"] = (
        references[0] if len(references) == 1 else {"anyOf": references}
    )


def request(
    ctx,
    model,
    *,
    selection_policy: Literal[
        "standalone_suite",
        "campaign_single_endpoint",
        "campaign_hypothesis_endpoint",
        "anchored_contrast_endpoint",
        "autonomous_development_endpoint",
        "independent_evaluation_endpoint",
    ] = "standalone_suite",
):
    """Bind both evidence and the caller's actual candidate-selection instructions."""
    if selection_policy not in SELECTION_POLICIES:
        raise ValueError("unknown behavior AFS selection policy")
    context_schema, selection_instructions = SELECTION_POLICIES[selection_policy]
    if ctx.get("schema_version") != context_schema:
        raise ValueError("behavior AFS selection policy does not match context schema")
    expected = b.digest(ctx)
    autonomous = selection_policy in {
        "autonomous_development_endpoint",
        "independent_evaluation_endpoint",
    }
    if selection_policy == "independent_evaluation_endpoint" and (
        ctx.get("development_search", {}).get("mode") != "independent-afs-discovery-v1"
        or ctx.get("development_search", {}).get("external_history") is not False
    ):
        raise ValueError("independent evaluation requires an isolated seed context")
    branch = ctx.get("development_search", {}).get("selection_policy") == "failure-branch-v3"
    directed = (
        branch or ctx.get("development_search", {}).get("selection_policy") == "failure-directed-v2"
    )
    expanded = (
        branch
        and ctx.get("development_search", {}).get("budget", {}).get("taxonomy_profile")
        == "expanded-ten-v1"
    )
    breadth = (
        ctx.get("development_search", {}).get("budget", {}).get("exploration_policy")
        == "breadth-v1"
    )
    feedback = ctx.get("development_search", {}).get("budget", {}).get("feedback_policy")
    reviewed = feedback in {"cause-review-v2", "cause-review-v3"}
    if directed and not autonomous:
        raise ValueError("failure-directed context requires autonomous endpoint policy")
    schema = (
        b.RoleSeparatedProposal
        if feedback == "cause-review-v3"
        else b.ReviewedBreadthProposal
        if reviewed
        else b.BreadthProposal
        if breadth
        else b.ExpandedBranchProposal
        if expanded
        else b.BranchProposal
        if branch
        else b.FailureProposal
        if directed
        else b.EndpointProposal
        if autonomous
        else b.Proposal
    ).model_json_schema()
    if reviewed:
        # Structured Outputs follows property order: ask for reviews before candidates.
        order = ("context_sha256", "episode_reviews", "spaces")
        schema["properties"] = {k: schema["properties"][k] for k in order}
        schema["required"] = list(order)
    selectable = list(b.context_axes(ctx))
    if autonomous:
        selectable = ctx["development_search"]["selectable_axes"]
        if not selectable or not set(selectable) <= set(b.context_axes(ctx)):
            raise ValueError("invalid autonomous selectable axes")
    for definition in schema["$defs"].values():
        properties = definition["properties"]
        if "axis" in properties:
            properties["axis"]["enum"] = selectable
        if reviewed and "evidence_id" in properties:
            properties["evidence_id"]["enum"] = ctx["failure_objective"]["behavior_evidence_ids"]
        if reviewed and "analysis_evidence_id" in properties:
            properties["analysis_evidence_id"]["enum"] = ctx["failure_objective"][
                "behavior_evidence_ids"
            ]
        if "anchor_behavior_refs" in properties:
            properties["anchor_behavior_refs"]["items"]["enum"] = ctx["failure_objective"][
                "behavior_evidence_ids"
            ]
        if "evidence_refs" not in properties:
            continue  # AxisChange shares the axis enum but has no hypothesis fields.
        properties["evidence_refs"]["items"]["enum"] = b.evidence_ids(ctx)
        if directed:
            objective = ctx["failure_objective"]
            properties["behavior_refs"]["items"]["enum"] = objective["behavior_evidence_ids"]
            properties["intent"]["enum"] = objective["allowed_intents"]
            properties["target_family"]["enum"] = objective["supported_targets"]
            if branch:
                properties["anchor_case_id"]["enum"] = [c["case_id"] for c in ctx["anchor_catalog"]]
    if directed:
        _bind_intent_modes(schema, ctx["failure_objective"]["allowed_intents"], ctx=ctx)
    schema["properties"]["context_sha256"]["enum"] = [expected]
    body = provider.request_body({"context_sha256": expected, "context": ctx}, schema)
    body.update(
        model=model,
        instructions=b.INSTRUCTIONS
        + "\n"
        + selection_instructions
        + "\nCopy context_sha256 from the request exactly; never compute or invent it.",
    )
    if autonomous:
        body["instructions"] += """
For the next independent experiment, prefer a concrete point: axis + value,
with no low/high fields. Legacy range proposals remain accepted ONLY with
low < high, both in allowed_axes. Equal endpoints are invalid ranges; use value.
The host selects at most one point or range endpoint, applying the same quotas,
minimum change, duplicate checks and evidence requirements. A point is not exempt.
Environment selection occurs BEFORE a rollout. Once it starts, AFS must not change
the scene or issue robot commands. Only after termination may it propose a new scene.
"""
    if ctx.get("development_search", {}).get("selection_policy") == "discovery-v1":
        body["instructions"] += """
Discovery-v1 overrides the alternating/local policy above: EVERY slot requests
a new LLM hypothesis; no host midpoint or repeat is scheduled. Selectable axes
are the least-used eligible axes, not a guarantee of failure-family diversity.
Each eligible endpoint must change its axis by at least
development_search.min_axis_change_fraction of the FULL allowed axis range.
Seek broad, behavior-grounded challenges and different plausible mechanisms,
not increasingly severe copies of one failure or relief of an already easy PASS.
Success-side tests remain useful when all comparable evidence is FAIL. Never
invent a family label: supported rules, unknowns and goal outcomes stay separate.
No eligible endpoint stops transparently, without Random substitution or retry.
"""
    if directed:
        body["instructions"] += (
            "\nExact intent/mode contract: choose only an allowed_intents value and its "
            "matching mode below. This overrides generic mode descriptions, including for "
            "two-axis combinations. A combination does NOT imply cross_mechanism.\n"
            + "\n".join(
                f"intent={intent} MUST use mode={b.FAILURE_INTENT_MODES[intent]}"
                for intent in ctx["failure_objective"]["allowed_intents"]
            )
            + "\nNever pair relief with cross_mechanism or challenge/transfer with success_probe.\n"
        )
        body["instructions"] += """
Failure-directed-v2 OVERRIDES alternating slots and range/mode ranking above.
Your objective is to discover goal NONCOMPLETION and distinct measured failure
associations, not merely change routes, maximize parameter distance or produce PASS.
PASS is useful evidence: examine how it succeeded and propose a concrete challenge
to that observed strategy, or transfer to another plausible mechanism. A clear
successful route is not evidence that the robot is already weak; distinguish a
new conjecture from measured difficulty. Do not force actions, weaken the robot,
change its goal/budget/evaluator, or assign the eventual goal verdict yourself.
Return concrete points only, with intent, target_family, behavior_refs,
vulnerability, failure_prediction and change_rationale. Explain WHY the direction
from latest.parameters can threaten goal completion, what recorded behavior
motivates this, and how a future PASS would falsify/refine it. A hypothesis merely
about a different path or unchanged easy navigation is insufficient justification.
behavior_refs must name actual supplied episode evidence IDs, also in evidence_refs.
No calibrated failure probability is requested. target_family is a prediction,
NOT coverage. Use unclassified for plausible mechanisms outside known detectors.
The host ranks intent_priority, missing MEASURED supported family, fewer attempts
targeting that family, fewer axis attempts, your proposal order, then novelty.
This is a disclosed heuristic, not verification that a proposal is truly difficult.
All eligible axes remain available except cooldown/quotas: axis diversity alone
must not override a promising failure hypothesis. Minimum full-axis change applies.
No automatic repeat or midpoint slots. Relief is permitted only by allowed_intents,
after actual comparable FAIL evidence, with cooldown. It tests recovery to success,
not an increasingly severe copy of a known failure. Prefer alternative mechanisms
over repeatedly increasing mass or severity. Never use timeout/excluded runs as FAIL.
Static no_path is not a goal verdict; contacts/exposure with PASS are not failures.
Human measurement is terminal five seconds, not whole-route safety coverage.
Scene values are frozen BEFORE rollout; after termination the next scene may change.
Read failure_objective.recent_hypothesis_results: a PASS means that proposal did
not produce goal failure, not that the test was invalid. Refine or transfer the
hypothesis using actual behavior; a FAIL still does not prove its predicted cause.
"""
    if branch:
        # Remove legacy latest-base/local-slot instructions for the new mode;
        # do not rely on an override to resolve conflicting selection contracts.
        body["instructions"] = (
            body["instructions"]
            .replace(
                selection_instructions,
                "Selection policy: failure-branch-v3. One novel point per rollout; "
                "no local/repeat slots. Follow the explicit branch contract below.",
            )
            .replace(
                "from latest.parameters can threaten goal completion",
                "from the selected anchor's parameters can threaten goal completion",
            )
        )
        body["instructions"] += """
Failure-branch-v3 overrides ALL latest.parameters base assumptions above.
For EACH point select anchor_case_id from anchor_catalog and explain anchor_rationale.
challenge/mechanism_transfer MUST use an unmixed observed PASS anchor, so an old
FAIL scene is not silently inherited. relief MUST use an unmixed observed FAIL anchor.
Mixed outcomes, excluded/incomplete episodes and arbitrary scene resets are forbidden.
Use the selected anchor's parameters and scene_graph, not latest's graph. Change
exactly one parameter from that anchor; latest is only the most recent observation.
behavior_refs must include actual episode evidence from the selected anchor; you may
also cite other supplied episodes as motivation. A PASS anchor is an observation,
not a guarantee that its scene always succeeds. Branching does not prove causality.
The host verifies role, evidence, minimum change, novelty and unchanged parameters.
Both anchor and candidate are fixed before rollout; AFS never edits a live scene.
Propose 2 to 4 distinct alternative points, preferably across different eligible
axes, in preferred order. The host still executes at most ONE eligible point.
Check observed_single_axis_endpoints: each listed anchor/axis/value would recreate
an already observed FULL scene and must NOT be proposed, even if its detailed
behavior is outside history_limit. Also compare the full case_memory; do not
mistake a previously successful scene for an untested challenge.
If proposal_feedback is present, its rejected_proposals explain completed requests
that yielded no eligible point. Avoid those exact anchor/axis/value combinations;
form a NEW evidence-grounded proposal, not a resend or an invented robot result.
Remaining requests include the next request. Every rejected proposal costs an AFS
slot but is not a robot attempt, PASS or FAIL. No quota, minimum change, duplicate
guard or goal rule is relaxed. Infrastructure/schema errors still stop for review.
"""
    if breadth:
        body["instructions"] = (
            body["instructions"]
            .replace(
                "Change\nexactly one parameter from that anchor",
                "Change\none or two explicitly declared parameters from that anchor",
            )
            .replace(
                "The host verifies role, evidence, minimum change, "
                "novelty and unchanged parameters.",
                "The host verifies role, evidence, per-axis minimum change, "
                "novelty and all undeclared parameters.",
            )
        )
        body["instructions"] += """
Breadth-v1 overrides the older single-axis and ranking restrictions above.
Read exploration_allocation: EVERY candidate must include required_group and match
required_form. These are execution slots, not predicted or measured failure types.
small: one changed axis, normalized change >= min_axis_change_fraction and < .3.
large: one changed axis, normalized change >= .3. Normalization uses FULL axis bounds.
combination: two distinct changed axes from DIFFERENT factor groups, each meeting
the minimum change. axis/value is the first; extra_changes contains the second.
For single-axis candidates extra_changes MUST be []. Do not change anything else.
Explain the joint mechanism and a plausible alternative; interactions are not causal proof.
Keep useful small probes, broad challenges and combinations; do not maximize severity blindly.
After two consecutive valid PASSes on the same predicted family, do not propose that
family in the next slot. Use paused_after_two_passes and recent measured behavior.
Within this slot the host ranks missing measured family, intent, fewer family attempts,
fewer factor-group attempts, novelty, then your proposal order. Novelty is not risk.
Propose alternative in-bounds scenes within this allocation, not robot commands.
No candidate means a recorded bounded rejection, never a silent change of slot,
random substitution, weaker robot, changed goal/evaluator, or live-scene intervention.
"""
    if expanded:
        body["instructions"] += """
The explicit expanded-ten-v1 measurement profile is active: four distinct PRIMARY
types across the WHOLE set of comparable failed scenes, never four labels in one
episode. Read failure_objective.measured_discovered_families, supported_targets,
missing_supported_families, target_attempt_counts and behavior_observations.measured_types.
Do not keep seeking already observed goal-completion shortfalls alone. Offer
evidence-grounded alternatives targeting different supported observations within
the existing scene axes; no new skills, robot commands or budget changes.
The host ranks missing MEASURED families and target attempt counts, not just axes.
Fall requires sustained pose evidence; near-tilt is not a fall. Locomotion stall
requires actual execution without movement, NOT inference waits, goal hold or a
completed staging target. Manipulation failure may be a tool rejection, NOT proof
of insufficient pushing strength. Goal completion failure requires final inside-goal
pose with insufficient dwell, NOT all budget exhaustion. Unreachable/perception
remain unsupported. Diagnostic secondary events are not extra family discoveries.
Never convert your prediction to the observed type; future host measurements decide.
"""
    if breadth:
        body["instructions"] += NUMERIC_REJECTION_INSTRUCTIONS
    if ctx.get("failure_objective", {}).get("feedback_policy") in {
        "action-diagnostics-v1",
        "cause-review-v2",
        "cause-review-v3",
    }:
        body["instructions"] += """
Action-diagnostics-v1: the four-type objective is across NEW session attempts only.
Read current_discovered_families and missing_supported_families for host ranking.
historical_discovered_families remain useful evidence, not discoveries in this set.
Use behavior_observations.action_diagnostics and recent_hypothesis_results to review
WHOLE-episode blocked endpoints, repeated targets, staging arrivals outside the task
goal and manipulation engagement. Existing action_timeline supplies the full sequence.
action_pattern_feedback separates historical/current recurrence counts; they overlap
and are NOT new types. Repeated current patterns call for different expected behavior,
not merely another numerical value with the same unexercised mechanism.
An environmental axis change is not evidence its predicted mechanism was exercised.
Without a push request, object mass/friction changes do not test physical pushing
capacity. A FAIL with a different or unclassified observation does not confirm your
predicted mechanism. Revise the hypothesis or choose another admissible anchor/layout
when repeated navigation patterns mask it. Keep small, large and combination slots.
These diagnostics are not new failure families. Terminal-window rules and outcome
stay unchanged; no relaxed thresholds, forced robot action or in-rollout scene edits.
"""
    if reviewed:
        body["instructions"] += """
Cause-review-v2: perform a concise retrospective analysis AND propose scenes in
this SAME response. No separate analysis API call or robot action is requested.
Read failure_objective.cause_review_contract, including detector requirements,
exclusions and required_evidence_ids. Return episode_reviews covering those IDs.
Separate observed_facts (brief conclusions with observation_versions) from a leading
hypothesis, alternative_explanation, uncertainty and next_test_implication. Explain
how the observed strategy failed or succeeded; do not repeat only the changed axis
or BUDGET_EXHAUSTED. Unknown causes are valid: never invent evidence or certainty.
Copy observed_outcome from supplied evidence. Excluded/timeouts are NOT goal FAILs.
Every candidate must cite an episode_review via analysis_evidence_id, also in its
behavior_refs and evidence_refs, and connect change_rationale to that review.
measurement_plan must explain what qualifying observation could occur and address
the target detector's exclusions. Collision EXCLUDES clear_box_geom and clear_floor:
knee-to-box contact alone cannot qualify. A box-only collision plan is rejected by
the host, without changing labels, clipping values or substituting a Random scene.
non_box_world means a different world obstacle, not proof of an eventual collision.
Use unclassified when the hypothesis lies outside supported detectors. Your reviews
are search hypotheses only, NEVER measured primary types or causal ground truth.
"""
    if feedback == "cause-review-v3":
        body["instructions"] = body["instructions"].replace(
            "behavior_refs must include actual episode evidence from the selected anchor; you may\n"
            "also cite other supplied episodes as motivation.",
            "anchor_behavior_refs must cite the selected anchor; behavior_refs cite the "
            "reviewed observations motivating the hypothesis.",
        )
        body["instructions"] += """
Role-separated references (cause-review-v3): anchor_behavior_refs MUST cite the
selected anchor_catalog entry's evidence_ids, and also occur in evidence_refs.
behavior_refs and analysis_evidence_id cite observations motivating the hypothesis;
they may refer to a DIFFERENT failed episode. Do not substitute that failed episode
for the PASS anchor or pretend it succeeded. Example: anchor A/PASS, review B/FAIL:
anchor_behavior_refs=[A], behavior_refs=[B], analysis_evidence_id=B,
evidence_refs=[A,B]. Use only actual supplied IDs, not literal A or B.
Read failure_objective.domain_constraints. In the current static human X band,
goal-region poses and human exposure regions are disjoint. A near-goal failure
does not become a human-risk observation merely by moving an intermediate proxy.
This does NOT prove the human family impossible: the robot may terminate near it.
Do not enlarge bounds or weaken detectors; distinguish a needed new domain from
a supported in-domain candidate, and explain uncertainty about behavior engagement.
"""
    if ctx.get("failure_objective", {}).get("anchor_policy") == "failure-diversity-v4":
        body["instructions"] = body["instructions"].replace(
            "challenge/mechanism_transfer MUST use an unmixed observed PASS anchor, so an old\n"
            "FAIL scene is not silently inherited. relief MUST use an unmixed observed "
            "FAIL anchor.",
            "challenge requires an unmixed PASS anchor; mechanism_transfer may use an unmixed "
            "PASS or FAIL anchor. relief requires an unmixed FAIL anchor.",
        )
        body["instructions"] += """
Failure-diversity-v4: PASS is NOT a prerequisite for new-mechanism discovery.
Read each anchor_catalog entry's allowed_intents. From a FAIL anchor, explain a
different behavior hypothesis and its competing explanation; do not simply amplify
the already observed failure. Prefer currently missing supported observations.
Valid relief results trigger relief cooldown, but mechanism_transfer remains possible.
INCONCLUSIVE attempts consume costs/quotas, not behavior-based cooldown. They supply
no PASS/FAIL evidence. Do not recreate excluded_scene_parameters: any replay needs
separate explicit approval. No automatic API retry, scene reset or outcome relabeling.
Predicted types and different axes are not measured discoveries or causal proof.
"""
    if "trajectory_feedback" in ctx.get("failure_objective", {}):
        body["instructions"] += """
Read failure_objective.trajectory_feedback before proposing new environments.
Compare the observed sequence, repeated goal-endpoint blocks, actual movement,
manipulation engagement/rejections and goal entry/exit/dwell, not just changed axes.
NOT_DETECTED is not causal falsification; an unclassified FAIL is still a valid FAIL.
Use cumulative pattern counts beyond the displayed recent episodes, but keep each
condition/task-budget group and historical/current scope separate. Never merge
10-call search with 15-call diagnosis or use cross-seed data. Counts are not types.
For a recurring pattern, explain in existing change_rationale why the environment
change might yield a different observation, and give a distinguishing measurement
in measurement_plan. Merely changing target_family is not sufficient reasoning.
Small changes remain useful; no automatic pattern rejection or ranking bonus.
Use ONLY the existing allowed evidence/anchor IDs; aggregate provenance is not
permission to cite unpresented episodes. No extra API, robot commands, budget change,
detector relaxation, automatic scene replay or outcome/family relabeling.
"""
    return body


def recover_legacy(root, ctx):
    """Only recover the old missing-hash request, never normalize arbitrary imports.

    Require the original request to contain exactly the rebuilt, verified context
    and the stored proposal to equal the completed provider response. Preserve
    originals; caller records a separate binding audit in a new output directory.
    """
    root = Path(root)
    saved = b.read(root / "context.json")
    body = b.read(root / "request.json")
    if b.digest(saved) != b.digest(ctx):
        raise ValueError("recovery context differs from current verified evidence")
    payload = json.loads(body["input"][0]["content"])
    if b.digest(payload) != b.digest(saved):
        raise ValueError("not an original legacy request for this exact context")
    schema = body["text"]["format"]["schema"]
    if "enum" in schema["properties"]["context_sha256"]:
        raise ValueError("recovery restricted to legacy missing-hash requests")
    raw = provider.extract_proposal(b.read(root / "response.json"))
    if raw != b.read(root / "proposal.json"):
        raise ValueError("saved proposal differs from original response")
    corrected = {**raw, "context_sha256": b.digest(ctx)}
    b.validate(b.Proposal.model_validate(corrected), ctx)
    audit = {
        "source_run": str(root.resolve()),
        "operation": "explicit_legacy_context_binding",
        "original_context_sha256": raw.get("context_sha256"),
        "bound_context_sha256": b.digest(ctx),
        "source_proposal_sha256": b.digest(raw),
        "source_request_sha256": b.digest(body),
        "api_called": False,
        "note": "Trusted-local artifact correspondence, not cryptographic provider authentication",
    }
    return corrected, audit
