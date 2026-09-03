# Failure Client / Simulation Server 실행 및 테스트 가이드

현재 구현된 Simulation Server와 Failure Client를 실행하고 연결, rollout, artifact 및 자동
테스트를 검증하는 절차다. 모든 명령은 별도 표시가 없으면 `scene2test/`에서 실행한다.

현재 server vertical slice의 실제 지원 범위는 다음과 같다.

- task: `stand@1.0`, `locomotion@1.0`
- scene: `g1_ground`, `g1_locomotion_ground`
- robot: `unitree_g1` (`43dof`), `unitree_g1_locomotion` (`29dof`)
- controller/policy: legacy `mock_standing` / `hold_pose`, learned `groot_balance` / `groot_balance_policy`, learned `groot_locomotion` / `groot_walk_policy`
- intervention: `set_robot_spawn`
- backend: 실제 `groot_mujoco` 또는 연결 점검용 `probe`

`config/failure_client_example.yaml`의 obstacle/navigation 예제는 향후 기능을 설명하는 설계
예제이며 현재 server에서는 실행되지 않는다. 현재 end-to-end 검증에는
`config/failure_client_server_smoke.yaml`을 사용한다. 실제 안정 보행 검증에는
`config/failure_client_locomotion_smoke.yaml`을 사용한다.

## 1. 설치

Python 3.11 이상과 `uv`가 필요하다. 실제 rollout에는 인접한
`GR00T-WholeBodyControl` 저장소가 필요하다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv sync --extra server
uv run failure-client --help
```

`simulation-server`는 현재 별도 CLI 옵션 없이 환경 변수로 설정한다. uvicorn 옵션은
`uv run uvicorn --help`로 확인한다.

## 2. Server 실행

### 실제 GR00T MuJoCo backend

Server 터미널에서 실행한다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
export SIM_SERVER_DATA_ROOT=/workspace/g1_failure/runtime/server
export GROOT_WBC_ROOT=/workspace/g1_failure/src/GR00T-WholeBodyControl
export SIM_SERVER_API_KEY=replace-with-a-long-random-token
export SIM_SERVER_BACKEND=groot_mujoco
uv run simulation-server
```

기본 주소는 `0.0.0.0:8000`이다. port나 log level을 바꾸려면 직접 실행한다.

```bash
uv run uvicorn simulation_server.main:create_app \
  --factory --host 0.0.0.0 --port 8001 --log-level debug
```

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SIM_SERVER_DATA_ROOT` | `/workspace/g1_failure/runtime/server` | registry, SQLite, job output 위치 |
| `GROOT_WBC_ROOT` | workspace의 GR00T 경로 | GR00T 저장소 root |
| `GROOT_WBC_PYTHON` | 현재 Python | worker subprocess interpreter |
| `SIM_SERVER_API_KEY` | 없음 | 설정 시 Bearer 인증 활성화 |
| `SIM_SERVER_BACKEND` | `groot_mujoco` | `groot_mujoco` 또는 `probe` |
| `SIM_SERVER_ONNX_PROVIDER` | `cuda` | learned balance/walk ONNX 실행 provider (`cuda` 또는 `cpu`) |
| `SIM_SERVER_WORKER_STARTUP_GRACE_S` | `120` | 모델 초기화·렌더링을 위한 worker 제한시간 여유 |
| `SIM_SERVER_RENDER_WIDTH` | `640` | offscreen 영상 너비 |
| `SIM_SERVER_RENDER_HEIGHT` | `480` | offscreen 영상 높이 |
| `SIM_SERVER_RENDER_FPS` | `20` | MP4/GIF 렌더링 FPS |

외부에 노출하는 Server에는 API key와 TLS를 사용한다. secret은 protocol이나 Git에 넣지 않는다.

### API 전용 probe backend

GR00T/MuJoCo 없이 API, idempotency, artifact 전달만 확인할 때 사용한다.

```bash
export SIM_SERVER_DATA_ROOT=/tmp/scene2test-probe-runtime
export GROOT_WBC_ROOT=/workspace/g1_failure/src/GR00T-WholeBodyControl
export SIM_SERVER_API_KEY=local-smoke-token
export SIM_SERVER_BACKEND=probe
uv run simulation-server
```

`probe`는 의도적으로 `execution.valid=false`와 `PROBE_BACKEND_NO_SIMULATION`을 반환한다.
물리 실험 성공 결과로 해석하면 안 된다.

## 3. Server 단독 점검

다른 터미널에서 실행한다.

```bash
export SERVER_URL=http://127.0.0.1:8000
export SERVER_TOKEN=replace-with-a-long-random-token
curl --fail --silent --show-error "$SERVER_URL/api/v1/health"
curl --fail --silent --show-error \
  -H "Authorization: Bearer $SERVER_TOKEN" \
  "$SERVER_URL/api/v1/capabilities"
