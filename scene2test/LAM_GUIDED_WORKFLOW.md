# LAM-Guided Failure Case Generator — 전체 워크플로우

**핵심 목표:** 로봇 정책의 취약성을 자동으로 발견하고, 그 취약성을 드러내는 3D 실패 케이스를 생성하기.

---

## 개요: 4단계 파이프라인

```
┌─────────────────────────────────────────────────────────────┐
│ 1️⃣ OBSERVE: 정책 행동 관찰                                   │
│    → 실제 정책이 어떤 객체를 선택하고 어떻게 집는지 기록      │
├─────────────────────────────────────────────────────────────┤
│ 2️⃣ PROFILE: 취약성 분석                                      │
│    → 관찰 데이터에서 실패 패턴 추출                          │
│    → "이 정책은 유사 객체(distractor)를 혼동한다" 등 진단    │
├─────────────────────────────────────────────────────────────┤
│ 3️⃣ GENERATE: Guided 실패 케이스 생성                         │
│    → 진단된 취약성을 자동으로 드러내는 장면 구성            │
│    → distractor 배치, 경로 차단 등 4가지 family             │
│    → 모든 케이스가 유효한지 검증                             │
├─────────────────────────────────────────────────────────────┤
│ 4️⃣ REFINE: 경계값 정제 (Binary Search)                      │
│    → "이 distractor는 얼마나 가까우면 안 되는가?"          │
│    → PASS↔FAIL 임계값 찾기 (예: ~0.14m)                    │
└─────────────────────────────────────────────────────────────┘
```

이 4단계를 **여러 라운드** 반복하면서 새로운 실패 케이스를 발견합니다.

---

## Step 1: OBSERVE — 정책 행동 관찰

### 목표
정책이 **실제로 어떤 객체를 집는지** 확인하고, 경로 특성(도달 여유, 장애물 거리 등)을 기록합니다.

### 베이스라인: 정상 정책 (RuleLAMProxy)
```bash
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model rule \
    --rounds 1 \
    --enabled
```

**내부 동작:**
1. 씬 로드: `data/scene_library/scene_00001.json` (테이블, target, obstacle들)
2. 정책 실행: `RuleLAMProxy.predict()` → 항상 sg.target() 선택 (정상)
3. 경로 생성: `run_kinematic_check(target_pos=...)` → 도달 여유, 경로 거리 등 계산
4. **산출물:** `RolloutTrace` (어떤 객체 선택, 경로 특성)

**예상 결과:**
- ✅ 항상 target 선택 (selected_obj_id == expected_obj_id)
- ✅ 경로 충돌/안전 문제 없음
- ❌ 실패 없음 → 향상할 게 없다 (좋은 baseline)

### 취약한 정책: 휴리스틱 (MiniActionModel)
```bash
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model mini \
    --rounds 1 \
    --enabled
```

**내부 동작:**
1. 씬 로드
2. 정책 실행: `MiniActionModel.predict()` 
   - 각 객체를 `유사도 × 근접성 - 가림 - 거리 + 노이즈` 로 점수화
   - argmax (점수가 가장 높은 객체 선택)
3. **potential wrong_object_grounding:** target 닮은 distractor가 더 높은 점수 받으면 distractor 선택

**예상 결과:**
- ⚠️ 때때로 distractor 선택 (wrong_object_grounding)
- ⚠️ 여러 경로 variant 생김
- ✅ 이제 향상할 게 있다!

---

## Step 2: PROFILE — 취약성 분석

### 목표
**"이 정책은 정확히 어떤 종류의 실패를 보이는가?"** 를 진단합니다.

### 자동 실행 (loop 내부)
```bash
# 위 Step 1 의 mini 명령이 이 단계를 자동 포함
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model mini \
    --rounds 1 \
    --enabled
```

**내부 동작 (lam_guided_loop.py 라운드 1):**

1. **행동 특성 추출** (`BehaviorTraceEncoder`)
   - `RolloutTrace` → 8차원 벡터로 변환
   - 예: `[wrong_object_selected=1, selection_margin=0.05, grasp_failed=0, ...]`

