"""Read-only robot compatibility evidence. No policy step, IK, or push execution."""

import hashlib
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import yaml


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def joint_table(model):
    rows = []
    for a in range(model.nu):
        j = int(model.actuator_trnid[a, 0])
        rows.append(
            {
                "actuator": model.actuator(a).name,
                "joint": model.joint(j).name,
                "qpos_adr": int(model.jnt_qposadr[j]),
                "dof_adr": int(model.jnt_dofadr[j]),
                "range_rad": model.jnt_range[j].tolist(),
                "force_range": model.actuator_forcerange[a].tolist(),
            }
        )
    return rows


def inspect(source, combined):
    from simulation_server.groot_locomotion import G1OnnxController

    baseline = mujoco.MjModel.from_xml_path(str(source))
    before, after = joint_table(baseline), joint_table(combined)
    if before != after or baseline.nu != 29:
        raise ValueError("G1 actuator/joint address or limit identity changed")
    if combined.nq != baseline.nq + 7 or combined.nv != baseline.nv + 6:
        raise ValueError("expected exactly one appended free body")
    boxj = combined.joint("clear_box_free").id
    if (
        int(combined.jnt_qposadr[boxj]) != baseline.nq
        or int(combined.jnt_dofadr[boxj]) != baseline.nv
    ):
        raise ValueError("box must not precede robot joint state")
    cfg = yaml.safe_load(source.with_suffix(".yaml").read_text())
    for key in ("cmd_scale", "default_angles"):
        cfg[key] = np.asarray(cfg[key], dtype=np.float32)
    observations = []
    for model in (baseline, combined):
        controller = G1OnnxController.__new__(G1OnnxController)
        controller.model, controller.data, controller.config = model, mujoco.MjData(model), cfg
        controller.command = np.zeros(3, dtype=np.float32)
        controller.action = np.zeros(cfg["num_actions"], dtype=np.float32)
        for i, row in enumerate(before[: cfg["num_actions"]]):
            controller.data.qpos[row["qpos_adr"]] = cfg["default_angles"][i]
        observations.append(controller._observation())
    if not np.array_equal(*observations):
        raise ValueError("appended box changed legacy gait observation")
    data = initial_data(combined, source)
    # Kinematic controllability at one pose is not dynamic manipulation feasibility.
    palms = []
    for side in ("left", "right"):
        arm = [
            r
            for r in after
            if r["joint"].startswith(side + "_")
            and any(s in r["joint"] for s in ("shoulder", "elbow", "wrist"))
        ]
        sid = combined.site(f"{side}_push_site").id
        jp, jr = np.zeros((3, combined.nv)), np.zeros((3, combined.nv))
        mujoco.mj_jacSite(combined, data, jp, jr, sid)
        collision_geoms = []
        for g in range(combined.ngeom):
            mesh = int(combined.geom_dataid[g])
            if combined.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH and mesh >= 0:
                if combined.mesh(mesh).name == f"{side}_hand_palm_link" and (
                    combined.geom_contype[g] or combined.geom_conaffinity[g]
                ):
                    collision_geoms.append(g)
        palms.append(
            {
                "side": side,
                "arm_joints": arm,
                "palm_collision_geom_ids": collision_geoms,
                "push_site_world_m": data.site_xpos[sid].tolist(),
                "position_jacobian_rank_at_initial_pose": int(
                    np.linalg.matrix_rank(jp[:, [r["dof_adr"] for r in arm]])
                ),
            }
        )
    finger_joints = [
        combined.joint(i).name
        for i in range(combined.njnt)
        if any(s in combined.joint(i).name for s in ("thumb", "index", "middle"))
    ]
    root = ET.parse(source).getroot()
    meshdir = source.parent / root.find("compiler").get("meshdir", "")
    sources = [
        source,
        source.with_suffix(".yaml"),
        *[meshdir / e.get("file") for e in root.findall("asset/mesh")],
    ]
    policy = source.parent / "policy/GR00T-WholeBodyControl-Walk.onnx"
    if policy.exists():
        sources.append(policy)
    return {
        "schema_version": "clear-path-robot-audit-v1",
        "robot_actuators": combined.nu,
        "baseline_nq_nv": [baseline.nq, baseline.nv],
        "combined_nq_nv": [combined.nq, combined.nv],
        "robot_joint_identity_preserved": True,
        "gait_observation_equal": True,
        "gait_observation_size": len(observations[0]),
        "joint_mapping": after,
        "palms": palms,
        "active_finger_joints": finger_joints,
        "walk_onnx_present": policy.exists(),
        "source_sha256": {str(p): sha256(p) for p in sources},
        "push_executor_available": False,
        "gpu_policy_executed": False,
        "decision": "Palm/arm target adapter candidate; P2 physical validation required.",
        "limitations": [
            "Current legacy controller holds 14 upper joints at zero",
            "No grasp executor; finger meshes are fixed in this asset",
            "Jacobian rank does not prove reachability, force control or stable pushing",
        ],
    }


def initial_data(model, source):
    data = mujoco.MjData(model)
    cfg = yaml.safe_load(source.with_suffix(".yaml").read_text())
    for row, value in zip(joint_table(model), cfg["default_angles"]):
        data.qpos[row["qpos_adr"]] = value
    mujoco.mj_forward(model, data)
    return data
