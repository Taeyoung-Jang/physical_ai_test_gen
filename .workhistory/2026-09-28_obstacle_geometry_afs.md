# 2026-09-28 — 다중 장애물 goal-agent AFS 확장

## 사용자 요청과 작업 범위

AFS/Random 비교가 끝날 때까지 개발을 멈추지 않고 다음 단계로 진행하라는 요청.
다음 단계 중 실제 goal-agent가 실행 가능한 환경의 기하 확장을 선택했다.
기존 단일 상자 5축 통로에 고정 장애물 2개를 추가하고, AFS가 그 위치·크기·높이·회전을
변경할 수 있게 했다. 로봇 기술 개발, 유료 재실험, 기존 캠페인 재분류는 하지 않았다.
시작 시 Git 작업 트리는 깨끗했다. 이번 작업에서는 commit/push하지 않았다.

## 구현

1. `clear_path/contracts.py`: `ObstacleFixture`, opt-in `clear-path-obstacles-v3`.
   기존 physics 3축 + corridor 2축 + 고정 블록별 6축 = 17개의 연속 파라미터.
   블록마다 X, 좌우 fraction, 로컬 가로/세로, 높이, yaw. 범위/finite/extra-field 검증.
   기존 동적 상자 크기와 X, 시작점, 목표, planner footprint/clearance는 바꾸지 않는다.
2. `clear_path/obstacles.py`: 하나의 함수에서 월드 중심, 로컬 크기, 회전 행렬/쿼터니언,
   월드 AABB를 파생. X 범위를 분리해 초기 상자와 출발/도착점 중첩을 방지한다.
   회전 AABB를 사용한 Y 배치로 전체 범위에서 벽 간격 5 cm 확보.
3. `fixture.py`: 동일한 기하를 XML, SceneGraph, 지도, revision에 반영한다.
   새 geom은 static이며 joint/actuator를 추가하지 않는다. SceneGraph size는 AABB,
   extra에 local_size/rotation/yaw를 보존한다. 접촉은 diagnostic-only다.
4. `goal_runner.py`: 세계 geometry 목록에 새 장애물을 포함한다. 실제 MuJoCo geometry가
   로봇 VLM 관측·내부 계획기·접촉 기록에 전달된다. 카메라도 물리 장면을 그대로 렌더한다.
   로봇 prompt·planner·action executor·goal evaluator를 바꾸지 않았으며 AFS 가설/정답 경로를
   로봇에 전달하지 않는다. 접촉 뒤 회복해 목표에 도달하는 경우 PASS 의미를 보존했다.
5. `scene_space.py`, `research_protocol.py`, `llm_afs/behavior.py`: 17축 독립 균등 Random,
   새로운 domain ID, AFS 출력 axis 계약과 설명을 연결했다. 기존 request builder의
   current-domain axis enum, evidence-ID enum, context-hash binding을 그대로 사용한다.
   낮은 장애물이 점프 기능을 의미하지 않는다는 점과 폭/크기/회전에 따른 Y coupling을 명시했다.
6. `research_campaign.py`: v3도 결과를 유효 횟수에 반영하기 전 config/XML 일치를 검사한다.
   `regression_cases.py`: 검증된 v3 장면 노드 정규화 및 domain별 축 범위로 bracket 정규화.
   로봇/solver의 잔여 XML 차이는 여전히 비교를 막는다. 단일 축 반대 결과만 관측 경계를 만든다.
7. `preview_corridor_scenes.py --preset obstacles`: API/로봇 실행 없는 4개 개발용 장면,
   회전 직사각형과 높이를 표시한 PNG, HTML, config/SceneGraph/map/XML/manifest.
   실제 G1 자산 CPU 검사 옵션을 재사용했다. GIF/MP4를 생성하지 않는다.
8. `config/behavior_afs_obstacles_luna.json`: Luna/Luna, 6+6 유효/최대 시도, 초기 각 2회,
   최대 로봇120호출 + AFS2호출. 기본 시뮬레이션 상한 없음, 오류 중단/추가비용 방지 유지.
   설정은 준비했지만 live 실행하지 않았다.

OpenAI Docs 스킬을 사용해 공식 Structured Outputs 문서를 검색 후 열람했다.
새 API 통합이나 모델 교체가 아니라 기존 strict 구조화 출력의 도메인 enum을 확장했다.
https://developers.openai.com/api/docs/guides/structured-outputs

## 검증

첫 통로/장면/runner/캠페인 선택 테스트: **114 passed, 52.17초**.
이후 새 고정 물체의 접촉이 FAIL을 강제하지 않는 검사 및 v3 campaign geometry 검사를 추가했다.

```bash
.venv/bin/python -m pytest tests/client tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_corridor_scene.py tests/test_goal_outcome_runner.py -q
```

**390 passed, 137.30초**. 범위:

