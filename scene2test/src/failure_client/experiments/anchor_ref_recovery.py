"""Only restore an omitted anchor behavior reference already explicitly cited."""

from copy import deepcopy


def normalize_anchor_refs(raw, ctx):
    from failure_client.methods.cause_review import validate_reviews
    from llm_afs import behavior as b

    if ctx["development_search"]["budget"].get("feedback_policy") != "cause-review-v2":
        raise ValueError("anchor reference recovery requires original cause-review-v2")
    proposal = b.ReviewedBreadthProposal.model_validate(raw)
    b.validate(proposal, ctx)
    validate_reviews(proposal, ctx)
    fixed = deepcopy(raw)
    changed = False
    for n, space in enumerate(proposal.spaces):
        anchor = next(
            (a for a in ctx["anchor_catalog"] if a["case_id"] == space.anchor_case_id), None
        )
        if anchor is None or anchor["role"] != (
            "observed_failure" if space.intent == "relief" else "success_control"
        ):
            raise ValueError("anchor identity/role cannot be repaired")
        if set(space.behavior_refs) & set(anchor["evidence_ids"]):
            continue
        declared = [ref for ref in anchor["evidence_ids"] if ref in space.evidence_refs]
        if len(declared) != 1:
            raise ValueError("requires exactly one already-cited anchor evidence ID")
        fixed["spaces"][n]["behavior_refs"].append(declared[0])
        changed = True
    if not changed:
        raise ValueError("no omitted anchor behavior reference")
    return fixed


def recover_anchor_refs(source, output, *, apply=False, fingerprint_fn=None):
    from .numeric_recovery import recover_numeric

    return recover_numeric(
        source, output, apply=apply, fingerprint_fn=fingerprint_fn, reference_repair=True
    )