curl --fail --silent --show-error \
  -H "Authorization: Bearer $SERVER_TOKEN" \
  "$SERVER_URL/api/v1/registry/snapshot"
```

health의 `status`는 `ok`여야 한다. `groot_root_available=false`이면 `GROOT_WBC_ROOT`를
확인한다. OpenAPI UI는 `http://127.0.0.1:8000/docs`에서 볼 수 있다.

## 4. Client 설정과 연결 점검

Client 터미널에서 실행한다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
export FAILURE_CLIENT_SERVER_URL=http://127.0.0.1:8000
export FAILURE_CLIENT_TOKEN=replace-with-a-long-random-token
export FAILURE_CLIENT_WORKSPACE=/workspace/g1_failure/runtime/client
export FAILURE_CLIENT_TIMEOUT_S=30
export FAILURE_CLIENT_MAX_ATTEMPTS=3
uv run failure-client health
uv run failure-client registry-sync
uv run failure-client method-list
```

Server에 API key가 없으면 Client token도 설정하지 않는다. 서로 다른 머신이면 Server의
공개 URL, VPN 주소 또는 SSH tunnel 주소를 사용한다.

- `health`: URL과 Server process 확인
- `registry-sync`: capabilities와 immutable revision을 SQLite에 동기화
- `method-list`: 설치된 failure discovery method 확인

Client 출력 구조:

```text
$FAILURE_CLIENT_WORKSPACE/
├── client.sqlite
├── artifacts/
└── experiments/<experiment_id>/
    ├── protocol.lock.yaml
    └── exports/
```

## 5. End-to-end smoke rollout

### registry revision 반영

GR00T MJCF 내용에 따라 revision이 달라지므로 registry 응답에서 `g1_ground` scene과
`unitree_g1` robot revision을 확인한다.

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer $FAILURE_CLIENT_TOKEN" \
  "$FAILURE_CLIENT_SERVER_URL/api/v1/registry/snapshot"
cp config/failure_client_server_smoke.yaml /tmp/failure_client_server_smoke.yaml
```

복사한 YAML의 두 `REPLACE_WITH_REGISTRY_REVISION`을 registry 값으로 바꾼다. 현재 scene과
robot은 같은 MJCF SHA-256을 사용하지만 항상 registry를 source of truth로 삼는다.

### 검증, 실행, 재개

```bash
uv run failure-client validate /tmp/failure_client_server_smoke.yaml
uv run failure-client run /tmp/failure_client_server_smoke.yaml --poll-interval 0.2
```

Client가 중간에 종료되었으면 동일 protocol로 재개한다.

```bash
uv run failure-client resume /tmp/failure_client_server_smoke.yaml --poll-interval 0.2
```

`experiment_id`는 workspace에서 유일해야 한다. 새 실험은 ID를 바꾸고, 중단된 동일 실험만
`resume`한다. 동일 ID에 `run`을 반복하지 않는다. `groot_mujoco`에서는 experiment가
`COMPLETED`되고 rollout/evaluation 수가 각각 1 이상이어야 한다. `probe`에서는 통신이
성공해도 evaluation이 `INDETERMINATE`인 것이 정상이다.

### 결과와 artifact

```bash
# Client 머신
find "$FAILURE_CLIENT_WORKSPACE/experiments" -maxdepth 4 -type f -print
find "$FAILURE_CLIENT_WORKSPACE/artifacts" -maxdepth 2 -type f -print

# Server 머신
find "$SIM_SERVER_DATA_ROOT/outputs/jobs" -maxdepth 2 -type f -print
```

실제 rollout job에는 `request.json`, `execution_result.json`, state/action/contact JSONL,
`reproduction.json`, `worker.log`가 생성된다. `artifacts.video: always`이면 `rollout.mp4`, `rollout.gif`, `thumbnail.png`도 생성되고 Client artifact store로 내려받는다. `on_standard_event`이면 standard event가 발생한 rollout에만 영상 파일을 보존한다. 확정 failure를 export한다.

