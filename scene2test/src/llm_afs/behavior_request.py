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
    schema = b.Proposal.model_json_schema()
    schema["$defs"]["Space"]["properties"]["axis"]["enum"] = list(b.context_axes(ctx))
    if selection_policy == "autonomous_development_endpoint":
        selectable = ctx["development_search"]["selectable_axes"]
        if not selectable or not set(selectable) <= set(b.context_axes(ctx)):
            raise ValueError("invalid autonomous selectable axes")
        schema["$defs"]["Space"]["properties"]["axis"]["enum"] = selectable
    schema["$defs"]["Space"]["properties"]["evidence_refs"]["items"]["enum"] = b.evidence_ids(ctx)
    schema["properties"]["context_sha256"]["enum"] = [expected]
    body = provider.request_body({"context_sha256": expected, "context": ctx}, schema)
    body.update(
        model=model,
        instructions=b.INSTRUCTIONS
        + "\n"
        + selection_instructions
        + "\nCopy context_sha256 from the request exactly; never compute or invent it.",
    )
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
