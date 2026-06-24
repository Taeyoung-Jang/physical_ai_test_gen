# Scene2Test 구현 계획서

> **마지막 업데이트**: 2026-06-22  
> **현재 완료**: P0~P10 (전체 완료)

---

## 프로젝트 개요

**과제명**: 3D Scene Graph 기반 Active Failure Search를 활용한 Physical AI 행동 회귀 테스트 자동화 시스템  
**약칭**: Scene2Test

**핵심 목표**: 제조·물류 로봇 자동화 환경에서 Physical AI가 실제 환경에서 실패하기 전에, 3D Scene Graph 기반 Active Failure Search를 통해 실패 조건을 자동으로 찾아내는 테스트 자동화 시스템.

---

## 확정된 설계 결정 사항

| 결정 항목 | 확정 내용 | 근거 |
|---|---|---|
| Scene 생성 방식 | Track A(절차적) 먼저 → Track B(RGB-D) 단계적 추가 | 안정성 우선, 3D Vision 시연은 후반부 |
| Sim 충실도 | **Kinematic oracle** (IK + 경로 보간 + 거리/충돌 쿼리) | 동역학 grasp는 MVP 범위 밖, robustness 6 margin은 기하학적 계산으로 충분 |
| 탐색 운용 | **Scene 라이브러리 + cross-scene 전이 surrogate** | AI 일반화 서사 강화, Failure Discovery Rate 정량 비교 가능 |
| Surrogate 모델 우선순위 | **RandomForest/ExtraTrees 1차**, GP는 비교군 | 혼합형 변수(이진 + 연속) 처리에 RF 유리 |
| robustness 함수 | **multi-output per margin** (개별 예측 후 min) | min(...)의 비평활 문제 해소 + failure_type 자동 도출 |
| 유효성 검사 | **numpy 해석적 AABB 체크** (PyBullet 미사용) | 1,000개 후보 필터 < 1초 목표 |
| 판정 우선순위 | BLOCKED(human_safety) > FAIL > WARN > PASS | 안전 우선, WARN은 warn_band(0.015m) 이내 |

---

## 전체 파이프라인

```
[Track A: 절차적 생성]     [Track B: RGB-D 인식]
  scene_generator.py    →  vision/rgbd_to_graph.py
         ↓                         ↓
         └─────── SceneGraph (공통 스키마) ───────┘
                          ↓
                  [scene_builder.py]  ← PyBullet 로드
                          ↓
                  [feature_extractor.py]  ← 물리 피처 8종
                          ↓
                  [mutation_space.py + validity.py]  ← 후보 1,000개 (numpy)
                          ↓
              [active_failure_search.py]
               ├─ Initial: LHS + boundary seeds
               ├─ surrogate_model.py (RF multi-output / GP 비교)
               ├─ acquisition.py (실패P + 불확실성 + 안전 + novelty)
               └─ 라운드별 top-K 선택 → PyBullet 실행
                          ↓
                  [sim_runner.py]  ← kinematic oracle (IK + 경로 샘플)
                          ↓
                  [physical_oracle.py]  ← 6종 Oracle → robustness + 판정
                          ↓
                  [reporter.py]  ← 결과표 + 실패 원인 + 개선 권고
                          ↓
                  [app.py]  ← Streamlit 4-패널 대시보드
```

---

## Phase별 상세 계획

### ✅ P0. 프로젝트 스캐폴딩 + SceneGraph 스키마 계약 (완료)

**완료된 파일:**
- `pyproject.toml` — uv 기반 빌드 설정, hatchling, ruff
- `.python-version` — Python 3.12 고정
- `.venv/` — uv로 생성한 가상환경
- `.env` — PYBULLET_MODE, SEED, LOG_LEVEL
- `.gitignore`
- `requirements.txt`
- `config/task_config.yaml` — 작업 정의 (pick_and_place)
- `config/robot_config.yaml` — Franka Panda, max_reach 0.855m, gripper 0.08m
- `config/thresholds.yaml` — Oracle 임계값 전체
- `config/scene_gen_config.yaml` — 절차적 scene 생성 파라미터
- `src/scene_graph.py` — SceneGraph 스키마 (SupportSurface, ObjectNode, Relation, UnknownRegion) + round-trip 직렬화

