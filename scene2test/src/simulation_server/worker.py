from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

from failure_client.contracts import (
    ArtifactRef,
    ExecutionSummary,
    RemoteJobState,
    RolloutRequest,
    RolloutResult,
    StandardEvent,
)


def _artifact(job_id: str, path: Path, kind: str) -> ArtifactRef:
    payload = path.read_bytes()
    return ArtifactRef(
        artifact_id=f"{job_id}:{path.name}",
        kind=kind,
        format=path.suffix.lstrip(".") or "jsonl",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def run_groot(request: RolloutRequest, output: Path, groot_root: Path) -> RolloutResult:
    import mujoco
    import numpy as np
    import yaml

    scene = groot_root / "decoupled_wbc/control/robot_model/model_data/g1/scene_43dof.xml"
    config_path = groot_root / "decoupled_wbc/control/main/teleop/configs/g1_29dof_gear_wbc.yaml"
    config = yaml.safe_load(config_path.read_text())
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    model.opt.timestep = request.execution.physics_timestep_s or float(config["SIMULATE_DT"])
    if model.nkey:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    for operation in request.interventions:
        if operation.kind == "robot_initial_state.set_spawn" or (
            operation.operation_id == "set_robot_spawn"
            and operation.kind == "robot_initial_state"
        ):
            position = operation.parameters.get("position_m")
            quaternion = operation.parameters.get("quaternion_wxyz")
            if position is not None:
                data.qpos[:3] = np.asarray(position, dtype=float)
            if quaternion is not None:
                data.qpos[3:7] = np.asarray(quaternion, dtype=float)
            mujoco.mj_forward(model, data)
    target = data.qpos[7 : 7 + model.nu].copy()
    kp = np.asarray(config["MOTOR_KP"], dtype=float)
    kd = np.asarray(config["MOTOR_KD"], dtype=float)
    if model.nu > kp.size:
        kp = np.pad(kp, (0, model.nu - kp.size), constant_values=20.0)
        kd = np.pad(kd, (0, model.nu - kd.size), constant_values=1.0)
    state_path, action_path, contact_path = (
        output / "state_trajectory.jsonl",
        output / "action_trajectory.jsonl",
        output / "contacts.jsonl",
    )
    duration = request.execution.maximum_duration_s
    events: list[StandardEvent] = []
    fallen = False
    with (
        state_path.open("w") as states,
        action_path.open("w") as actions,
        contact_path.open("w") as contacts,
    ):
        while data.time < duration:
            q = data.qpos[7 : 7 + model.nu]
            dq = data.qvel[6 : 6 + model.nu]
            data.ctrl[:] = kp[: model.nu] * (target - q) - kd[: model.nu] * dq
            mujoco.mj_step(model, data)
            states.write(
                json.dumps(
                    {"time_s": data.time, "qpos": data.qpos.tolist(), "qvel": data.qvel.tolist()}
                )
                + "\n"
            )
            actions.write(json.dumps({"time_s": data.time, "ctrl": data.ctrl.tolist()}) + "\n")
            for index in range(data.ncon):
                contact = data.contact[index]
                contacts.write(
                    json.dumps(
                        {
                            "time_s": data.time,
                            "geom1": int(contact.geom1),
                            "geom2": int(contact.geom2),
                            "position_m": contact.pos.tolist(),
                        }
                    )
                    + "\n"
                )
            base_height = float(data.qpos[2])
            if not fallen and base_height < 0.45:
                fallen = True
                events.append(
                    StandardEvent(
                        event_type="BASE_HEIGHT_THRESHOLD_CROSSED",
                        timestamp_s=float(data.time),
                        measurements={"base_height_m": base_height, "threshold_m": 0.45},
                    )
                )
    job_id = output.name
    reproduction = {
        "job_id": job_id,
        "resolved_resources": request.resources.model_dump(mode="json"),
        "runtime": {
            "backend": "groot_mujoco",
            "python_version": platform.python_version(),
            "mujoco_version": mujoco.__version__,
            "groot_root": str(groot_root),
        },
        "randomness": {"master_seed": request.execution.seed},
        "execution": {"physics_timestep_s": model.opt.timestep, "duration_s": duration},
    }
    reproduction_path = output / "reproduction.json"
    reproduction_path.write_text(json.dumps(reproduction, indent=2, sort_keys=True))
    return RolloutResult(
        job_id=job_id,
        execution=ExecutionSummary(
            valid=True,
            status=RemoteJobState.SUCCEEDED,
            termination_reason="MAX_DURATION",
            determinism_level="BEST_EFFORT",
        ),
        task_facts={"standing_at_end": not fallen, "final_base_height_m": float(data.qpos[2])},
        standard_events=events,
        summary_metrics={
            "simulation_steps": int(data.time / model.opt.timestep),
            "contact_samples": sum(1 for _ in contact_path.open(encoding="utf-8")),
        },
        artifacts=[
            _artifact(job_id, state_path, "state_trajectory"),
            _artifact(job_id, action_path, "action_trajectory"),
            _artifact(job_id, contact_path, "contacts"),
            _artifact(job_id, reproduction_path, "reproduction_manifest"),
        ],
        reproduction=reproduction,
    )


def run_probe(request: RolloutRequest, output: Path, groot_root: Path) -> RolloutResult:
    """Dependency-free backend used only by contract tests."""
    job_id = output.name
    reproduction = {
        "job_id": job_id,
        "runtime": {"backend": "probe"},
        "resolved_resources": request.resources.model_dump(mode="json"),
    }
    path = output / "reproduction.json"
    path.write_text(json.dumps(reproduction, sort_keys=True))
    return RolloutResult(
        job_id=job_id,
        execution=ExecutionSummary(
            valid=False,
            status=RemoteJobState.SUCCEEDED,
            termination_reason="PROBE_BACKEND_NO_SIMULATION",
        ),
        artifacts=[_artifact(job_id, path, "reproduction_manifest")],
        reproduction=reproduction,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--groot-root", type=Path, required=True)
    parser.add_argument("--backend", choices=("groot_mujoco", "probe"), required=True)
    args = parser.parse_args()
    request = RolloutRequest.model_validate_json(args.request.read_text())
    result = (run_groot if args.backend == "groot_mujoco" else run_probe)(
        request, args.output, args.groot_root
    )
    (args.output / "execution_result.json").write_text(
        result.model_dump_json(by_alias=True, indent=2)
    )


if __name__ == "__main__":
    main()
