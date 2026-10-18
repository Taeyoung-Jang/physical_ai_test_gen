"""Host-computed context binding and explicit trusted-local legacy recovery."""

import json
from pathlib import Path
from typing import Literal

from . import behavior as b
from . import provider

SELECTION_POLICIES = {
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
    ] = "standalone_suite",
):
    """Bind both evidence and the caller's actual candidate-selection instructions."""
    if selection_policy not in SELECTION_POLICIES:
        raise ValueError("unknown behavior AFS selection policy")
    context_schema, selection_instructions = SELECTION_POLICIES[selection_policy]
    if ctx.get("schema_version") != context_schema:
        raise ValueError("behavior AFS selection policy does not match context schema")
    expected = b.digest(ctx)
    autonomous = selection_policy == "autonomous_development_endpoint"
    branch = ctx.get("development_search", {}).get("selection_policy") == "failure-branch-v3"
    directed = (
        branch or ctx.get("development_search", {}).get("selection_policy") == "failure-directed-v2"
    )
    expanded = (
        branch
        and ctx.get("development_search", {}).get("budget", {}).get("taxonomy_profile")
        == "expanded-ten-v1"
    )
    if directed and not autonomous:
        raise ValueError("failure-directed context requires autonomous endpoint policy")
    schema = (
        b.ExpandedBranchProposal
        if expanded
        else b.BranchProposal
        if branch
        else b.FailureProposal
        if directed
        else b.EndpointProposal
        if autonomous
        else b.Proposal
    ).model_json_schema()
    selectable = list(b.context_axes(ctx))
    if autonomous:
        selectable = ctx["development_search"]["selectable_axes"]
        if not selectable or not set(selectable) <= set(b.context_axes(ctx)):
            raise ValueError("invalid autonomous selectable axes")
    for definition in schema["$defs"].values():
        properties = definition["properties"]
        properties["axis"]["enum"] = selectable
        properties["evidence_refs"]["items"]["enum"] = b.evidence_ids(ctx)
        if directed:
            objective = ctx["failure_objective"]
            properties["behavior_refs"]["items"]["enum"] = objective["behavior_evidence_ids"]
            properties["intent"]["enum"] = objective["allowed_intents"]
            properties["target_family"]["enum"] = objective["supported_targets"]
            if branch:
                properties["anchor_case_id"]["enum"] = [c["case_id"] for c in ctx["anchor_catalog"]]
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
