# Simulation Execution Server 구현 현황과 확장 설계

이 문서는 `.blueprint/SERVER_ARCHITECTURE.md`를 기준으로 구현한 첫 번째 Server vertical
slice의 범위, 실행 방법, Client 연동 계약, GR00T backend 구조와 향후 3D scene 확장 방향을
정리한다.

## 1. 목적과 책임 경계

Server는 failure를 탐색하거나 최종 failure label을 결정하지 않는다. 연구 방법론은
`failure_client`에 남겨 두고 Server는 다음만 담당한다.

1. revision이 고정된 scene, robot, controller, policy와 task를 해석한다.
2. generic intervention을 검증하고 실행 상태에 적용한다.
3. 독립 subprocess에서 MuJoCo rollout을 실행한다.
4. state, action, contact와 표준 event 같은 raw evidence를 기록한다.
5. 동일 실험을 재현할 수 있는 runtime 및 resource provenance를 반환한다.

```text
Mac Failure Client
  → FastAPI rollout request
  → resource revision 및 intervention 검증
  → SQLite job 생성/idempotency 처리
  → 독립 worker subprocess
  → GR00T 43-DoF G1 MJCF + MuJoCo
  → state/action/contact 기록
  → standard event + reproduction manifest
  → Client가 자체 failure evaluator 실행
```

## 2. 코드 구조

```text
src/simulation_server/
├── main.py       # FastAPI endpoint, 인증 및 authoritative validation
├── config.py     # 환경 변수와 runtime 경로
├── bootstrap.py  # 로컬 GR00T resource의 초기 registry 등록
├── registry.py   # immutable manifest registry 및 snapshot
├── jobs.py       # SQLite job/idempotency, subprocess, timeout/cancel
├── worker.py     # 실제 bounded MuJoCo rollout과 evidence 기록
├── groot_locomotion.py # GPU ONNX balance/walk controller
└── cli.py        # simulation-server 실행 명령
```

실제 robot asset은 인접한 `GR00T-WholeBodyControl` 저장소의
`decoupled_wbc/control/robot_model/model_data/g1/scene_43dof.xml`을 사용한다. Server는
MJCF 내용을 SHA-256으로 계산하여 revision에 사용하며 원본 GR00T 파일을 수정하지 않는다.

## 3. 현재 구현된 범위

### API와 control plane

- `GET /api/v1/health`
- `GET /api/v1/capabilities`
- `GET /api/v1/registry/snapshot`
- `GET /api/v1/scenes/{scene_id}/snapshot`
- `POST /api/v1/scenes/{scene_id}/queries`
- `POST /api/v1/rollouts`
- `GET /api/v1/rollouts/{job_id}`
- `GET /api/v1/rollouts/{job_id}/result`
- `POST /api/v1/rollouts/{job_id}/cancel`
- `GET /api/v1/artifacts/{artifact_id}`

Bearer token, canonical request hash, idempotency conflict, normalized error envelope, timeout,
cancellation과 Server 재시작 시 unfinished job의 `INTERRUPTED` 전환을 지원한다.

### 현재 등록되는 runtime resource

| Resource | ID | Revision |
|---|---|---|
| Scene | `g1_ground` | GR00T MJCF SHA-256 |
| Robot | `unitree_g1`, profile `43dof` | GR00T MJCF SHA-256 |
| Controller | `mock_standing` | `builtin:pd-standing-v1` |
| Policy | `hold_pose` | `builtin:hold-pose-v1` |
| Task | `stand@1.0` | `schema:stand@1.0` |
| Scene/Robot | `g1_locomotion_ground` / `unitree_g1_locomotion` (`29dof`) | native WBC MJCF SHA-256 |
| Controller/Policy | `groot_balance` / `groot_balance_policy` | Balance ONNX SHA-256 |
| Controller/Policy | `groot_locomotion` / `groot_walk_policy` | Walk ONNX SHA-256 |
| Task | `locomotion@1.0` | `schema:locomotion@1.0` |

`mock_standing`은 호환성 확인용 deterministic PD controller이며 장시간 안정 자세 기준선이 아니다.
실제 standing/walking에는 GR00T-WBC 저장소의 Balance/Walk ONNX 정책을 사용한다. 기본 provider는
`CUDAExecutionProvider`이며 CUDA 초기화 실패 시 조용히 CPU로 폴백하지 않고 작업을 실패시킨다.

