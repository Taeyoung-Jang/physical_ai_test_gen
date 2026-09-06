# 생성 환경에서 G1 내비게이션

이 경로는 **정확한 지도와 로봇 위치를 사용하는 정적 환경 기준선**이다. LLM/VLA, SLAM, 센서 기반 장애물 인식, 동적 장애물 회피는 포함하지 않는다. 기존 stand/locomotion과 구분한 `navigation@1.0` task다.

## 구현 흐름

`world bundle → 검증·로컬 registry 등록 → 요청 revision 확인 → G1 XML 합성 → 지도 경로 단순화 → 근거리 경로 추종 → 기존 CUDA 보행 정책 → 결과·영상`.

`simulation_server.worlds`는 전체 bundle의 hash/size, SceneSpec revision, graph/nav 재계산 결과를 검사한다. 임의 XML 업로드 API는 추가하지 않았다. 등록은 신뢰하는 운영자가 로컬 CLI로 수행한다. 서버 전용 assets 위치로 복사하고 기존 registry를 덮어쓰지 않는다.

실행 geometry는 검증한 SceneSpec에서 생성해 원 G1 XML에 합성한다. 원 지면을 교체하고 robot tree/joint/actuator는 유지한다. 컴파일 후 관절·액추에이터 이름 순서, nq/nv/nu 및 모든 벽/장애물 위치·크기를 확인한다. `world_<object_id>`가 실제 collision geom 이름이다. 로봇/정책의 실제 hash와 요청 revision이 다르면 실행을 거부한다. gains YAML과 종속 mesh hash도 reproduction에 남긴다.

## 실행 예시

`scene2test`에서 기존 서비스와 분리한 검증 서버를 실행한다. 아래 8001은 localhost 전용이며 기존 8000 서버를 변경하지 않는다.

```bash
PYTHONPATH=src MUJOCO_GL=egl SIM_SERVER_ONNX_PROVIDER=cuda .venv/bin/python -c '
from pathlib import Path
from dataclasses import replace
import uvicorn
from simulation_server.config import ServerConfig
from simulation_server.main import create_app
cfg = replace(ServerConfig.from_env(),
    data_root=Path("/workspace/g1_failure/runtime/navigation_server"),
    maximum_episode_duration_s=600,
    worker_startup_grace_s=180)
uvicorn.run(create_app(cfg), host="127.0.0.1", port=8001)
'
```

필요한 경우 `GROOT_WBC_ROOT`와 `GROOT_WBC_PYTHON`을 실제 설치 경로로 지정한다. API key는 기존 `SIM_SERVER_API_KEY` 환경 변수를 사용한다. 외부 공개 시 인증/프록시 설정 없이 bind만 변경하지 않는다.

다른 터미널에서:

```bash
PYTHONPATH=src .venv/bin/python tools/run_navigation_validation.py
```

이 명령은 순차적으로 straight → corner → obstacle → rooms → maze를 생성·등록·HTTP submit/poll한다. 모든 rollout에 video=always를 요청한다. 오류 또는 시간 초과를 성공으로 숨기지 않는다. 실패한 단계도 summary에 남기고 후속 단계를 진행한다. `--stages obstacle`로 한 단계만 실행하거나 `--no-video`로 영상 없는 진단을 할 수 있다.

이 도구는 scene 등록을 위해 Server filesystem에 접근하는 **서버 로컬 통합 검증 클라이언트**다. 임의의 원격 Mac에서 로컬 경로 없이 scene ingestion을 수행하는 도구는 아니다. 등록 후 실행 요청·조회·artifact 다운로드는 HTTP를 사용한다.

기존 생성 bundle을 등록하려면:

```bash
PYTHONPATH=src .venv/bin/python -m simulation_server.worlds /path/to/world/bundle --data-root /workspace/g1_failure/runtime/navigation_server
```

## navigation@1.0 계약