**완료 기준 달성**: `SceneGraph round-trip OK: desk_scene_001`

---

### ✅ P1. PyBullet 기본 환경 + Kinematic Sim Primitives (완료)

**목표 파일**: `src/scene_builder.py`, `src/sim_runner.py`

**scene_builder.py 구현 내용:**
```
- PyBullet 연결 (DIRECT/GUI 모드 .env 기반 전환)
- 평면 + 테이블 생성
- Franka Panda URDF 로드 (pybullet_data 사용)
- create_box(pos, size, color, mass) → body_id
- create_cylinder(pos, radius, height, color, mass) → body_id
- create_tray(pos, size) → body_id
- create_human_zone(pos, radius) → body_id (visual-only, no collision)
- load_scene_graph(sg: SceneGraph) → body_id_map
- reset_scene(sg: SceneGraph, mutation_params: dict) → body_id_map
```

**sim_runner.py 구현 내용 (Kinematic Oracle):**
```
- get_ee_pose(body_id) → (pos, orn)
- solve_ik(target_pos, target_orn) → joint_angles | None
- interpolate_joint_path(q_start, q_end, n_samples) → List[q]
- check_path_collisions(path: List[q], body_ids) → (min_dist, colliding_bodies)
- get_closest_points(body_a, body_b) → min_distance_m
- capture_frame() → np.ndarray (DIRECT 모드 TinyRenderer)
```

**완료 기준**: Franka Panda URDF 로드 + IK 성공 + 경로 보간 + 충돌 거리 쿼리 동작

---

### ✅ P2. 절차적 Scene 생성기 (Track A) + numpy 유효성 필터 (완료)

**목표 파일**: `src/scene_generator.py`, `src/validity.py`

**scene_generator.py 구현 내용:**
```
- generate_scene(seed: int, config: dict) → SceneGraph
  - workspace: table bounds 랜덤 샘플
  - target: 도달 가능 내부 영역에 배치 (reach_fraction 범위)
  - obstacles: count_range 내 랜덤 수, target 주변 min_gap 보장
  - destination: table 반대쪽 영역에 배치
  - human_zone: presence_prob로 삽입, min_dist_to_path 보장
  - 생성된 scene은 nominal PASS 보장 (validity.is_valid_base_scene)

- generate_library(n: int, output_dir: str) → List[SceneGraph]
  - library_size=20개 생성 → data/scene_library/ 저장
```

**validity.py 구현 내용 (numpy만 사용, PyBullet 미사용):**
```
- aabb_overlap(center_a, size_a, center_b, size_b) → bool
- point_in_bounds(point, bounds) → bool
- is_valid_base_scene(sg: SceneGraph, robot_cfg: dict) → bool
  - target이 reach annulus 내에 있는지
  - 객체 간 overlap 없는지
  - destination 식별 가능한지
- is_valid_mutation(base_sg: SceneGraph, params: dict, ...) → bool
  - mutation 후 table bounds 이탈 없는지
  - 객체 간 비현실적 overlap 없는지
```

**완료 기준**: `generate_library(20)` 실행 시 20개 SceneGraph JSON이 `data/scene_library/`에 저장되고, 모두 `is_valid_base_scene` 통과

---

### ✅ P3. Feature Extractor — scene_features + mutation 결합 벡터 (완료)

**목표 파일**: `src/feature_extractor.py`

**추출 피처 8종:**

| 피처 이름 | 계산 방법 |
|---|---|
| `target_robot_distance` | `‖target.pos - robot.base‖` |
| `target_to_nearest_obstacle` | min obstacle까지 거리 |
| `path_min_clearance` | robot→target 직선 경로 주변 최소 장애물 거리 |
| `reach_margin` | `max_reach - target_robot_distance` |
| `obstacle_on_path` | 경로와 obstacle AABB 교차 (0/1) |
| `destination_occupied` | tray region 내 obstacle 존재 (0/1) |
| `human_zone_min_distance` | 경로 ↔ human_zone 최소 거리 |
| `unknown_region_overlap` | occlusion region과 경로 겹침 비율 |