```bash
uv run failure-client export exp_g1_stand_smoke_001
```

failure가 없다면 명령은 성공해도 failure case 수는 0일 수 있다.

## 6. 기존 결과 재평가

raw rollout을 다시 실행하지 않고 새 definition으로 append-only 재평가할 수 있다.

```yaml
# /tmp/standing_definition_v2.yaml
schema_version: "1.0"
definition_id: "g1_standing_failure"
definition_version: "2.0"
failure_events:
  - rule_id: "base_too_low"
    event_type: "BASE_HEIGHT_THRESHOLD_CROSSED"
success_predicates:
  - rule_id: "standing_at_end"
    source: "task_facts"
    path: "standing_at_end"
    operator: "truthy"
```

```bash
uv run failure-client reevaluate \
  exp_g1_stand_smoke_001 /tmp/standing_definition_v2.yaml
```

## 7. 자동 테스트

빠른 Client/Server smoke suite:

```bash
PYBULLET_MODE=DIRECT uv run pytest tests/server -q
uv run ruff check src/simulation_server tests/server
PYBULLET_MODE=DIRECT uv run pytest tests/client -q
uv run ruff check src/failure_client tests/client
```

Server suite는 health/registry, idempotency, probe artifact와 revision 오류를 검사한다. Client
suite는 계약, gateway retry/checksum, resume, method, 평가/archive, orchestration과
100-rollout fake-gateway acceptance를 검사한다.

전체 pytest 회귀:

```bash
PYBULLET_MODE=DIRECT uv run pytest tests/ -v
```

P1-P21 일부는 pytest가 수집하지 않는 `main()` script다. 전체 phase 검증 시 해당 파일을
직접 실행한다. scene3d 테스트는 `--extra scene3d`가 필요할 수 있고 integration script는
artifact를 생성할 수 있다.

자동 server 테스트는 빠른 `probe`를 사용한다. 실제 MuJoCo smoke는 별도로 확인한다.

1. health의 backend가 `groot_mujoco`이다.
2. experiment가 `COMPLETED`된다.
3. `execution.valid=true`, status가 `SUCCEEDED`이다.
4. state/action/contact/reproduction artifact가 생성된다.
5. reproduction에 revision, seed, timestep, Python/MuJoCo version이 있다.

짧은 smoke 성공은 장시간 안정성이나 learned controller 성능을 입증하지 않는다.

## 8. 원격 연결

```bash
ssh -N -L 8000:127.0.0.1:8000 user@server-host
```

Client는 `FAILURE_CLIENT_SERVER_URL=http://127.0.0.1:8000`을 사용한다. RunPod proxy나 HTTPS
reverse proxy 사용 시 해당 HTTPS URL을 지정한다.

## 9. 문제 해결

| 증상 | 원인 및 조치 |
|---|---|
| `FAILURE_CLIENT_SERVER_URL is required` | Client URL 환경 변수 설정 |
| HTTP 401 | Client token과 Server API key 확인 |
| connection refused/timeout | process, URL/port, 방화벽, tunnel 확인 |
| `groot_root_available: false` | GR00T 경로 확인 |
| `RESOURCE_REVISION_NOT_FOUND` | registry 재동기화 후 YAML revision 갱신 |
| `ROBOT_PROFILE_NOT_FOUND` | profile을 `43dof`로 설정 |
| `TASK_NOT_SUPPORTED` | 현재 `stand@1.0`만 지원 |
| `INTERVENTION_CAPABILITY_MISSING` | 현재 `set_robot_spawn`만 지원 |
| `IDEMPOTENCY_CONFLICT` | 같은 key에 다른 request를 제출했는지 확인 |
| `PROBE_BACKEND_NO_SIMULATION` | 실제 검증에는 `groot_mujoco` 사용 |
| experiment ID exists | 새 ID 또는 중단 실험에 `resume` 사용 |
| worker failure/timeout | job의 `worker.log`, result, interpreter 의존성 확인 |

문제 보고 시 secret을 제외하고 다음 정보를 기록한다.

```bash
uv --version
uv run python --version
uv run python -c "import fastapi, httpx, mujoco; print(fastapi.__version__, httpx.__version__, mujoco.__version__)"
git rev-parse HEAD
```

Server는 `Ctrl-C`로 종료한다. runtime과 Client workspace에는 재현 및 resume 정보가 있으므로
필요한 artifact와 SQLite backup을 확인하기 전에 삭제하지 않는다.