### 현재 지원 intervention

현재 authoritative하게 검증하고 적용하는 intervention은 `set_robot_spawn`,
`set_friction`, `apply_external_force`다.

```json
{
  "operation_id": "set_robot_spawn",
  "kind": "robot_initial_state",
  "operation_version": "1.0",
  "parameters": {
    "position_m": [0.0, 0.0, 0.8],
    "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]
  }
}
```

위치와 quaternion의 길이, finite number 여부 및 quaternion의 nonzero norm을 검사한다.
마찰계수는 [0, 2], 외력은 각 성분 ±1000 N 범위로 검증한다. 외력은 대상 body,
시작 시간과 양의 duration을 지정하며 실제 적용값은 reproduction manifest에 기록된다.

### 생성되는 evidence

```text
/workspace/g1_failure/runtime/server/outputs/jobs/<job_id>/
├── request.json
├── execution_result.json
├── state_trajectory.jsonl
├── action_trajectory.jsonl
├── contacts.jsonl
├── reproduction.json
└── worker.log
```

- state: simulation time, `qpos`, `qvel`
- action: simulation time, MuJoCo `ctrl`
- contact: geom pair와 contact position
- task fact: standing 여부와 최종 base height
- standard event: `BASE_HEIGHT_THRESHOLD_CROSSED`
- reproduction: resource revision, seed, timestep, Python/MuJoCo version과 backend 경로

Infrastructure/worker failure는 `execution.valid=false`, `status=FAILED`로 기록되어 robot의
task failure와 구분된다.

## 4. 실행 방법

설치, Server 기동, Client 환경 변수, API 점검, end-to-end smoke protocol, artifact 확인,
자동 테스트와 troubleshooting은 [Client / Server 실행 및 테스트 가이드](CLIENT_SERVER_RUNBOOK.md)를
참고한다. 아래는 Server를 시작하는 최소 명령이다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv sync --extra server

export SIM_SERVER_DATA_ROOT=/workspace/g1_failure/runtime/server
export GROOT_WBC_ROOT=/workspace/g1_failure/src/GR00T-WholeBodyControl
export SIM_SERVER_API_KEY=replace-me