**출력**: `np.ndarray shape=(N_features+N_mutation_params,)` — surrogate 입력 벡터

**완료 기준**: SceneGraph → 8종 피처 벡터 출력, mutation 파라미터와 concat 후 surrogate 입력 형태 확인

---

### ✅ P4. Mutation Space Builder + 샘플러 (완료)

**목표 파일**: `src/mutation_space.py`

**변형 파라미터 공간 (8차원):**
```python
MUTATION_PARAMS = {
    "target_dx":               (-0.10, 0.10),
    "target_dy":               (-0.10, 0.10),
    "obstacle_angle":          (0, 360),
    "obstacle_dist_to_target": (0.02, 0.20),
    "human_zone_x":            (0.25, 0.75),
    "human_zone_y":            (-0.35, 0.35),
    "tray_occupied":           (0, 1),     # 이진 → round()
    "occlusion_ratio":         (0.0, 0.6),
}
```

**샘플러 3종:**
```
- sample_random(sg, n=1000) → List[dict]  # 균일 랜덤
- sample_latin_hypercube(sg, n=100) → List[dict]  # 초기 seed용 LHS
- sample_boundary_seeds(sg) → List[dict]  # reach 최대, clearance 최소 등 경계 근처
```

**필터**: `validity.is_valid_mutation`으로 유효 후보만 반환 (numpy AABB, < 1초)

**완료 기준**: 1개 SceneGraph → 1,000개 이상 유효 후보 1초 이내 샘플링

---

### ✅ P5. Physical Oracle — 6종 + robustness + 판정 (완료)

**목표 파일**: `src/physical_oracle.py`

**6종 Oracle:**

| Oracle | 판정 로직 | failure_type |
|---|---|---|
| ReachabilityOracle | IK 성공 여부 + `max_reach - dist` > 0 | `unreachable` |
| CollisionOracle | 경로 waypoint별 `getClosestPoints` → min_dist > threshold | `path_collision` |
| ClearanceOracle | target 주변 최소 거리 vs `gripper_width/2 + margin` | `insufficient_clearance` |
| HumanSafetyOracle | 경로 ↔ human_zone 최소 거리 vs `safety_distance` | `human_risk` (→ BLOCKED) |
| DestinationOracle | tray region AABB 여유 vs object footprint | `destination_occupied` |
| PerceptionOracle | `occlusion_ratio > threshold` 또는 unknown overlap | `perception_uncertainty` |

**robustness 계산:**
```python
margins = {
    "reach":       max_reach - dist,
    "clearance":   actual_clearance - required_clearance,
    "collision":   min_path_dist - collision_threshold,
    "safety":      min_human_dist - safety_distance,
    "goal":        tray_free_area - object_footprint,
    "perception":  confidence - confidence_threshold,
}
robustness = min(margins.values())
failure_type = min(margins, key=margins.get)  # binding margin
```

**판정 우선순위:**
```
margins["safety"] < 0       → BLOCKED
robustness <= 0              → FAIL  (failure_type = binding margin)
0 < robustness <= warn_band  → WARN  (경계 조건)
robustness > warn_band       → PASS
```

**출력 형태:**
```json
{
  "test_id": "T04",
  "result": "FAIL",
  "failure_type": "insufficient_clearance",
  "robustness": -0.019,
  "margins": {"reach": 0.13, "clearance": -0.019, ...},
  "reason": "target 주변 최소 여유 4.1cm < 요구 clearance 6.0cm",
  "recommendation": "장애물을 target에서 최소 6cm 이상 이동"
}
```

**완료 기준**: 6종 Oracle 각각 동작 + robustness + 판정값 자동 산출

---

### ✅ P6. Active Failure Search Engine (단일 scene) (완료)

**목표 파일**: `src/surrogate_model.py`, `src/acquisition.py`, `src/active_failure_search.py`