2. **취약성 진단** (`VulnerabilityProfiler`)
   - 특성 벡터들의 평균 계산
   - 축별로 어느 것이 높은지 확인
     - `wrong_object_selected` 높음 → **semantic_distractor** 취약
     - `ee_oscillation` 높음 → **action_instability** 취약
     - `clearance_pressure` 높음 → **path_blocker** 취약
   - 결과: `VulnerabilityProfile` (권장 family + 가중치)

3. **산출물:** `reports/vulnerability_summary.md`
   ```
   === Vulnerability Profile ===
   wrong_object_selected: 0.45 ← HIGH
   selection_margin: 0.08  ← LOW (여유 없음)
   clearance_pressure: 0.20
   ...
   Recommended families: [semantic_distractor, path_blocker]
   ```

**해석:**
- "이 정책은 유사한 물체(distractor)를 자주 혼동한다"
- "선택 여유가 작다 (약간만 유사해도 선택 바뀜)"

---

## Step 3: GENERATE — Guided 실패 케이스 생성

### 목표
취약성을 **자동으로 드러내는** 실패 케이스를 만듭니다.
- "정책이 distractor를 혼동하면, distractor를 target 옆에 놓아두자"
- "정책이 경로 충돌에 약하면, target으로 가는 경로 위에 장애물을 놓자"

### 자동 실행 (loop 내부)
```bash
# Step 1 의 mini 명령의 라운드 2~4
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model mini \
    --rounds 4 \
    --batch-size 8 \
    --enabled
```

**내부 동작 (각 라운드마다):**

1. **후보 생성** (`FailureCaseGenerator`)
   - Profile에서 권장된 family 기반으로 60개 후보 생성
   - **semantic_distractor family:**
     - 유사도 높은 distractor (red_can, red_block 등)
     - target 근처에 배치 (distance_to_target = 0.05~0.20m)
     - 최소 이격 4cm (reach 실제 변화)
   - **path_blocker family:**
     - robot → target 경로 위에 box 배치
     - 경로 blocking 강도 변화 (offset)
   - **occluder family:**
     - 카메라 ↔ target 사이 tall obstacle
     - occlusion_ratio 0.3~0.8
   - **human_safety_intrusion family:**
     - 경로 중점 근처 human_proxy

2. **유효성 검증** (`ConstraintFilter`)
   ```
   후보 마다:
     - 씬에 추가했을 때 충돌? → 제거
     - 테이블 범위 밖? → 제거
     - 다른 객체와 관통? → 제거
   결과: 유효한 후보만 남김 (예: 60 → 45개)
   ```

3. **상위 후보 선택**
   - 남은 후보를 점수화: `family_prior + novelty + coverage − redundancy`
   - 상위 8개 선택 (batch_size=8)
   - novelty: "지금까지 본 케이스와 다른가?"
   - coverage: "실패 공간에서 새로운 영역인가?"
   - redundancy: "이미 찾은 케이스와 중복인가?"

4. **정책 실행 + 평가** (8개 후보 각각)
   ```
   후보 마다:
     a. 장면 구성: base_scene + 후보 객체 삽입
     b. 정책 실행: policy.predict() → selected_obj_id
     c. rollout: run_kinematic_check(target_pos=selected.position)
     d. 평가: PolicyOracle.evaluate_policy()
        - selected ≠ expected → wrong_object_grounding ✓
        - 경로 충돌? → path_collision ✓
        - 안전 침범? → safety_noncompliance(BLOCKED) ✓
   ```

5. **실패 케이스 기록**
   - verdict = FAIL 또는 BLOCKED인 케이스만 저장
   - `data/counterexamples.jsonl` 에 추가
   ```json
   {
     "case_id": "lam_00032",
     "family": "semantic_distractor",
     "scene_id": "scene_00001",
     "selected_obj_id": "distractor_red_can",
     "expected_obj_id": "target_0",
     "verdict": "FAIL",
     "reason": "wrong_object_grounding"
   }
   ```

**산출물:**
- `data/counterexamples.jsonl` — 발견한 실패 (계속 누적)
- `data/lam_guided_logs/round_*.json` — 각 라운드 상세 로그
- `reports/counterexample_table.csv` — 요약 표