- 24개 seed의 MuJoCo 형상/회전/SceneGraph 크기·ID/지도/실제 내부 계획 경로 일치.
- 최소/최대 폭, −90/−45/0/45/90도, 좌우/중앙 배치의 최대 크기 충돌·벽 여유 검사.
- 17축 각각 범위 밖/NaN/Inf/숨은 goal·footprint 변경 거부, fixed count 검증.
- 낮은/높은 블록은 물리/revision이 달라지지만 2D blocked 지도는 동일함을 명시적으로 검사.
- 실제 runner + CPU MuJoCo + 제어기/정책 대역으로 새 geometry 관측 및 접촉 이벤트 연결.
  contact 후 goal 도달 PASS는 대역이 만든 입력으로, G1 능력 증명이 아니다.
- 합성 17축 캠페인 12회, 끊김 없이/중간 재개 결과 일치, Luna 전달, paired cold start,
  exploration/repeat 슬롯, 요청 schema enum, history 및 보고서 생성.
- 회전/높이/X의 단일 축 PASS/FAIL bracket과 midpoint, solver 차이가 있으면 bracket 제외.
- 위치/크기/회전/마찰 XML 변조 거부; 잘못된 scene geometry의 유효 FAIL 집계 제외.
- 기존 근거-ID 복구, 측정기, API/예산·goal semantics 및 옛 3/5축 회귀 유지.

외부 실물 자산 파일 기반 **CPU 조립 검사**를 네 장면 모두 수행:
29 actuators, robot_joint_identity_preserved=true, gait_observation_equal=true,
gpu_policy_executed=false. 물리 step/모델 추론/로봇 rollout은 0회다.
정적 경로는 앞의 3개 장면에서 있고, blocked 장면에서는 없다. goal outcome은 모두 NOT_EXECUTED.

`git show HEAD:.../fixture.py`의 변경 전 함수를 메모리에서 실행해 기존 Fixture,
기본 CorridorFixture 및 폭1.6/오프셋1 조건의 identity/XML/graph/map과 비교했다.
**모두 동일**했다. 단, 소스 fingerprint가 달라진 것은 별개이며 기존 frozen campaign을
새 코드로 재개할 수 있다고 주장하지 않는다.

Ruff 및 `git diff --check`를 적용했다. 테스트 결과는 합성/CPU 검증이며 유료 API 호출 0회,
GPU 정책 실행 0회, 새로운 실제 성공률/AFS Gain/6유형 coverage 수치는 없다.

## 미리보기 산출물

최종:

`/workspace/g1_failure/runtime/obstacle_previews/20260928T140821_430973Z/report.html`

- `scene_000`: slalom. 정적 reference Y는 −0.125..0.125 m로 앞/중앙/뒤 장애물 사이에서 변한다.
- `scene_001`: 45도/−30도 회전, 높이1.2/0.4m.
- `scene_002`: 높이0.1/0.15m. planner는 낮은 물체도 보수적으로 피한다.
- `scene_003`: 폭1.6m + 회전 최대 크기, 정적 경로 없음.
- 26개 manifest artifact의 SHA-256을 확인했다.
- PNG를 직접 열어 회전 표기, 고정/가동 물체 구분, reference/실제 궤적 구분을 검토했다.

초기 미리보기 `20260928T140446_655524Z`도 보존했다. 이때 slalom 예제의 장애물이
너무 벽 가까이에 있어 중앙 직선 경로가 남았다. 개발 fixture의 좌우 fraction만 바꿔
실제 방향 전환이 필요한 배치로 보완했다. 수정 후 preview CLI 테스트 **1 passed, 15.34초**,
네 장면 CPU 자산 검사와 최종 manifest를 다시 확인했다. 과거 산출물을 덮어쓰지 않았다.
AFS 자동 생성이나 로봇에게 지정된 경유점을 넣은 것은 아니다.

## 실행 안내와 한계

README 및 `scene2test/docs/OBSTACLE_AFS.md`에 무료 preview/plan과 유료 single-run/campaign
명령을 분리해 저장했다. 단순 command 복사로 기존 recovery 캠페인을 바꾸지 않게 안내한다.

- 새 domain ID: `d45c8b222698d445450b6d82968113efdcf0c3808e4afa1e34c85ec0664323b0`.
- 6+6 설정은 작은 연결 검사이며 17차원 통계적 성능 비교의 충분한 표본 수가 아니다.
- orientation의 대칭/주기 때문에 다른 parameter 값이 같은 형상을 만들 수 있다.
  파라미터 novelty를 물리적 다양성 또는 실패 family coverage로 해석하지 않는다.
- 높이별 stepping/jumping, dynamic 다중 물체 조작, 임의 미로/여러 방/terrain goal-agent
  적재는 하지 않았다. 기존 standalone 생성기의 지원과 이번 실행 backend를 구분한다.
- 추가 블록은 고정되어 있어 새 push 대상으로 삼을 수 없다. 기존 상자만 movable이다.
- static no_path는 예산 조건 로봇 FAIL이나 조작까지 고려한 불가능성의 증거가 아니다.
- 과거 고정 캠페인은 원래 코드 환경에서만 재개한다. 이전 evidence와 비용은 그대로 보존했다.
- 다음 독립 개발 단계는 근거 기반 유형 측정과 저장 사례의 실행형 회귀 runner다.