**surrogate_model.py:**
```
- MultiOutputSurrogate: 각 margin을 개별 출력으로 예측
  - fit(X, Y)  where Y.shape = (N, 6)
  - predict(X) → (mean: np.ndarray, std: np.ndarray)  각 (N, 6)
- RFSurrogate(MultiOutputSurrogate): ExtraTreesRegressor 앙상블
  - 불확실성 = 트리 간 예측 분산
- GPSurrogate(MultiOutputSurrogate): GaussianProcessRegressor per margin
  - Matern(nu=2.5) 커널 + noise
```

**acquisition.py:**
```python
def acquisition_score(z, surrogate, dataset, sg):
    mean, std = surrogate.predict(features(z))
    prob_fail = norm.cdf(0, loc=mean.min(), scale=std[mean.argmin()])

    return (
        0.35 * prob_fail              # 실패 가능성
      + 0.25 * std.mean()            # 예측 불확실성
      + 0.20 * safety_priority(z)   # human_zone 근접
      + 0.15 * novelty_score(z, dataset)  # 기존 테스트와 거리
      - 0.05 * redundancy_score(z, dataset)
    )
```

**active_failure_search.py (탐색 루프):**
```python
for round_idx in range(num_rounds=5):
    pool = sample_valid_mutations(sg, n=1000)

    if len(dataset) < min_train_size(=15):
        selected = lhs_seeds + boundary_seeds  # k=10
    else:
        surrogate.fit(dataset_X, dataset_Y)
        scores = [acquisition_score(z) for z in pool]
        selected = select_topk_diverse(pool, scores, k=10)

    results = [run_kinematic_oracle(sg, z) for z in selected]
    dataset.extend(results)
    log_round(round_idx, results)
```

**완료 기준**: 50회 테스트 기준 Random Search 대비 FAIL/BLOCKED 발견 수 30% 이상 증가

---

### ✅ P7. Scene 라이브러리 + Cross-scene 전이 Surrogate (완료)

**목표 파일**: `src/active_failure_search.py` (확장), `src/scene_library.py`

**핵심 아이디어**: 단일 scene surrogate를 확장하여 라이브러리 전체 데이터로 학습.
- 한 행 = `[scene_features ‖ mutation_params] → (margin_1..6)`
- 여러 base scene에서 누적 학습 → scene 간 전이 가능한 surrogate
- 새 scene 투입 시 **warm-start**: 라이브러리 surrogate로 시작 → 첫 라운드부터 가속

**비교 실험 3종:**

| 방식 | 설명 |
|---|---|
| Random Search | 유효 mutation 공간에서 무작위 선택 |
| Active cold-start | 해당 scene만으로 학습 (기존 P6) |
| **Active warm-start** | 라이브러리 surrogate로 초기화 후 탐색 |

**완료 기준**: 새 scene에서 warm-start가 cold-start보다 첫 라운드부터 FAIL 발견 곡선이 빠름

---

### ✅ P8. Reporter + Streamlit 대시보드 (완료)

**목표 파일**: `src/reporter.py`, `app.py`

**reporter.py 출력물:**
- `generate_test_table()` → CSV + Markdown 결과표
- `generate_counterexample_report()` → FAIL/BLOCKED 케이스 상세
- `generate_comparison_report()` → Random vs Active 비교 (Failure Discovery Curve)

**app.py 4-패널 레이아웃:**
```
┌──────────────────────┬──────────────────────┐
│  Scene Graph View     │  Active Search        │
│  3D scatter (plotly)  │  Progress Graph       │
│  객체 위치·역할·관계   │  (Active vs Random)   │
├──────────────────────┼──────────────────────┤
│  PyBullet Replay      │  Test Result Table    │
│  스냅샷 슬라이드        │  + Counterexample     │
│  (DIRECT TinyRenderer)│    Report Card        │
└──────────────────────┴──────────────────────┘
```

**완료 기준**: Scene 생성 → Active Search → 실행 → 리포트까지 원클릭 시연 가능

---

### ✅ P9. 비교 실험 + 평가 지표 (완료)

**평가 지표 목표:**

