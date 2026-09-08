"""Bounded, revision-preserving scene mutation and sequential navigation AFS pilot.

This is a local scene-bundle search, not the legacy Panda AFS or a remote mutation API.
Only evaluated valid rollouts may be supplied as observations.
"""

import math
from dataclasses import replace

import numpy as np
from scipy.stats import qmc
from sklearn.ensemble import ExtraTreesRegressor

from .core import navigation_map, scene_graph

BOUNDS = np.array([[-2.0, 2.0], [-2.4, 2.4]])
VERSION = "g1-scene-search-v1"


class InvalidScene(ValueError):
    """Geometric rejection, not a robot failure."""


def move_obstacle(base, offsets, object_id="obstacle_0"):
    values = np.asarray(offsets, dtype=float)
    if values.shape != (2,) or not np.isfinite(values).all():
        raise InvalidScene("INVALID_PARAMETERS")
    if np.any(values < BOUNDS[:, 0]) or np.any(values > BOUNDS[:, 1]):
        raise InvalidScene("OUT_OF_BOUNDS")
    graph = scene_graph(base).to_dict()
    # The graph and physics share the same immutable SceneSpec object IDs.
    if not any(o["id"] == object_id for o in graph["objects"]):
        raise InvalidScene("UNKNOWN_GRAPH_OBJECT")
    source = next(b for b in base.boxes if b.id == object_id)
    if not source.mutable or source.category != "obstacle":
        raise InvalidScene("IMMUTABLE_OBJECT")
    moved = replace(
        source,
        position=(
            source.position[0] + values[0],
            source.position[1] + values[1],
            source.position[2],
        ),
    )
    for axis, extent in enumerate((base.config.width, base.config.height)):
        if (
            not moved.size[axis] / 2
            <= moved.position[axis]
            <= (extent * base.config.cell_size_m - moved.size[axis] / 2)
        ):
            raise InvalidScene("OUTSIDE_FLOOR")
    for other in base.boxes:
        if other.id != object_id and all(
            abs(a - b) < (sa + sb) / 2 - 1e-9
            for a, b, sa, sb in zip(moved.position, other.position, moved.size, other.size)
        ):
            raise InvalidScene("GEOMETRY_OVERLAP")
    derived = replace(base, boxes=tuple(moved if b.id == object_id else b for b in base.boxes))
    nav = navigation_map(derived)
    if not nav["reachable"] or not nav["all_region_centers_reachable"]:
        raise InvalidScene("NO_PATH")
    return derived


def outcome(result, duration):
    """Versioned search utility, NOT a calibrated physical robustness margin.

    All valid failures rank below successes. Within successes favor low time slack;
    within failures favor greater remaining goal distance. Invalid execution is excluded.
    """
    execution, facts = result["execution"], result.get("task_facts", {})
    if execution["status"] != "SUCCEEDED" or not execution["valid"]:
        return None
    success = facts.get("navigation_success")
    elapsed, distance = facts.get("elapsed_simulation_s"), facts.get("goal_distance_m")
    if type(success) is not bool or not all(
        isinstance(v, (float, int)) and math.isfinite(v) for v in (elapsed, distance)
    ):
        return None
    utility = max(0.001, 1 - elapsed / duration) if success else -1 - min(distance / 10, 1)
    return {"failure": not success, "utility": utility}


class SceneSearch:
    """Rebuildable sampler; journal rows are the complete adaptive state.

    ExtraTrees ensemble disagreement is heuristic uncertainty, not a posterior.
    Common Sobol cold-start for Sobol and AFS; invalids never train the surrogate.
    """

    def __init__(self, method, seed, cold_start=4):
        if method not in {"random", "sobol", "afs"}:
            raise ValueError("unknown method")
        self.method, self.seed, self.cold_start = method, seed, cold_start

    def propose(self, rows):
        attempt = len(rows)
        rng = np.random.default_rng(np.random.SeedSequence([self.seed, attempt]))
        valid = [r for r in rows if r.get("evaluation") is not None]
        metadata = {"phase": "cold_start", "training_count": len(valid)}
        if self.method == "random":
            point = rng.random(2)
            metadata["phase"] = "random"
        elif self.method == "sobol" or len(valid) < self.cold_start:
            engine = qmc.Sobol(2, scramble=True, seed=self.seed)
            if attempt:
                engine.fast_forward(attempt)
            point = engine.random(1)[0]
            metadata["phase"] = "sobol" if self.method == "sobol" else "cold_start"
        else:
            x = np.array([r["offsets"] for r in valid])
            x = (x - BOUNDS[:, 0]) / np.diff(BOUNDS, axis=1).ravel()
            y = np.array([r["evaluation"]["utility"] for r in valid])
            model = ExtraTreesRegressor(n_estimators=64, random_state=self.seed, n_jobs=1)
            model.fit(x, y)
            pool = rng.random((512, 2))
            predictions = np.array([tree.predict(pool) for tree in model.estimators_])
            # Include invalid proposals in novelty to discourage repeated rejected neighborhoods.
            seen = (np.array([r["offsets"] for r in rows]) - BOUNDS[:, 0]) / np.diff(
                BOUNDS, axis=1
            ).ravel()
            novelty = np.linalg.norm(pool[:, None] - seen[None, :], axis=2).min(axis=1)
            score = predictions.mean(axis=0) - predictions.std(axis=0) - 0.1 * novelty
            chosen = int(np.argmin(score))
            point = pool[chosen]
            metadata.update(
                phase="adaptive",
                predicted_utility=float(predictions[:, chosen].mean()),
                ensemble_std=float(predictions[:, chosen].std()),
                acquisition=float(score[chosen]),
            )
        return (BOUNDS[:, 0] + point * np.diff(BOUNDS, axis=1).ravel()).tolist(), metadata