**예상 결과 (4 라운드 후):**
- ✅ semantic_distractor: 2~3개 실패 발견
- ✅ path_blocker: 1~2개 실패 발견
- ✅ 총 10~15개 정책 실패 케이스 확보

---

## Step 4: REFINE — 경계값 정제

### 목표
**"정책이 언제 실패하기 시작하는가?"** 의 정확한 임계값을 찾습니다.

예시:
- semantic_distractor: "distractor가 target으로부터 얼마나 가까우면 안 되는가?" → **~0.14m**
- path_blocker: "경로를 얼마나 차단하면 안 되는가?" → **~0.08m**

### 자동 실행 (loop 종료 후)
Loop가 모든 라운드를 마치면 자동 실행됨:

```bash
# 위 4라운드가 끝난 후 자동으로 실행
# 별도 명령어 없음
```

**내부 동작 (`BoundaryRefiner`):**

각 family (semantic_distractor, path_blocker) 마다:

1. **primary parameter 추출**
   - semantic_distractor: `distance_to_target` (distractor가 target에서 떨어진 거리)
   - path_blocker: `offset_from_path` (장애물이 경로에서 떨어진 거리)

2. **Binary search (8 iteration):**
   ```
   PASS 점수를 가진 값과 FAIL 점수를 가진 값 사이를 이분 탐색
   
   예: semantic_distractor
     초기: distance=0.05m (FAIL, 너무 가까움)
           distance=0.30m (PASS, 너무 멈)
     iter 1: distance=0.175m → FAIL 또는 PASS?
             → 다음 범위 결정
     iter 2: ...
     iter 8: distance=0.14m (수렴)
   ```

3. **stochastic sampling** (안정성)
   - 각 distance마다 30번 샘플링 (policy noise 때문)
   - FAIL률 계산 (예: 30번 중 25번 실패 = 83% FAIL)
   - tolerance 이내 (±0.005m) 수렴할 때까지

4. **산출물:** `reports/boundary_report.md`
   ```
   === Boundary Refinement Report ===
   
   [semantic_distractor]
   Family: semantic_distractor (distractor_red_can)
   Primary Parameter: distance_to_target
   
   PASS at 0.170m (100% success rate)
   FAIL at 0.110m (93% failure rate)
   
   Boundary: 0.14m ± 0.01m
   Interpretation: 정책이 target으로부터 14cm 이내의 distractor는
                  거의 항상 실수한다.
   
   [path_blocker]
   Family: path_blocker (blocker_box)
   Primary Parameter: offset_from_path
   
   Boundary: 0.06m ± 0.01m
   ...
   ```

**해석:**
- "distractor가 target에서 14cm 이내면 안 된다"
- "경로를 6cm 이상 차단하면 안 된다"

---

## 전체 실행: 한 사이클 완전 예시

```bash
cd scene2test

# [준비]
uv sync
uv run python src/scene_generator.py --n 20 --output-dir data/scene_library --seed 0

# [전체 파이프라인: 관찰 → 취약성 → 생성 → 정제]
echo "=== LAM-Guided Failure Case Generator v2 ==="
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model mini \
    --rounds 4 \
    --batch-size 8 \
    --enabled
```

**내부 흐름:**

```
Loop Round 1:
  [OBSERVE] policy.predict() → RolloutTrace
  [PROFILE] encode() → BehaviorFeatures → VulnerabilityProfile
    ├─ wrong_object_selected: 0.45
    ├─ selection_margin: 0.08
    └─ recommended: [semantic_distractor, path_blocker]
  [GENERATE] generate 60 candidates from profile
    ├─ ConstraintFilter: 60 → 45 valid
    ├─ Score & rank: pick top 8
    └─ Execute + evaluate each 8
  [RESULT] 2~3 failures recorded → counterexamples.jsonl

Round 2~3:
  [OBSERVE] 1 baseline rollout
  [PROFILE] update profile (더 많은 데이터)
  [GENERATE] 60 candidates (갱신된 profile 기반)
  [RESULT] 추가 failures

Round 4:
  ... (반복)

After all rounds:
  [REFINE] BoundaryRefiner
    ├─ semantic_distractor: 0.14m 경계값
    └─ path_blocker: 0.06m 경계값
    
Reports generated:
  ├─ vulnerability_summary.md (취약성 프로필)
  ├─ counterexample_table.csv (발견한 실패들)
  ├─ boundary_report.md (경계값)
  └─ lam_guided_logs/*.json (상세 로그)
```