| 지표 | 목표 |
|---|---|
| Failure Discovery Rate@50 | Active > Random + 30% |
| Unique Failure Mode Coverage | 5종 중 4종 이상 |
| Simulation Budget Reduction | 전수 실행 대비 70% 절감 |
| Critical Boundary Discovery | 주요 실패 유형별 경계 케이스 1건 이상 |
| Minimum Perturbation Counterexample | 3건 이상 |
| Safety Block Rate | human risk 조건 BLOCKED 90% 이상 |
| Report Generation Rate | 100% |

---

### ✅ P10. Track B: RGB-D → SceneGraph (완료)

**목표 파일**: `src/vision/rgbd_to_graph.py`

**처리 흐름:**
```
PyBullet camera RGB-D (또는 실제 카메라)
→ depth to point cloud (Open3D)
→ object mask 적용 (YOLO seg 또는 ground-truth mask)
→ object point cloud 추출
→ 3D bounding box 계산
→ support plane 추정 (RANSAC)
→ SceneGraph 생성 (Track A와 동일 스키마)
→ perception_margin 실측값 포함
```

**완료 기준**: RGB-D 입력 → SceneGraph JSON (Track A와 동일 스키마), perception_margin 실측

---

## 파일 구조 (최종 목표)

```
scene2test/
├── .venv/                       # uv 가상환경 (gitignore)
├── .python-version              # 3.12
├── .env                         # PYBULLET_MODE, SEED, LOG_LEVEL
├── .gitignore
├── pyproject.toml               # uv + hatchling + ruff
├── requirements.txt
├── PLAN.md                      # 이 파일
├── config/
│   ├── task_config.yaml         # 작업 정의
│   ├── robot_config.yaml        # Franka Panda 설정
│   ├── thresholds.yaml          # Oracle 임계값
│   └── scene_gen_config.yaml    # 절차적 scene 생성 파라미터
├── src/
│   ├── __init__.py
│   ├── scene_graph.py           ✅ P0 완료 — SceneGraph 스키마 계약
│   ├── scene_builder.py         ✅ P1 완료
│   ├── sim_runner.py            ✅ P1 완료
│   ├── scene_generator.py       🔲 P2
│   ├── validity.py              🔲 P2
│   ├── feature_extractor.py     🔲 P3
│   ├── mutation_space.py        🔲 P4
│   ├── physical_oracle.py       🔲 P5
│   ├── surrogate_model.py       🔲 P6
│   ├── acquisition.py           🔲 P6
│   ├── active_failure_search.py 🔲 P6 → P7 확장
│   ├── scene_library.py         🔲 P7
│   ├── reporter.py              🔲 P8
│   └── vision/
│       └── rgbd_to_graph.py     🔲 P10
├── data/
│   ├── generated_scenes/
│   ├── scene_library/           # 20개 base scene JSON
│   ├── search_logs/
│   └── test_results/
├── models/
│   └── surrogate_model.pkl
├── reports/
│   ├── final_test_report.md
│   └── comparison_report.csv
└── app.py                       🔲 P8
```

---

## 실행 방법 (예정)

```bash
# 가상환경 활성화
source .venv/bin/activate
# 또는
uv run python <script>

# Scene 라이브러리 생성 (P2 완료 후)
python src/scene_generator.py --library-size 20

# Active Failure Search 실행 (P6 완료 후)
python src/active_failure_search.py --scene data/scene_library/scene_001.json

# 비교 실험 (P9)
python src/active_failure_search.py --mode compare --n-tests 50

# 대시보드 실행 (P8 완료 후)
streamlit run app.py
```

---

## 기술 스택

| 역할 | 라이브러리 |
|---|---|
| 물리 시뮬레이션 | `pybullet >= 3.2.6` |
| 수치 계산 | `numpy`, `scipy` |
| Surrogate 모델 | `scikit-learn` (ExtraTrees, GP) |
| 3D 비전 (Track B) | `open3d >= 0.17` |
| 대시보드 | `streamlit >= 1.28` |
| 3D 시각화 | `plotly` |
| 설정 | `pyyaml` |
| 데이터 처리 | `pandas` |
| 패키지 관리 | `uv` |
| 린트 | `ruff` |
| 테스트 | `pytest` |
