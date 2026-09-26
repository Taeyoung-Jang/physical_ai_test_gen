"""Host-computed context binding and explicit trusted-local legacy recovery."""

import json
from pathlib import Path

from . import behavior as b
from . import provider


def request(ctx, model):
    expected = b.digest(ctx)
    schema = b.Proposal.model_json_schema()
    schema["properties"]["context_sha256"]["enum"] = [expected]
    body = provider.request_body({"context_sha256": expected, "context": ctx}, schema)
    body.update(
        model=model,
        instructions=b.INSTRUCTIONS
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