uv run simulation-server
```

영상 요청(`video: always` 또는 event가 발생한 `on_standard_event`)은 Linux에서 EGL
headless rendering을 사용한다. 기본 profile은 640x480, 20 FPS이며 `SIM_SERVER_RENDER_WIDTH`,
`SIM_SERVER_RENDER_HEIGHT`, `SIM_SERVER_RENDER_FPS`로 변경한다. Server는 전체 `rollout.mp4`,
최대 120-frame `rollout.gif` preview, `thumbnail.png`를 artifact로 등록한다.

기본 worker는 API와 같은 Python environment를 사용한다. 별도 interpreter가 필요하면
`GROOT_WBC_PYTHON`을 설정할 수 있지만, 해당 환경에는 이 프로젝트와 `mujoco`, `numpy`,
`pyyaml`이 모두 설치되어 있어야 한다.

테스트용 `probe` backend는 simulation을 실행하지 않으며 항상 `execution.valid=false`를
반환하므로 실제 evidence로 사용하면 안 된다.

## 5. 현재 Client가 실행할 수 있는 failure candidate

현재는 G1의 초기 위치나 자세가 standing stability에 미치는 영향만 실험할 수 있다.

```text
Client가 위험할 것으로 예상한 spawn pose 생성
→ set_robot_spawn intervention 제출
→ Server가 실제 G1 MuJoCo rollout 실행
→ base height, contacts, joint trajectory 반환
→ Client가 자체 failure definition으로 판정
```

`locomotion@1.0`은 전진·횡방향 속도와 yaw rate 명령을 실행하고 standing 및 이동 거리를 반환한다.
장애물, 마찰, 외력, sensor noise intervention은 아직 실행할 수 없으므로 일반적인
failure-seeking simulation platform의 완성본으로 표현해서는 안 된다.

## 6. 가상 물체 배치 확장 설계

다음 milestone에서 `add_primitive`와 `add_mesh` generic intervention을 추가한다.

```json
{
  "operation_id": "add_primitive",
  "kind": "scene",
  "operation_version": "1.0",
  "parameters": {
    "object_id": "obstacle_001",
    "shape": "box",
    "size_m": [0.4, 0.2, 0.6],
    "pose": {
      "position_m": [1.2, 0.1, 0.3],
      "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0]
    },
    "physics": {
      "mass_kg": 5.0,
      "friction": [0.8, 0.01, 0.001]
    }
  }
}
```

원본 scene을 수정하지 않고 derived MJCF를 생성하고 다음 cache key를 사용한다.

```text
sha256(
  scene_revision
  + robot_revision
  + canonical_precompile_interventions
  + compiler_version
)
```

필수 validation:

- 허용 shape 및 mesh format
- 좌표, quaternion, 크기, mass와 friction의 numeric range
- 중복 `object_id`
- initial robot collision envelope와의 overlap
- path traversal 및 외부 파일 접근 차단
- derived MJCF compile 가능 여부

## 7. Point cloud 기반 실제 3D scene 확장 설계

Point cloud 자체는 점 사이의 surface topology가 없어 MuJoCo collision geometry로 직접
사용하기에 적합하지 않다. 원본 관측 자산으로 보존하면서 visual mesh와 단순 collision
mesh를 별도로 생성해야 한다.

```text
PLY/PCD/RGB-D/GLB 입력
→ 보안, 좌표계, 단위와 scale 검사
→ outlier 제거 및 floor/plane 추출
→ surface reconstruction
→ detailed visual mesh 생성
→ low-poly/convex collision geometry 생성
→ semantic object/region annotation
→ spawn point와 camera 정의
→ GR00T G1 MJCF와 world asset 합성
→ MuJoCo compile validation
→ standing smoke rollout
→ immutable READY revision 등록
```

권장 scene package:

```text
scene_package/
├── manifest.yaml
├── source/
│   ├── scan.ply
│   └── reconstructed.glb
├── visual/
│   └── scene.glb
├── collision/
│   ├── floor.obj
│   ├── walls.obj
│   └── furniture_lowpoly.obj
├── semantics/
│   ├── objects.json
│   ├── regions.json
│   └── relations.json
├── cameras/
│   └── cameras.yaml
└── spawn_points.yaml
```

| Asset | 용도 |
|---|---|
| 원본 point cloud | provenance, offline 분석과 재처리 |
| Visual mesh | camera/offscreen rendering |
| Collision mesh | physics/contact 계산 |
| Semantic metadata | Client world model과 failure reasoning |
| Occupancy/navmesh | clearance/path/traversability query |

고밀도 reconstructed mesh를 collision mesh로 그대로 사용하면 compile과 contact 계산 비용이
커진다. 바닥과 벽은 가능하면 plane/box로 근사하고 복잡한 물체는 low-poly 또는 convex
decomposition을 사용한다.

```text
GR00T G1 robot MJCF
+ imported visual/collision scene
+ semantic/camera/spawn metadata
+ Client generic interventions
→ content-addressed derived model
→ isolated MuJoCo rollout
```

## 8. 다음 구현 우선순위

1. `add_primitive`, `set_friction`, `set_joint_state`
2. scheduled `apply_external_force`
3. derived MJCF compiler와 content-addressed cache
4. OBJ/GLB scene package ingestion 및 validation CLI
5. visual/collision asset 분리와 point-cloud preprocessing
6. object pose/AABB/clearance/raycast query
7. `navigate_to_pose@1.0`과 목표 기반 locomotion
8. 별도 policy trace와 추가 learned controller adapter
9. 다중 offscreen camera/video artifact
10. worker crash recovery와 100-rollout soak test

## 9. 검증 현황

- Ruff 검사 통과
- Server 및 기존 Client 계약 테스트 14개 통과
- 실제 GR00T `scene_43dof.xml`을 사용한 0.02초 MuJoCo smoke rollout 통과
- smoke 결과: 4 simulation steps, 최종 base height 약 `0.791 m`, contact sample 8개
- state/action/contact/reproduction artifact 생성 확인

위 smoke test는 실행 경로의 유효성을 확인한 것이며 장시간 standing 안정성, learned WBC,
실제 point-cloud scene의 안정성을 입증하지 않는다. 별도 5초 GPU 보행 E2E에서는
최저 base height `0.737 m`, 전진 거리 `1.173 m`, CUDA provider 및 MP4/GIF 생성을 확인했다.
