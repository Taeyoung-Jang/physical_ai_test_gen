"""Host-computed context binding and explicit trusted-local legacy recovery."""

import json
from pathlib import Path
from typing import Literal

from . import behavior as b
from . import provider

SELECTION_POLICIES = {
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
    selection_policy: Literal["standalone_suite", "campaign_single_endpoint"] = "standalone_suite",
):
    """Bind both evidence and the caller's actual candidate-selection instructions."""
    if selection_policy not in SELECTION_POLICIES:
        raise ValueError("unknown behavior AFS selection policy")
    context_schema, selection_instructions = SELECTION_POLICIES[selection_policy]
    if ctx.get("schema_version") != context_schema:
        raise ValueError("behavior AFS selection policy does not match context schema")
    expected = b.digest(ctx)
    schema = b.Proposal.model_json_schema()
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
