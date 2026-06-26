# Scene2Test

**3D Scene Graph 기반 Active Failure Search를 활용한 Physical AI 행동 회귀 테스트 자동화 시스템**

> 제조·물류 로봇 자동화 환경에서 3D Vision으로 작업공간을 구조화하고, Active Failure Search를 통해
> 실패 가능성이 높은 장면 조건을 능동적으로 탐색하여 로봇 행동의 성공·실패·위험 요인을 자동 검증하는 시스템.

---

## 한눈에 보기

로봇 pick-and-place 작업이 **실제 현장에서 실패하기 전에**, 어떤 환경 조건(장애물 배치, 작업자 접근, 목적지 점유, 카메라 가림 등)에서 실패하는지를 AI가 능동적으로 찾아냅니다.

- 단순히 장면을 랜덤하게 흔드는 것이 **아님**
- LLM에게 테스트 케이스를 만들어 달라고 하는 것도 **아님**
- 핵심은 **시뮬레이션 피드백으로 학습한 surrogate 모델이, 실패 가능성이 높은 다음 테스트 장면을 능동적으로 제안**하는 Active Failure Search 엔진

자세한 과제 배경·설계 의도는 [`.blueprint/00_blueprint.md`](.blueprint/00_blueprint.md) 참조.

---

## 파이프라인

```
3D Scene (시뮬레이션 / RGB-D)
        ↓
3D Scene Graph 생성            scene_graph.py / scene_generator.py / vision/
        ↓
Mutation Space 정의 (8개 변수)  mutation_space.py
        ↓
┌──────────────────────────────────────────────┐
│  Active Failure Search Engine                 │  active_failure_search.py
│   ├─ 초기 시드 샘플링 (LHS + boundary seeds)    │  mutation_space.py
│   ├─ Surrogate Model (Random Forest / GP)     │  surrogate_model.py
│   ├─ Acquisition Function                     │  acquisition.py
│   └─ 시뮬레이션 피드백 루프                       │
└──────────────────────────────────────────────┘
        ↓
Kinematic Simulation Runner    sim_runner.py
        ↓
Physical Oracle (6종 판정)      physical_oracle.py
        ↓
실패 조건 / 경계 조건 리포트     reporter.py / app.py
```

---

## 핵심 개념

### 8개 장면 변형 변수 (Mutation Space)
| 변수 | 범위 | 의미 |
|---|---|---|
| `target_dx`, `target_dy` | ±0.10 m | 목표물 위치 이동 |
| `obstacle_angle` | 0–360° | 장애물 배치 각도 |
| `obstacle_dist_to_target` | 0.02–0.20 m | 장애물–목표물 거리 |
| `human_zone_x`, `human_zone_y` | 작업공간 내 | 작업자 위험 영역 위치 |
| `tray_occupied` | 0/1 | 목적지 점유 여부 |
| `occlusion_ratio` | 0.0–0.60 | 목표물 가림 비율 |

하나의 변수 벡터 = 하나의 테스트 장면.

### 6개 Robustness Margin → 4개 판정
오라클은 각 테스트에서 6개 margin을 계산하고, **가장 낮은 margin이 최종 robustness와 실패 유형(failure_type)을 결정**합니다.

```
reach      = max_reach − robot_to_target_distance
clearance  = target_clearance − required_gripper_clearance
collision  = path_min_obstacle_distance − collision_threshold
safety     = path_to_human_distance − safety_distance
goal       = destination_clearance − place_margin
perception = perception_confidence − confidence_threshold

robustness = min(위 6개)
```

| 판정 | 조건 |
|---|---|
| **PASS** | robustness > warn_band |
| **WARN** | 0 < robustness ≤ warn_band (경계 조건) |
| **FAIL** | robustness ≤ 0 |
| **BLOCKED** | safety margin < 0 (사람 안전, 최우선 차단) |

> AI 모델(Surrogate)의 목적과 사용 방식은 아래 **"AI 모델: 무엇을 학습하고, 어떻게 쓰는가"** 섹션에서 자세히 설명합니다.

