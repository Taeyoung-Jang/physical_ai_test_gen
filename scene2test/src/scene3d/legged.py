"""legged.py — quadruped/humanoid 등 다리로 서는 로봇의 stance(정적 자립) 실패 탐색.

팔에는 OpenVLA라는 실제 pretrained "가져다 쓰는" 정책이 있었지만, 다리로 서는
로봇에는 그런 범용 오프더셸프 locomotion 정책이 없다(있다면 사용자가 직접 학습시킨
걸 붙이는 시나리오). 그래서 이 모듈은 "훈련된 gait 컨트롤러 통합"이 아니라 팔의
kinematic oracle과 같은 철학 — 실제 URDF를 실제 스캔 씬 바닥에 놓고 실제 물리
시뮬레이션(p.stepSimulation)으로 쓰러지는지/서 있는지만 본다 — 을 다리 로봇에
옮긴 것이다. 컨트롤러가 단순 position-hold라 자주 넘어지더라도 그 자체가 정당한
실패 탐색 결과다.

RobotSpec 하나만 채우면 새 로봇을 추가할 수 있다(joint_types + home_positions만
있으면 됨). spec_from_urdf()로 전용 SPEC이 없는 임의 URDF도 같은 경로로 스탠스
테스트할 수 있다 — "일반 로봇 지원"의 핵심 확장 지점.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pybullet as p


@dataclass
class RobotSpec:
    """다리로 서는 로봇 1종의 로드/제어 스펙.

    home_positions 값의 형식은 joint_types로 결정된다:
    JOINT_REVOLUTE(0)/PRISMATIC(1) → 스칼라 1개를 담은 리스트, JOINT_SPHERICAL(2)
    → 쿼터니언(x,y,z,w) 4개.
    """

    name: str
    urdf_path: str
    spawn_height: float
    home_positions: dict[int, list[float]]
    joint_types: dict[int, int]
    max_force: float = 200.0
    pos_gain: float = 0.5   # JOINT_SPHERICAL(MultiDof) 전용
    vel_gain: float = 1.0   # JOINT_SPHERICAL(MultiDof) 전용
    min_stance_height: float = 0.2   # 이 아래로 떨어지면 FAIL
    max_tilt_deg: float = 30.0       # roll/pitch가 이걸 넘으면 FAIL


# 실측(240 physics step, force=200): 0.45m에서 스폰 → 0.368m로 정착, roll/pitch
# 둘 다 ~0.004 rad(0.23°)까지 안정 — 명확한 PASS 케이스.
LAIKAGO_SPEC = RobotSpec(
    name="laikago",
    urdf_path="laikago/laikago_toes_zup.urdf",
    spawn_height=0.45,
    home_positions={
        0: [0.0], 1: [0.6], 2: [-1.2],
        4: [0.0], 5: [0.6], 6: [-1.2],
        8: [0.0], 9: [0.6], 10: [-1.2],
        12: [0.0], 13: [0.6], 14: [-1.2],
    },
    joint_types={i: p.JOINT_REVOLUTE for i in (0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14)},
    max_force=200.0,
    min_stance_height=0.25,
    max_tilt_deg=25.0,
)

# 실측: 항등 쿼터니언(팔다리 zero pose) + force=400, pos_gain=0.5, vel_gain=1.0이
# 넘어지지 않은 자세 중 가장 나은 결과였다(240 step 기준 roll~0.06, pitch~0.03 rad).
# 다만 이 URDF는 실제 밸런스 컨트롤러(RL/PD) 없이는 장시간(400+ step) 서서히
# 앞으로 기운다 — 팔과 달리 pretrained locomotion 정책이 없다는 이 모듈의 전제 그대로,
# "간단한 제어로는 자주/서서히 넘어짐"이 humanoid의 정당한 기본 결과다.
HUMANOID_SPEC = RobotSpec(
    name="humanoid",
    urdf_path="humanoid/humanoid.urdf",
    spawn_height=1.0,
    home_positions={
        1: [0, 0, 0, 1], 2: [0, 0, 0, 1],       # chest, neck
        3: [0, 0, 0, 1], 6: [0, 0, 0, 1],       # shoulders
        9: [0, 0, 0, 1], 12: [0, 0, 0, 1],      # hips
        11: [0, 0, 0, 1], 14: [0, 0, 0, 1],     # ankles
        4: [0.0], 7: [0.0], 10: [0.0], 13: [0.0],  # elbows, knees
    },
    joint_types={
        1: p.JOINT_SPHERICAL, 2: p.JOINT_SPHERICAL,
        3: p.JOINT_SPHERICAL, 6: p.JOINT_SPHERICAL,
        9: p.JOINT_SPHERICAL, 12: p.JOINT_SPHERICAL,
        11: p.JOINT_SPHERICAL, 14: p.JOINT_SPHERICAL,
        4: p.JOINT_REVOLUTE, 7: p.JOINT_REVOLUTE,
        10: p.JOINT_REVOLUTE, 13: p.JOINT_REVOLUTE,
    },
    max_force=400.0,
    pos_gain=0.5,
    vel_gain=1.0,
    min_stance_height=0.5,
    max_tilt_deg=30.0,
)

BUILTIN_SPECS = {"laikago": LAIKAGO_SPEC, "humanoid": HUMANOID_SPEC}


def spec_from_urdf(
    cid: int,
    urdf_path: str,
    name: str = "custom",
    spawn_height: float = 1.0,
    max_force: float = 300.0,
    min_stance_height: float = 0.2,
    max_tilt_deg: float = 30.0,
) -> RobotSpec:
    """전용 RobotSpec이 없는 임의 URDF에서 스펙을 자동 생성한다.

    모든 비고정 관절의 기본(0 위치 / 항등 쿼터니언) 자세를 home pose로 삼는다 —
    특정 로봇에 대한 사전 지식 없이도 "일단 제자리에서 버티기"를 시도할 수 있는
    최소 공통 분모. 결과가 나쁘면(자주 넘어짐) 그 자체가 유효한 탐색 결과다.
    """
    probe_id = p.loadURDF(urdf_path, basePosition=[0, 0, spawn_height], physicsClientId=cid)
    home_positions: dict[int, list[float]] = {}
    joint_types: dict[int, int] = {}
    for j in range(p.getNumJoints(probe_id, physicsClientId=cid)):
        info = p.getJointInfo(probe_id, j, physicsClientId=cid)
        jtype = info[2]
        if jtype == p.JOINT_FIXED:
            continue
        joint_types[j] = jtype
        home_positions[j] = [0, 0, 0, 1] if jtype == p.JOINT_SPHERICAL else [0.0]
    p.removeBody(probe_id, physicsClientId=cid)
    return RobotSpec(
        name=name, urdf_path=urdf_path, spawn_height=spawn_height,
        home_positions=home_positions, joint_types=joint_types,
        max_force=max_force, min_stance_height=min_stance_height,
        max_tilt_deg=max_tilt_deg,
    )


def load_legged_robot(
    cid: int,
    spec: RobotSpec,
    base_xy: tuple[float, float],
    floor_z: float,
    fixed_base: bool = False,
) -> int:
    base_pos = [base_xy[0], base_xy[1], floor_z + spec.spawn_height]
    return p.loadURDF(
        spec.urdf_path, basePosition=base_pos, useFixedBase=fixed_base,
        physicsClientId=cid,
    )


def hold_home_pose(cid: int, body_id: int, spec: RobotSpec) -> None:
    """모든 관절에 home_positions 목표를 건다.

    JOINT_SPHERICAL은 setJointMotorControlMultiDof(쿼터니언 목표), 나머지는
    setJointMotorControl2(스칼라 목표)를 쓴다 — PyBullet이 관절 자유도별로
    서로 다른 제어 API를 요구하기 때문.
    """
    for j, target in spec.home_positions.items():
        jtype = spec.joint_types.get(j, p.JOINT_REVOLUTE)
        if jtype == p.JOINT_SPHERICAL:
            p.setJointMotorControlMultiDof(
                body_id, j, p.POSITION_CONTROL,
                targetPosition=target, targetVelocity=[0, 0, 0],
                positionGain=spec.pos_gain, velocityGain=spec.vel_gain,
                force=[spec.max_force] * 3, physicsClientId=cid,
            )
        else:
            p.setJointMotorControl2(
                body_id, j, p.POSITION_CONTROL,
                targetPosition=target[0], force=spec.max_force,
                physicsClientId=cid,
            )


@dataclass
class StanceResult:
    verdict: str  # "PASS" | "FAIL"
    min_base_height: float
    max_tilt_deg: float
    fell_at_step: int | None
    base_path: list[list[float]] = field(default_factory=list)


def run_stance_trial(cid: int, body_id: int, spec: RobotSpec, steps: int = 240) -> StanceResult:
    """실제 물리 스텝을 steps회 진행하며 base 높이/기울기를 추적한다.

    spec.min_stance_height 아래로 떨어지거나 spec.max_tilt_deg를 넘는 첫 스텝을
    fell_at_step에 기록한다(있으면 FAIL) — 이후에도 계속 step은 진행해
    base_path/최종 통계는 끝까지 남긴다.
    """
    base_path: list[list[float]] = []
    min_height = float("inf")
    max_tilt = 0.0
    fell_at: int | None = None

    for step in range(steps):
        p.stepSimulation(physicsClientId=cid)
        pos, orn = p.getBasePositionAndOrientation(body_id, physicsClientId=cid)
        euler = p.getEulerFromQuaternion(orn)
        tilt_deg = max(abs(np.degrees(euler[0])), abs(np.degrees(euler[1])))
        base_path.append(list(pos))
        min_height = min(min_height, pos[2])
        max_tilt = max(max_tilt, tilt_deg)
        if fell_at is None and (pos[2] < spec.min_stance_height or tilt_deg > spec.max_tilt_deg):
            fell_at = step

    return StanceResult(
        verdict="FAIL" if fell_at is not None else "PASS",
        min_base_height=min_height,
        max_tilt_deg=max_tilt,
        fell_at_step=fell_at,
        base_path=base_path,
    )
