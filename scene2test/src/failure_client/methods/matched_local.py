"""Shared fixed-base local changes; no outcome-driven Random draws."""

from clear_path.search_domain import check_parameters, checked_domain
from failure_client.methods.behavior_feedback import seeded

VERSION = "matched-local-v1"


def validate_design(spec, domain, minimum):
    if set(spec) != {"schema_version", "base_parameters", "change_counts"}:
        raise ValueError("explicit matched-local contract required")
    if (
        spec["schema_version"] != VERSION
        or spec["change_counts"] != [1, 2]
        or any(type(n) is not int for n in spec["change_counts"])
    ):
        raise ValueError("matched local requires predeclared alternating [1,2] changes")
    check_parameters(spec["base_parameters"], domain)
    if not 0 < minimum < 0.3:
        raise ValueError("matched local requires common minimum change below .3")


def change_count(spec, index):
    return spec["change_counts"][index % len(spec["change_counts"])]


def check_candidate(params, spec, domain, count, minimum):
    check_parameters(params, domain)
    base, axes = spec["base_parameters"], checked_domain(domain)
    changed = [a for a in axes if params[a] != base[a]]
    if len(changed) != count or any(
        abs(params[a] - base[a]) / (axes[a][1] - axes[a][0]) + 1e-12 < minimum for a in changed
    ):
        raise ValueError("candidate violates shared fixed-base change count/minimum")
    return changed


def random_candidate(spec, domain, minimum, seed, index):
    """Uniform axis subset; values uniform on allowed intervals outside minimum gap."""
    axes, base = checked_domain(domain), spec["base_parameters"]
    rng = seeded(seed, VERSION, index)
    count = change_count(spec, index)
    chosen = rng.sample(list(axes), count)
    params = dict(base)
    for axis in chosen:
        lo, hi = axes[axis]
        delta = minimum * (hi - lo)
        intervals = [(lo, base[axis] - delta), (base[axis] + delta, hi)]
        intervals = [(a, b) for a, b in intervals if b > a]
        offset = rng.random() * sum(b - a for a, b in intervals)
        for a, b in intervals:
            if offset < b - a:
                params[axis] = a + offset
                break
            offset -= b - a
    changed = check_candidate(params, spec, domain, count, minimum)
    return {
        "stage": "discovery",
        "strategy": "matched_local_uniform_random",
        "axis": changed[0],
        "changed_axes": changed,
        "parameters": params,
        "evidence": {"source": "uniform axis subset and admissible values; no outcomes used"},
        "scheduler": {"seed": seed, "local_index": index, "change_count": count},
        "branch_audit": {
            "before": {a: base[a] for a in changed},
            "after": {a: params[a] for a in changed},
            "unchanged_parameters_verified": True,
        },
    }