### Kinematic Oracle (중요)
판정은 **순수 기하 쿼리**(IK 도달성, 경로–장애물 거리, 경로–사람 거리, occlusion 비율)로 이루어지며,
**물리 동역학 grasp을 시뮬레이션하지 않습니다.** 그래서:
- 연속적인 부호 있는 margin(예: -1.58cm)을 얻어 surrogate 학습/탐색에 유리
- 완전 결정론적이고 가벼워 수천 케이스 탐색 가능
- 단, 전복·미끄러짐 같은 동적 실패는 잡지 못함 → 시각화 도구에 `--physics` 옵션으로 별도 관찰 제공

---

## AI 모델: 무엇을 학습하고, 어떻게 쓰는가

이 시스템의 핵심 AI는 **Surrogate Model(대리 모델)** 입니다. PASS/FAIL을 단순 분류하는 모델이 **아니라**,
**"다음에 어떤 장면을 테스트해야 실패를 가장 빨리 찾을지"를 제안**하기 위한 모델입니다.

### 왜 필요한가 — 목적
PyBullet 시뮬레이션은 한 번 돌리는 데 비용이 듭니다. 매 라운드 후보 **1,000개**를 전부 실행하는 건 낭비입니다.
그래서:

> 일부 실행 결과로 모델을 학습 → 나머지 후보들의 **실패 가능성을 예측** → 실패할 것 같은 상위 K개만 실제 실행

이렇게 하면 **시뮬레이션 예산을 절감**하면서 **실패 발견 효율을 극대화**합니다. (목표: 전수 대비 70%↓ 실행, Random 대비 +30% 실패 발견)

### 무엇을 학습하나 — 입력/출력
`src/surrogate_model.py`

| | 내용 |
|---|---|
| **입력 X** | 16차원 feature 벡터 (장면 그래프 + mutation에서 `feature_extractor.py`가 추출) |
| **출력 Y** | 6개 robustness margin `[reach, clearance, collision, safety, goal, perception]` |
| **모델** | `RFSurrogate`(기본): ExtraTrees 앙상블, margin마다 별도 회귀기 6개 / `GPSurrogate`: Gaussian Process(비교군) |

즉 모델이 근사하는 함수는:
```
f(장면 feature, mutation 파라미터) → 6개 margin (각각 평균 + 표준편차)
```

여기서 두 가지 핵심 산출이 나옵니다:
- **robustness 예측** = `min(6개 margin 평균)` — 실패에 가장 가까운 margin(binding margin)
- **불확실성** = 앙상블 트리 간 예측 분산(또는 GP 분산) — 모델이 아직 잘 모르는 영역일수록 큼
- **실패 확률** `P(robustness < 0)` = 가우시안 근사 `norm.cdf(0, 평균, 표준편차)`

### 어떻게 다음 테스트를 고르나 — Acquisition Function
`src/acquisition.py`. 후보 1,000개 각각에 대해 모델 예측 + 규칙을 결합한 점수를 매깁니다.

```
A(z) =  0.35 · P(실패)          ← 모델: 실패 가능성 높은 곳 (exploit)
      + 0.25 · 불확실성          ← 모델: 아직 모르는 곳 (explore)
      + 0.20 · 안전 중요도        ← 규칙: human_zone 포함 여부
      + 0.15 · novelty           ← 기존 테스트와의 거리 (다양성)
      − 0.05 · redundancy        ← 기존과 너무 가까우면 페널티
      + coverage_bonus           ← 아직 못 찾은 실패 유형 유도 (예: occlusion↑, tray 점유)
```

`exploit`(실패 가능성)과 `explore`(불확실성)를 동시에 고려하는 것이 **Bayesian Optimization 계열의 능동 탐색** 구조입니다.
점수 상위 K개를 다양성까지 고려해(`select_topk_diverse`) 선택합니다.

### 탐색 루프 (능동 학습)
```
초기 시드 실행 → 오라클이 margin 라벨 생성 → RF 재학습
   → 1,000개 후보의 실패확률·불확실성 예측 → Acquisition 점수화
   → 상위 K개 선택 → 시뮬레이션 실행 → 라벨 추가 → (반복)
```
모델은 **자기가 만든 라벨로 부트스트랩**하며 라운드를 거칠수록 실패 영역을 더 잘 조준합니다.

### Cold-Start: 처음엔 모델을 쓰지 않습니다
사전 학습 데이터가 없으므로 **오라클 자체가 데이터 생성기**입니다.