---

## 산출물 해석

### 1. `reports/vulnerability_summary.md`
```
행동 특성 평균치 → "이 정책의 강점과 약점"
```
높은 값 = 문제:
- `wrong_object_selected: 0.45` → distractor 혼동 심함
- `clearance_pressure: 0.30` → 경로 여유 부족

### 2. `reports/counterexample_table.csv`
```csv
case_id,family,selected_obj,verdict,reason,score
lam_00001,semantic_distractor,distractor_red_can,FAIL,wrong_object_grounding,0.85
lam_00002,path_blocker,blocker_box,FAIL,path_collision,0.72
...
```
실제로 발견한 정책 실패들.

### 3. `reports/boundary_report.md`
```
semantic_distractor (distractor_red_can):
  Boundary: 0.14m
  → "14cm 이내면 거의 항상 실수"
```
정책의 **정량적 약점** (테스트 기준).

### 4. `data/counterexamples.jsonl`
```json
{"case_id": "lam_00001", "family": "semantic_distractor", ...}
{"case_id": "lam_00002", "family": "path_blocker", ...}
```
프로그래밍 방식 접근용.

---

## 시각화: Counterexample GIF

실패 케이스를 애니메이션으로 보기:

```bash
PYBULLET_MODE=DIRECT uv run python tools/animate_lam_failure.py --max 4
open data/lam_anim/LAMFC_wrong_object_grounding_*.gif
```

**보이는 것:**
- 녹색 원 (TARGET): 테이블 고정 (정상 위치)
- 빨강 원 (PICKED): 그리퍼가 향함 (정책이 선택한 곳)
- 둘이 다르면 → **wrong_object_grounding** 명확히 보임

---

## 비교 분석: Rule vs Mini vs OpenVLA

같은 씬에서 3가지 정책 비교:

```bash
# Rule (baseline, 정상)
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model rule --rounds 1 --enabled \
    2>&1 | grep -E "Verdict|Profile"

# Mini (취약)
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model mini --rounds 4 --batch-size 8 --enabled \
    2>&1 | grep -E "Verdict|Profile|Boundary"

# OpenVLA (실제 로봇 정책 - stub 또는 openvla)
PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
    --scene data/scene_library/scene_00001.json \
    --policy stub --insert distractor_red_can --gif
```

**비교:**
| 정책 | 정확도 | 발견 실패 | 경계값 |
|---|---|---|---|
| Rule | 100% (항상 target) | 0개 | - |
| Mini | ~55% (distractor 혼동) | 10+ | 0.14m |
| OpenVLA | ? (모르는 것) | ? | ? |

---

## 다음 단계

### 실무 응용
1. **정책 평가 자동화**: "새 정책을 배포해도 되나?" 자동 검증
2. **테스트 케이스 자동 생성**: 이 시스템이 찾은 실패들을 CI/CD 테스트로 추가
3. **강화학습 피드백**: 경계값 근처 케이스를 학습 데이터로 추가 → 정책 개선

### 연구 확장
1. **비교 실험**: 기존 Active Failure vs 랜덤 distractor vs LAM-Guided → 효율성 정량화
2. **더 많은 family**: destination_occupied (목적지 혼동), grasp_difficult_object (잡기 어려운 형태)
3. **VLA 루프 연결**: 전체 LAM-Guided를 OpenVLA와 닫힌 고리로 연결 → 실제 VLA 약점 발견

---

## 핵심 요점

✅ **LAM-Guided는 정책의 약점을 자동으로 찾습니다**
- 정책 행동을 관찰
- 패턴 인식
- 그 패턴을 드러내는 장면 자동 구성

❌ **손으로 만들 수 없는 테스트:**
- "distractor 14cm는 되고 13cm는 안 된다" 같은 미세한 경계
- 정책마다 다른 약점 (policy-specific)

✅ **결과: 정책에 맞춘 테스트 슈트**
- 경제적 (자동 생성)
- 정확 (boundary refinement)
- 재현 가능 (parameter 기록)