- robot `unitree_g1_locomotion`, profile `29dof`
- controller `groot_locomotion`, policy `groot_walk_policy`
- scene은 등록된 `procedural_world_v1` bundle이어야 한다.
- physics timestep은 0.005s, policy는 native control rate를 사용한다.
- parameters: `speed_mps` [0.05,0.4], `goal_tolerance_m` [0.1,0.35], `stuck_timeout_s` [5,60]. 기본값은 0.3, 0.25, 20.
- 시작/목표는 scene에 고정한다. v1에서는 모든 intervention과 알 수 없는 task parameter를 거부한다. 장면 변경 실험은 새 bundle/revision을 등록해야 한다.
- 최대 episode는 server limit를 따른다. 일반 서버 기본 120s보다 긴 미로는 명시적으로 limit를 높인 인스턴스를 사용한다.
- 검증 도구는 순차 실행한다. 여러 클라이언트 동시 제출에 대한 전역 GPU admission control을 이번 변경으로 구현한 것은 아니다.

## 추종기와 판정

`gt-waypoint-v2`는 4-connected 기준 경로의 시야선 단순화와 0.65m 근거리 lookahead를 사용한다. 회전 오차가 크면 전진을 멈추고 yaw를 조절한다. 최대 yaw command는 0.5rad/s다. 실제 box XY 형상과 circular footprint로 짧은 전진 구간의 clearance를 검사한다. 이는 보수적인 map padding에 갇히는 문제를 줄이기 위한 것으로 전신 동역학 안전 보장은 아니다.

기준선 stage는 명시적인 가정으로 radius=0.4m, margin=0.1m, coarse cell=1.8m를 사용한다. 예전 기본 1.2m 미로가 그대로 검증된 것은 아니다. fixture 세 개는 고정 회귀 장면이고 rooms/maze 두 개는 seed=7 생성 장면이다. seed 하나씩의 성공을 전체 random 환경 성공률로 주장하지 않는다.

종료 원인:
- `GOAL_REACHED`: 허용 거리 내에서 1초 유지, 넘어짐·벽/장애물 접촉 없음.
- `COLLISION`: robot geom과 wall/obstacle geom의 실제 접촉(dist<=0). 지면 접촉 제외.
- `FALL`: base height<0.45m 또는 |roll/pitch|>1rad.
- `STUCK`: 설정 시간 동안 base가 기준 위치에서 0.1m 이상 이동하지 못함.
- `MAX_DURATION`: task 시간 초과. 정상 실행이지만 navigation 실패.
- `NUMERICAL_INSTABILITY`: 무효 실행. 연구상의 정상 실패와 구분.

STUCK의 움직임 기반 판정은 작은 드리프트로 갱신될 수 있다. 따라서 느린 정체가 MAX_DURATION으로 끝날 수도 있다. 둘 다 성공이 아니다. `execution.status=SUCCEEDED`는 worker 완료 상태이며 `task_facts.navigation_success`가 작업 성공 기준이다.

## 산출물과 검증

- run 요청/결과/summary: `/workspace/g1_failure/runtime/navigation_validation/<timestamp>/`
- 서버 실행 evidence: `/workspace/g1_failure/runtime/navigation_server/outputs/jobs/<job_id>/`
- job별 MP4/GIF/thumbnail, 실제·기준 경로 PNG, 20Hz state/action 기록, obstacle contact 기록, SceneSpec/SceneGraph/map/path, 합성 XML, reproduction을 저장한다.
- reproduction에 CUDA provider, 실제 자원 hash, scene revision, navigator/code hash, timestep/seed/설정을 기록한다.
- 합성 XML의 외부 robot mesh는 hash로 참조한다. job 폴더 하나만으로 모든 robot 자산이 복제되었다고 보장하지 않는다.
- HTTP artifact endpoint로 신규 evidence도 내려받을 수 있다.

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/client tests/server tests/test_procedural_world.py -q
```

서버/worker 테스트 외에 실제 GPU 실행 기록은 `.workhistory`의 navigation integration 기록을 확인한다. 다음 연구 단계는 이 기준선을 고정하고 SceneGraph 기반 bounded mutation과 AFS를 연결하는 것이다.

주의: 기존 contact-slip 측정기는 plane 접촉만 취급한다. 이 경로는 box 지면을 사용하므로 저장된 `foot_contact_sample_count=0`의 slip 값은 미측정 placeholder이며 무미끄럼 증거로 사용하지 않는다. 이번 성공 판정은 slip 지표에 의존하지 않는다.