1. **초기 단계 (데이터 < `min_train_size`=15)** — Surrogate 미사용.
   Latin Hypercube Sampling(공간 고르게 덮기) + Boundary Seeds(일부러 실패 직전 조건으로 밀기)로 시드 선택.
2. **오라클이 채점** → `(feature → 6 margin)` 라벨을 즉석 생성.
3. **데이터 15개 이상 누적 시** 비로소 RF가 학습되고 위 Acquisition이 동작.

> ⚠️ 총 테스트가 15개 미만이면 모델이 학습조차 안 되고 boundary seed 휴리스틱만 동작합니다.
> 모델 효과를 보려면 `--rounds 5 --tests-per-round 20`처럼 충분히 크게 실행하세요.
> (`acquisition_score`가 0이 아닌 케이스가 모델이 선택한 테스트입니다.)

### LLM은 핵심이 아닙니다
LLM은 테스트 케이스 생성·판정에 **사용하지 않습니다**(물리 유효성 보장 어려움). 핵심 AI는 위 Surrogate + Acquisition이며,
LLM은 결과 리포트 문장화 등 보조 용도로만 선택적으로 쓸 수 있습니다.

---

## 설치

> **환경:** macOS(Apple Silicon 포함), Python 3.11, [uv](https://docs.astral.sh/uv/)

```bash
cd scene2test
uv sync
```

### Apple Silicon 주의사항
- 공식 `pybullet`은 Apple Silicon에서 컴파일 실패 → **`pybullet-arm64`** (prebuilt wheel) 사용. `pyproject.toml`에 반영됨.
- 애니메이션 GIF/영상 기능은 Homebrew `ffmpeg` 필요: `brew install ffmpeg`
- PyBullet **GUI 창은 macOS(Metal)에서 정상 렌더링되지 않음**(보라색 화면). 시각화는 헤드리스 스냅샷/GIF로 제공.

---

## 빠른 시작

모든 명령은 `scene2test/` 디렉터리에서 실행.

### 1. 씬 라이브러리 생성
```bash
uv run python src/scene_generator.py --n 20 --output-dir data/scene_library --seed 0
```

### 2. Active Failure Search 실행
```bash
# 단일 씬, cold 모드
uv run python src/active_failure_search.py \
    --scene data/scene_library/scene_00001.json \
    --mode cold --rounds 5 --tests-per-round 20

# Random vs Active 비교 실험
uv run python src/active_failure_search.py \
    --scene data/scene_library/scene_00001.json \
    --mode compare --rounds 5 --tests-per-round 20
```
결과 로그는 `data/search_logs/*.json`에 저장됨.

**주요 옵션:** `--mode {cold|warm|random|compare}`, `--rounds`, `--tests-per-round`,
`--surrogate {rf|gp}`, `--seed`

### 3. 대시보드
```bash
uv run streamlit run app.py   # http://localhost:8501
```

---

## 시각화 도구 (`tools/`)

### 씬 스냅샷
```bash
# 4-뷰(front/top/side/perspective) PNG 스냅샷
uv run python tools/view_scene.py --snapshot --scene data/scene_library/scene_00001.json
```

### 실패/성공 케이스 애니메이션 GIF
로봇의 전체 pick-and-place 동작(Home → Pre-grasp → Grasp → Lift → Place → Home)을 GIF로 재생.
출력: `data/failure_anim/*.gif`

```bash
# 검색 로그의 특정 FAIL 케이스
uv run python tools/animate_failure.py \
    --log data/search_logs/<로그파일>.json --test-index 0

# 모든 FAIL 케이스
uv run python tools/animate_failure.py \
    --log data/search_logs/<로그파일>.json --verdict FAIL --max 8

# 성공(PASS) 참조 케이스 — 원본 씬, mutation 없음
uv run python tools/animate_failure.py --pass-scene scene_00001

# 물리 동역학 모드: 모터 제어 + 충돌 응답 (팔이 장애물을 실제로 밀어냄)
uv run python tools/animate_failure.py \
    --log data/search_logs/<로그파일>.json --test-index 0 --physics
```

| 모드 | 동작 | 용도 |
|---|---|---|
| 기본 (kinematic) | teleport, 잡은 블록은 표시용으로 그리퍼에 부착 | 판정 로직과 동일한 기하 기반 |
| `--physics` | `setJointMotorControl2` 구동 + 충돌 응답 | 전복·밀림 등 물리적 결과 관찰 |

---

## v2: LAM-Guided Failure Case Generator

기본 파이프라인이 "장면을 바꿔 실패를 찾는다"였다면, v2 확장은 **"LAM/정책이 실제로 어떻게 행동하는지 관찰 → 그 정책이 취약한 3D failure case를 생성 → 재실행"** 하는 행동 조건부(behavior-conditioned) 루프를 추가합니다. 기존 파이프라인은 손대지 않으며 `enabled` flag로 on/off 합니다. (설계: `.blueprint/01_blueprint.md`)

```
정책(ActionModel) 실행 관찰 → RolloutTrace
   → 행동 취약성 추정 (VulnerabilityProfiler)
   → 약점 family의 3D failure case 생성 (FailureCaseGenerator + GeneratedAssetBank)
   → ConstraintFilter → 재실행 → Policy/Physical Oracle → FailureMemory
   → BoundaryRefiner로 최소 perturbation 경계 탐색
```

### 핵심 차별점
- **객체 선택 정책**: `MiniActionModel`(휴리스틱, 딥러닝 아님)은 색/형상/instruction 키워드 + 근접도로 객체를 채점 → 유사한 distractor가 들어오면 **wrong object grounding**이 발생. `RuleLAMProxy`는 항상 정답(baseline).
- **두 개의 오라클**: 기존 Physical Oracle(충돌/clearance) + 신규 **Policy Oracle**(wrong_object_grounding, wrong_object_picked, safety_noncompliance, action_instability, recovery_failure).
- **4개 failure family**: semantic_distractor, occluder, path_blocker, human_safety_intrusion.
- **Kinematic 기반**: `run_kinematic_check(target_pos=…)`가 좌표를 받으므로, 정책이 고른 객체로 뻗는 데 sim 수정이 필요 없음. 새 객체는 `ObjectNode`로 삽입(기존 spawner 재사용, URDF 없음).

### 실행
```bash
# 정상 정책 baseline (Demo 1) — wrong grounding 없음
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json --action-model rule --rounds 4 --enabled

# 헷갈리는 정책으로 guided 생성 (Demo 2~4)
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json --action-model mini --rounds 4 --enabled
```
산출물: `data/lam_guided_logs/*.json`, `reports/{vulnerability_summary.md, counterexample_table.csv, boundary_report.md}`.

### counterexample 시각화 (GIF)
발견한 counterexample을 로봇 애니메이션 GIF로 렌더링합니다. wrong-grounding 케이스는
**TARGET(초록 링, 테이블에 남음)** vs **PICKED(빨강 링, 그리퍼가 들어올림)** 마커로 "엉뚱한 객체를 집었음"을 명시합니다.
```bash
# 최신 LAM 로그의 family별 counterexample → GIF (data/lam_anim/)
PYBULLET_MODE=DIRECT uv run python tools/animate_lam_failure.py --max 4
# 특정 family / failure type만
PYBULLET_MODE=DIRECT uv run python tools/animate_lam_failure.py --family semantic_distractor
```
TinyRenderer로 캡처(macOS GUI/OpenGL 문제 회피), 저장 전 프레임이 실제로 다른지 검증.

### 핵심 결과 (같은 기계, 정책마다 다른 취약성)
| 정책 | wrong_object_grounding | semantic_distractor 경계 |
|---|---|---|
| `rule` (정답) | 없음 | ~0.04m (최소 = 취약점 없음) |
| `mini` (헷갈림) | 발견 | **~0.14m** (14cm 내 유사 distractor면 grounding 불안정) |

검증: `PYBULLET_MODE=DIRECT uv run python tests/test_p11_lam_guided.py` (unit 7 + Demo 1~4).

### 실제 VLA(OpenVLA) 통합 — closed-loop 정책
테스트 대상 정책은 교체 가능하다. `MiniActionModel`(휴리스틱)을 넘어 **실제 OpenVLA**를
붙이려면 closed-loop 경로를 쓴다: 매 스텝 [RGB 렌더 → `act()` → 7-DoF EE 델타 → IK → step].
- `src/policies_vla.py` — `ClosedLoopPolicy`(reset/act), `StubReachPolicy`(GPU-free 검증용), `OpenVLAPolicy`(GPU)
- `src/lam_guided/closed_loop.py` — `render_rgb`, `run_closed_loop_rollout`, `infer_selected_object`
- 산출 `RolloutTrace`가 동일 스키마라 PolicyOracle/Physical 체크 불변 → OpenVLA는 **drop-in**

```bash
# stub 정책으로 closed-loop 데모 (별도 설치 불필요) — VLA 관측 GIF 포함
PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
    --scene data/scene_library/scene_00001.json --policy stub --insert distractor_red_can --gif

# 실제 OpenVLA: 의존성 설치 후 device=auto (Apple Silicon이면 자동 MPS)
uv sync --extra vla
PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
    --scene data/scene_library/scene_00001.json --policy openvla --unnorm-key bridge_orig
```
`OpenVLAPolicy`는 device를 자동 감지(Apple Silicon `mps`+fp16 / CUDA `cuda`+bf16 / `cpu`)하고
flash-attn은 쓰지 않는다. 검증: `tests/test_p12_vla_closed_loop.py`.
설치·성능 현실(M4 Pro)·embodiment 보정·Octo 대안은 [`docs/openvla_integration.md`](scene2test/docs/openvla_integration.md).

### 3D Object Generation (Shap-E) — 없으면 default 폴백
distractor/occluder를 **텍스트→3D 생성 메쉬**로 만들어 asset bank에 등록한다.
**생성 모델이 없거나 실패하면 procedural default 객체로 자동 폴백**한다.
- `src/lam_guided/asset_gen.py` — `ShapEGenerator`(diffusers, Apple Silicon은 CPU 자동), `acquire_asset`(실패→default)
- `src/scene_builder.py` — `create_mesh` + `_spawn_object` 메쉬 분기(GEOM_MESH 시각 + box collision proxy)
- 생성은 **offline 1회**(느림), 루프는 등록된 메쉬를 consume (블루프린트 14장 2단계)

```bash
uv sync --extra gen3d        # diffusers, trimesh (transformers 4.40.1 호환 버전 고정)
# 실제 생성 (M4 Pro CPU ~30s) — index.json 등록 + 스냅샷
PYBULLET_MODE=DIRECT uv run python tools/gen3d_asset.py \
    --prompt "a red soda can" --asset-id gen3d_red_can --family semantic_distractor --steps 24
# 모델 없이 폴백 확인
PYBULLET_MODE=DIRECT uv run python tools/gen3d_asset.py --no-model
```
이 M4 Pro에서 Shap-E 실제 생성 동작 확인(can 형상 메쉬). 검증: `tests/test_p13_asset_gen.py`.
상세는 [`docs/3d_generation.md`](scene2test/docs/3d_generation.md).

---

## 디렉터리 구조

```
physical_ai_test_gen/
├── README.md               ← 이 파일
├── .blueprint/             설계 보고서 (과제 배경/설계 의도)
└── scene2test/
    ├── app.py              Streamlit 대시보드 (4-패널)
    ├── pyproject.toml      의존성 (pybullet-arm64, Python 3.11)
    ├── config/
    │   ├── robot_config.yaml    Franka Panda 설정 (관절/그리퍼/reach)
    │   ├── thresholds.yaml      오라클 임계값 (6 margin 기준)
    │   ├── task_config.yaml
    │   ├── scene_gen_config.yaml
    │   └── lam_guided_failure.yaml  [v2] LAM-guided 루프 flag + knob
    ├── src/
    │   ├── scene_graph.py           SceneGraph 자료구조
    │   ├── scene_builder.py         PyBullet 씬 로드 + mutation 적용
    │   ├── scene_generator.py       절차적 씬 생성 [CLI]
    │   ├── scene_library.py         라이브러리 관리
    │   ├── mutation_space.py        8-변수 공간 + LHS/boundary/random 샘플링
    │   ├── validity.py              물리 유효성 제약
    │   ├── feature_extractor.py     특징 벡터 추출
    │   ├── sim_runner.py            Kinematic check (IK + 거리/충돌 쿼리)
    │   ├── physical_oracle.py       6종 오라클 + robustness + 판정
    │   ├── surrogate_model.py       RFSurrogate / GPSurrogate
    │   ├── acquisition.py           Acquisition Function
    │   ├── active_failure_search.py 메인 탐색 루프 [CLI]
    │   ├── reporter.py              리포트 생성 (+v2 LAM 리포트 3종)
    │   ├── vision/rgbd_to_graph.py  RGB-D → Scene Graph (Track B)
    │   ├── policies.py              [v2] ActionModel (RuleLAMProxy, MiniActionModel)
    │   ├── policies_vla.py          [v2] ClosedLoopPolicy (StubReachPolicy, OpenVLAPolicy)
    │   └── lam_guided/              [v2] LAM-guided failure 루프 패키지
    │       ├── types.py             RolloutTrace/BehaviorFeatures/VulnerabilityProfile/...
    │       ├── asset_bank.py        GeneratedAssetBank + 씬 시맨틱 주석
    │       ├── case_apply.py        새 객체(asset) 삽입
    │       ├── rollout.py           선택 객체 kinematic rollout
    │       ├── policy_oracle.py     Policy Oracle + 물리 체크
    │       ├── behavior_encoder.py  RolloutTrace → BehaviorFeatures
    │       ├── vulnerability.py     취약성 프로파일링
    │       ├── case_generator.py    4 family failure case 생성
    │       ├── constraint_filter.py 삽입 유효성 (validity 재사용)
    │       ├── failure_memory.py    counterexample 저장 + novelty/redundancy
    │       ├── boundary_refiner.py  최소 perturbation 경계 (binary search)
    │       ├── closed_loop.py       [v2] VLA closed-loop rollout (RGB→act→IK)
    │       ├── asset_gen.py         [v2] 3D 생성(Shap-E)+default 폴백
    │       └── lam_guided_loop.py   오케스트레이터 [CLI]
    ├── tools/
    │   ├── view_scene.py            씬 스냅샷/뷰어
    │   ├── animate_failure.py       pick-and-place 애니메이션 (kinematic/physics)
    │   ├── animate_lam_failure.py   [v2] LAM counterexample GIF (TARGET/PICKED 마커)
    │   ├── run_vla_rollout.py       [v2] closed-loop VLA rollout 데모 (stub/openvla)
    │   └── gen3d_asset.py           [v2] 3D object 생성 데모 (+default 폴백)
    ├── tests/                       phase별 검증 (test_p1 ~ test_p10, +test_p11 LAM-guided)
    └── data/
        ├── scene_library/          생성된 씬 JSON
        ├── search_logs/            탐색 결과 로그
        ├── failure_anim/           실패/성공 케이스 GIF
        ├── generated_assets/       [v2] procedural asset index.json
        └── lam_guided_logs/        [v2] LAM-guided 루프 로그 + counterexamples
```

---

## 평가 지표 (목표)

| 지표 | 목표 |
|---|---|
| Failure Discovery Rate@K | Random 대비 +30% 이상 |
| Unique Failure Mode Coverage | 5종 중 4종 이상 (collision, clearance, unreachable, destination_occupied, human_risk, perception) |
| Simulation Budget Reduction | 전수 실행 대비 70% 이상 절감 |
| Safety Block Rate | human risk 조건 BLOCKED 90% 이상 |
| Report Generation Rate | 실행 테스트 100% 자동 리포트 |

비교 실험은 `--mode compare`로 Random Search vs Active Failure Search의 실패 발견 수를 직접 대조합니다.

---

## 테스트

phase별 검증 스크립트로 각 단계를 개별 실행합니다.

```bash
uv run python tests/test_p5_physical_oracle.py     # 오라클 판정
uv run python tests/test_p6_active_failure_search.py  # 탐색 루프
uv run python tests/test_p9_comparison.py          # Random vs Active 비교
# ... test_p1 ~ test_p10
```

---

## 구현 범위

**하는 것:** 시뮬레이션/RGB-D 기반 Scene Graph 생성, 8-변수 mutation 공간, robustness 기반 6종 오라클,
Active Failure Search(Surrogate + Acquisition), PyBullet kinematic 검증, 실패/경계 조건 리포트.

**하지 않는 것:** 실제 로봇 하드웨어 제어, VLA/VLM 정책 학습, 포토리얼 3D inpainting,
LLM 기반 테스트 케이스 직접 생성, 복잡한 grasp planning.
