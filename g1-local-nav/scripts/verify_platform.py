"""Milestone 0 — platform audit.

g1-sim and g1-vlm are separate venvs (blueprint §5.1, dependency/fault isolation), so this
script only checks whatever is importable in the venv it's run under and reports the rest as
"skipped: different venv" rather than failing on it. Run it once from each venv to cover
everything:

    envs/.venv-g1-sim/bin/python scripts/verify_platform.py
    envs/.venv-g1-vlm/bin/python scripts/verify_platform.py

CYCLONEDDS_HOME must be set when running under g1-sim (see envs/SETUP_NOTES.md) — the
cyclonedds Python binding needs the native C library location to load against.

Exits 0 only if every check that *could* run in this venv actually passed. Writes a JSON
report to runs/platform_audit_<venv>.json.
"""
from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def check_arch() -> dict:
    machine = platform.machine()
    return {
        "name": "arch_arm64",
        "status": "pass" if machine == "arm64" else "fail",
        "detail": f"platform.machine()={machine}, python={platform.python_version()}",
    }


def check_mujoco() -> dict:
    try:
        import mujoco
    except ImportError as e:
        return {"name": "mujoco", "status": "skip", "detail": f"not importable here: {e}"}
    try:
        xml = "<mujoco><worldbody><geom type='plane' size='1 1 0.1'/>" \
              "<body pos='0 0 1'><joint type='free'/><geom type='sphere' size='0.1'/>" \
              "</body></worldbody></mujoco>"
        m = mujoco.MjModel.from_xml_string(xml)
        d = mujoco.MjData(m)
        for _ in range(10):
            mujoco.mj_step(m, d)
        return {
            "name": "mujoco", "status": "pass",
            "detail": f"mujoco {mujoco.__version__}, stepped OK, ball z={d.qpos[2]:.4f}",
        }
    except Exception as e:
        return {"name": "mujoco", "status": "fail", "detail": str(e)}


def check_onnxruntime() -> dict:
    try:
        import onnxruntime as ort
    except ImportError as e:
        return {"name": "onnxruntime", "status": "skip", "detail": f"not importable here: {e}"}
    try:
        providers = ort.get_available_providers()
        return {
            "name": "onnxruntime", "status": "pass",
            "detail": f"onnxruntime {ort.__version__}, providers={providers}",
        }
    except Exception as e:
        return {"name": "onnxruntime", "status": "fail", "detail": str(e)}


def check_mlx_metal() -> dict:
    try:
        import mlx.core as mx
    except ImportError as e:
        return {"name": "mlx_metal", "status": "skip", "detail": f"not importable here: {e}"}
    try:
        a = mx.array([1.0, 2.0, 3.0])
        mx.eval(a * 2)
        device = mx.default_device()
        ok = "gpu" in str(device).lower()
        return {
            "name": "mlx_metal",
            "status": "pass" if ok else "fail",
            "detail": f"default_device={device}",
        }
    except Exception as e:
        return {"name": "mlx_metal", "status": "fail", "detail": str(e)}


def check_unitree_dds() -> dict:
    try:
        import unitree_sdk2py  # noqa: F401
        from cyclonedds.domain import DomainParticipant
    except ImportError as e:
        return {"name": "unitree_dds", "status": "skip", "detail": f"not importable here: {e}"}
    try:
        dp = DomainParticipant()
        return {"name": "unitree_dds", "status": "pass", "detail": f"DomainParticipant created: {dp}"}
    except Exception as e:
        return {"name": "unitree_dds", "status": "fail", "detail": str(e)}


def check_lerobot_g1() -> dict:
    try:
        from lerobot.robots.unitree_g1.gr00t_locomotion import GrootLocomotionController  # noqa: F401
        from lerobot.robots.unitree_g1.unitree_g1 import UnitreeG1  # noqa: F401
    except ImportError as e:
        return {"name": "lerobot_g1", "status": "skip", "detail": f"not importable here: {e}"}
    return {"name": "lerobot_g1", "status": "pass", "detail": "UnitreeG1 + GrootLocomotionController import OK"}


def main() -> int:
    checks = [
        check_arch(),
        check_mujoco(),
        check_onnxruntime(),
        check_mlx_metal(),
        check_unitree_dds(),
        check_lerobot_g1(),
    ]

    venv_name = Path(sys.prefix).name or "unknown"
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python_executable": sys.executable,
        "venv": venv_name,
        "checks": checks,
    }

    failed = [c for c in checks if c["status"] == "fail"]
    passed = [c for c in checks if c["status"] == "pass"]
    skipped = [c for c in checks if c["status"] == "skip"]

    for c in checks:
        marker = {"pass": "OK", "fail": "FAIL", "skip": "SKIP"}[c["status"]]
        print(f"[{marker}] {c['name']}: {c['detail']}")

    out_dir = REPO_ROOT / "runs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"platform_audit_{venv_name}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\n{len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped (different venv)")
    print(f"report: {out_path}")

    if failed:
        return 1
    if not passed:
        print("WARNING: nothing actually ran in this venv — check you activated the right one")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
