# 3D Vision 기반 Physical AI 테스트 자동화 플랫폼 최종 보고서

## 1. 과제명

### 3D Vision 기반 Physical AI 테스트 자동화 플랫폼
보다 구체적인 제출용 과제명은 다음을 권장한다.
> **3D Scene Graph 기반 Active Failure Search를 활용한 Physical AI 행동 회귀 테스트 자동화 시스템**

약칭:
> **Scene2Test**

---

## 2. 과제 핵심 요약
본 과제는 제조·물류 자동화 환경에서 로봇팔 또는 Physical AI 에이전트가 특정 작업을 수행하기 전, 작업공간의 3D Scene을 기반으로 다양한 실패 조건을 자동 탐색하고 검증하는 시스템을 구현하는 것을 목표로 한다.
핵심은 단순히 3D Scene 안의 물체를 랜덤하게 움직여보는 것이 아니다.
또한 LLM에게 테스트 케이스 목록을 생성하게 하는 것도 아니다.
본 과제의 핵심 AI는 다음이다.
> **3D Scene Graph에서 장면 변형 가능 공간을 정의하고, 물리 시뮬레이션 결과를 피드백으로 사용하여 실패 가능성이 높은 다음 테스트 장면을 능동적으로 찾아가는 Active Failure Search Engine**

즉, 시스템은 다음을 수행한다.

```text
3D Scene 인식
→ Scene Graph 생성
→ 장면 변형 파라미터 공간 정의
→ 초기 테스트 실행
→ 물리 Robustness Score 계산
→ AI Surrogate Model 학습
→ Acquisition Function으로 다음 테스트 제안
→ 시뮬레이션 실행
→ 실패 조건 및 경계 조건 발견
→ 회귀 테스트셋과 리포트 생성
```

이 과제의 목적은 **로봇을 잘 움직이는 데모**가 아니라, **Physical AI가 실제 환경에서 실패하기 전에 실패 조건을 자동으로 찾아내는 테스트 자동화 시스템**을 구현하는 것이다.

---

# 3. 문제 정의
## 3.1 배경
제조·물류 자동화 영역에서는 로봇팔, AMR, 비전 AI 기반 자동화 솔루션의 도입이 증가하고 있다. 이러한 Physical AI 시스템은 실제 공간에서 행동하기 때문에, 소프트웨어 모델의 예측 정확도만으로는 충분히 검증되기 어렵다.
예를 들어 실험실 환경에서는 정상적으로 작동하던 로봇 pick-and-place 작업도 실제 운영 환경에서는 다음 요인으로 실패할 수 있다.

```text
- 목표 물체 위치 변화
- 장애물 추가
- 작업자 손 또는 사람 접근
- 목적지 영역 점유
- 로봇 작업 반경 초과
- 그리퍼 접근 공간 부족
- 카메라 가림 또는 depth 불확실성
- 현장 배치 변경
```

현재 이러한 실패 조건 검증은 사람이 예상 가능한 케이스를 수작업으로 정의하거나, 실제 로봇 장비에서 제한된 조건만 반복 검증하는 방식에 의존하는 경우가 많다. 이 방식은 테스트 케이스 생성 시간이 오래 걸리고, 위험 조건을 체계적으로 탐색하기 어렵고, 실패 원인을 빠르게 분류하기도 어렵다.

---

## 3.2 핵심 Pain Point

| 구분 | Pain Point            | 설명                                                                                              |
| -- | --------------------- | ----------------------------------------------------------------------------------------------- |
| P1 | 테스트 케이스 생성이 수작업 중심    | 작업공간별 목표물, 장애물, 목적지, 사람 접근 조건을 사람이 일일이 설계해야 함                                                   |
| P2 | 실제 로봇 기반 반복 검증 비용이 높음 | 실제 장비에서 모든 환경 변형을 검증하기 어렵고, 충돌·안전 리스크가 존재함                                                      |
| P3 | 실패 조건 탐색이 비효율적        | 랜덤 또는 수동 테스트는 경계 조건과 드문 실패 조건을 놓치기 쉬움                                                           |
| P4 | 실패 원인 분석이 어려움         | 실패가 reachability, collision, clearance, human safety, perception uncertainty 중 무엇 때문인지 구분하기 어려움 |
| P5 | 현장 변경 시 재검증 생산성이 낮음   | 물체 배치나 작업공간이 바뀔 때마다 테스트 케이스를 다시 설계해야 함                                                          |

---

# 4. 해결 방향
## 4.1 기존 접근의 한계

초기 아이디어는 다음과 같은 구조였다.

```text
3D Scene Graph
→ 후보 테스트 다수 생성
→ AI Risk Scorer가 PASS/FAIL 예측
→ 위험도 높은 후보 선택
→ 시뮬레이션 실행
```

하지만 이 방식은 핵심 AI가 약해 보일 수 있다.
평가자 입장에서는 다음과 같이 볼 수 있기 때문이다.

> “결국 랜덤하게 만든 feature와 시뮬레이션 라벨로 지도학습 분류기를 만든 것 아닌가?”

따라서 본 과제에서는 단순 Risk Scorer를 핵심으로 두지 않는다.
대신 **Active Failure Search** 구조로 확장한다.

---

## 4.2 최종 핵심 아이디어
본 과제의 핵심 엔진은 다음과 같다.

> **3D Scene Graph 기반 Active Failure Search Engine**

이는 3D Scene 내 component들을 무작위로 바꾸는 방식이 아니라, 다음 절차로 실패 조건을 능동 탐색한다.

```text
1. 3D Scene Graph에서 변형 가능한 요소를 정의한다.
2. 목표 작업의 성공/실패를 판단할 robustness score를 정의한다.
3. 초기 테스트를 소량 실행한다.
4. 실행 결과로 surrogate model을 학습한다.
5. 모델의 예측값과 불확실성을 이용해 다음 테스트 장면을 제안한다.
6. 제안된 테스트를 시뮬레이션에서 실행한다.
7. 새 결과를 반영해 모델을 갱신한다.
8. 제한된 테스트 예산 안에서 실패 조건과 경계 조건을 최대한 많이 발견한다.
```

즉, AI의 역할은 단순 분류가 아니라:

```text
- 어떤 장면 조건이 실패를 유발할 가능성이 높은지 예측
- 아직 탐색되지 않은 불확실한 영역 탐색
- PASS/FAIL 경계 조건 탐색
- 최소한의 장면 변화로 실패를 유발하는 반례 탐색
- 테스트 예산 안에서 실패 발견 효율 극대화
```

이다.

이 접근은 시뮬레이션만 가능한 복잡한 시스템에서 사양 위반 입력, 즉 counterexample을 찾는 **simulation-based falsification** 흐름과 유사하다. 해당 분야에서는 계산 비용이 큰 시뮬레이션 횟수를 줄이기 위해 surrogate model과 Bayesian Optimization을 활용하는 접근이 연구되어 왔다. ([arXiv][1])

---

# 5. 과제에서 말하는 테스트 케이스의 정의
본 과제에서 테스트 케이스는 단순한 작업 명령이 아니다.

## 5.1 테스트 케이스 정의

> **Physical AI 테스트 케이스란, 특정 로봇 작업을 검증하기 위한 3D 장면 상태, 장면 변형 조건, 물리 검증 기준, 기대 또는 측정 판정을 포함하는 실행 단위이다.**

예시는 다음과 같다.

```json
{
  "test_id": "T04_obstacle_near_target",
  "task": {
    "type": "pick_and_place",
    "target": "red_block",
    "destination": "tray"
  },
  "scene_mutation": {
    "type": "move_obstacle_near_target",
    "object": "blue_obstacle",
    "target": "red_block",
    "distance_m": 0.04
  },
  "validation": {
    "check_reachability": true,
    "check_collision": true,
    "check_clearance": true,
    "check_human_safety": true
  },
  "expected_or_measured_result": {
    "decision": "FAIL",
    "reason": "insufficient_clearance"
  }
}
```

즉, 테스트 케이스는 다음의 조합이다.

```text
테스트 케이스 =
작업 목표
+ 3D 장면 상태
+ 장면 변형 파라미터
+ 물리 검증 기준
+ 시뮬레이션 실행 결과
```

---

## 5.2 테스트 케이스 예시

기본 작업을 다음과 같이 고정한다.

```text
red_block을 집어서 tray에 놓기
```

이때 자동으로 탐색할 수 있는 테스트 장면은 다음과 같다.

| Test | 장면 조건                              | 검증 목적                  |
| ---- | ---------------------------------- | ---------------------- |
| T01  | 현재 장면 그대로 실행                       | 기본 성공 여부               |
| T02  | target을 좌우 5cm 이동                  | 위치 변화 강건성              |
| T03  | target을 로봇 작업 반경 끝으로 이동            | 도달 가능성 경계              |
| T04  | obstacle을 target 4cm 옆으로 이동        | gripper clearance 부족   |
| T05  | obstacle을 접근 경로 중앙에 배치             | path collision         |
| T06  | human zone을 작업 경로 근처에 삽입           | safety stop            |
| T07  | tray 위에 장애물을 배치                    | destination occupied   |
| T08  | target 주변에 unknown/occlusion 영역 추가 | perception uncertainty |

중요한 점은 **작업 자체를 많이 만드는 것**이 아니라, **정해진 작업이 어떤 3D 환경 변화에서 실패하는지 찾는 것**이다.

---

# 6. 구현 범위

## 6.1 MVP 범위

1인 과제의 완성도를 확보하기 위해 범위를 명확히 제한한다.

| 항목     | MVP 범위                                   |
| ------ | ---------------------------------------- |
| 작업공간   | 책상 또는 작업대 위 1개 영역                        |
| 작업 종류  | pick-and-place 1종                        |
| 로봇     | PyBullet 내 Franka Panda 또는 KUKA 로봇팔      |
| 객체     | 목표 블록, 장애물, 트레이, 사람 위험 영역                |
| 입력     | 1차: PyBullet 시뮬레이션 장면 / 2차: RGB-D 카메라 확장 |
| 테스트 방식 | Active Failure Search 기반 테스트 장면 탐색       |
| 판정     | PASS / FAIL / WARN / BLOCKED             |
| 산출물    | 데모 앱, 테스트 결과표, 실패 원인 리포트, 탐색 성능 비교       |

---

## 6.2 하지 않는 것

과제 범위가 지나치게 커지는 것을 막기 위해 다음은 제외한다.

```text
- 실제 로봇 하드웨어 제어
- 범용 VLA/VLM 기반 로봇 정책 학습
- 실제 3D reconstruction mesh의 포토리얼 편집
- 객체 제거 후 생기는 빈 영역의 3D inpainting
- 모든 component의 정밀 mesh 복원
- LLM 기반 테스트 케이스 직접 생성
- 복잡한 grasp planning
- 실시간 SLAM 전체 구현
```

---

## 6.3 하는 것

본 과제에서 실제 구현할 것은 다음이다.

```text
- 시뮬레이션 또는 RGB-D 기반 3D Scene 생성
- 객체, 지지면, 목적지, 장애물, 사람 위험 영역 추출
- 3D Scene Graph 생성
- 장면 변형 파라미터 공간 정의
- 물리 robustness score 정의
- Active Failure Search Engine 구현
- PyBullet 기반 테스트 실행
- Physical Oracle 기반 PASS/FAIL/WARN/BLOCKED 판정
- 실패 조건 및 경계 조건 리포트 생성
```

---

# 7. 시스템 아키텍처

## 7.1 전체 구조

```text
[RGB-D / Simulation Scene]
          ↓
[3D Vision & Scene Parsing]
          ↓
[3D Scene Graph]
          ↓
[Mutation Space Builder]
          ↓
[Active Failure Search Engine]
   ├─ Initial Test Sampler
   ├─ Surrogate Model
   ├─ Acquisition Function
   ├─ Diversity / Coverage Controller
   └─ Simulation Feedback Loop
          ↓
[PyBullet Simulation Runner]
          ↓
[Physical Oracle]
          ↓
[Counterexample Test Suite]
          ↓
[Test Report / Dashboard]
```

---

## 7.2 주요 모듈

| 모듈                           | 역할                                            |
| ---------------------------- | --------------------------------------------- |
| Scene Builder                | PyBullet 또는 RGB-D 입력으로 작업공간 구성                |
| Scene Parser                 | 객체, 지지면, 목적지, 장애물, human zone 추출              |
| Scene Graph Builder          | 객체 위치, 크기, 역할, 관계를 graph 형태로 저장               |
| Mutation Space Builder       | 변형 가능한 component와 파라미터 범위 정의                  |
| Active Failure Search Engine | 실패 조건을 능동 탐색                                  |
| Simulation Runner            | 테스트 장면을 PyBullet에서 실행                         |
| Physical Oracle              | reachability, collision, clearance, safety 판정 |
| Reporter                     | 결과표, 실패 원인, 개선 권고 생성                          |
| Dashboard                    | 테스트 생성·실행·탐색 과정을 시각화                          |

---

# 8. 3D Scene Graph 설계

## 8.1 Scene Graph 예시

```json
{
  "scene_id": "desk_scene_001",
  "support_surfaces": [
    {
      "id": "table_1",
      "type": "plane",
      "height": 0.0,
      "bounds": {
        "x": [0.20, 0.80],
        "y": [-0.35, 0.35]
      }
    }
  ],

  "objects": [
    {
      "id": "red_block",
      "role": "target",
      "position": [0.45, -0.10, 0.05],
      "size": [0.06, 0.06, 0.08],
      "movable": true
    },
    {
      "id": "blue_obstacle",
      "role": "obstacle",
      "position": [0.35, -0.08, 0.05],
      "size": [0.08, 0.08, 0.08],
      "movable": true
    },
    {
      "id": "tray",
      "role": "destination",
      "position": [0.60, 0.20, 0.03],
      "size": [0.18, 0.12, 0.04],
      "movable": false
    }
  ],
  "relations": [
    {
      "type": "near",
      "source": "blue_obstacle",
      "target": "red_block",
      "distance_m": 0.11
    },
    {
      "type": "reachable",
      "source": "panda_arm",
      "target": "red_block",
      "value": true
    }
  ],
  "unknown_regions": []
}

```

---

## 8.2 Scene Graph의 역할

3D Scene Graph는 단순한 장면 표현이 아니라, 테스트 생성과 실패 탐색의 입력이다.
Scene Graph를 통해 다음을 계산한다.

```text
- target과 robot 간 거리
- target과 obstacle 간 거리
- gripper 접근 여유 공간
- target이 작업 반경 내에 있는지 여부
- obstacle이 접근 경로 위에 있는지 여부
- tray가 점유되어 있는지 여부
- human zone이 경로와 안전거리 이내인지 여부
- unknown region 또는 occlusion과 경로의 overlap 여부
```

ConceptGraphs와 같은 연구는 2D foundation model 결과를 3D로 융합해 open-vocabulary 3D scene graph를 만들고, 이를 downstream planning에 활용하는 방향을 제시한다. 본 과제는 이와 유사하게 3D Scene Graph를 활용하지만, 최종 목적을 planning 자체가 아니라 **Physical AI 행동 회귀 테스트 자동화**로 둔다. ([ConceptGraphs][2])

---

# 9. 3D Scene 편집과 빈 공간 문제 처리

실제 3D Scene에서 component를 움직이면 해당 component가 있던 자리에 빈 공간이 생긴다. 이 문제를 포토리얼하게 해결하려고 하면 3D inpainting 또는 3D scene editing 연구가 되어 과제 범위가 지나치게 커진다.
본 과제에서는 다음 원칙을 적용한다.

> **원본 3D reconstruction을 직접 편집하지 않고, Scene Graph 기반 Editable Test World를 생성한다.**

즉, 실제 장면은 테스트 월드를 만들기 위한 계측 데이터로 사용하고, 테스트 실행은 proxy object 기반 시뮬레이션 장면에서 수행한다.

| 이슈                        | 처리 전략                                   |
| ------------------------- | --------------------------------------- |
| 물체를 치웠을 때 생기는 시각적 빈 공간    | 포토리얼 복원하지 않음                            |
| 책상 위 물체 제거로 생긴 자리         | 주변 지지면을 기준으로 table plane으로 보간           |
| 카메라가 보지 못한 영역             | unknown region으로 표시                     |
| unknown region을 로봇 경로가 통과 | WARN 또는 BLOCKED 판정                      |
| 테스트 실행 장면                 | box, cylinder, tray 등 proxy object로 재구성 |
| 목적                        | 시각적 자연스러움이 아니라 물리 테스트 가능성 확보            |

따라서 본 과제는 **3D Scene Editing**이 아니라 **Physical Test World Generation**을 목표로 한다.

---

# 10. Active Failure Search Engine 상세 설계

## 10.1 장면 변형 파라미터 공간 정의

Scene Graph에서 변형 가능한 component를 찾고, 테스트 목적에 맞는 파라미터 공간을 정의한다.

예:

```json
{
  "target_dx": [-0.10, 0.10],
  "target_dy": [-0.10, 0.10],
  "obstacle_angle": [0, 360],
  "obstacle_distance_to_target": [0.02, 0.20],
  "human_zone_x": [0.25, 0.75],
  "human_zone_y": [-0.35, 0.35],
  "tray_occupied": [0, 1],
  "occlusion_ratio": [0.0, 0.6]
}
```

하나의 파라미터 벡터는 하나의 테스트 장면을 의미한다.

```text
z = [
  target_dx,
  target_dy,
  obstacle_angle,
  obstacle_distance_to_target,
  human_zone_x,
  human_zone_y,
  tray_occupied,
  occlusion_ratio
]

```

---

## 10.2 물리 유효성 제약

AI가 아무 장면이나 만들면 안 된다.
따라서 테스트 후보는 아래 제약을 만족해야 한다.

```text
- 객체는 table bounds 안에 있어야 함
- 객체는 support surface 위에 있어야 함
- 객체끼리 초기 상태에서 비현실적으로 겹치면 안 됨
- target과 destination은 식별 가능해야 함
- human zone은 작업공간 안에 있어야 함
- 변형 후 장면은 PyBullet에서 로딩 가능해야 함
```

이 부분은 AI가 아니라 rule/constraint 기반으로 처리한다.

---

## 10.3 Robustness Score 정의

단순 PASS/FAIL 분류 대신, 각 테스트 장면이 얼마나 안전하고 여유 있게 성공 가능한지 나타내는 **robustness score**를 정의한다.

예:

```text
reach_margin      = max_reach - robot_to_target_distance
clearance_margin  = actual_clearance - required_gripper_clearance
collision_margin  = min_path_obstacle_distance - collision_threshold
safety_margin     = min_path_human_distance - safety_distance
goal_margin       = available_goal_space - object_footprint
perception_margin = perception_confidence - confidence_threshold
```

전체 robustness는 다음과 같이 정의한다.

```text
robustness = min(
    reach_margin,
    clearance_margin,
    collision_margin,
    safety_margin,
    goal_margin,
    perception_margin
)

```

판정 기준은 다음과 같다.

```text
robustness > 0  → PASS
robustness ≈ 0  → 경계 조건
robustness < 0  → FAIL / BLOCKED / WARN
```

이렇게 하면 AI의 목표가 단순 분류가 아니라:

> **robustness가 0 이하가 되는 장면 조건을 빠르게 찾는 것**

으로 바뀐다.

---

## 10.4 Surrogate Model

PyBullet 시뮬레이션은 상대적으로 비용이 들기 때문에 모든 장면 변형 후보를 실행하지 않는다.
대신 일부 실행 결과를 바탕으로 surrogate model을 학습한다.
학습 대상 함수는 다음이다.

```text
f(scene_graph_features, mutation_parameters) → robustness
```

또는:

```text
f(scene_graph_features, mutation_parameters) → failure_probability, failure_type
```

MVP에서 사용할 수 있는 모델은 다음과 같다.

| 모델                        | 활용 이유                                                     |
| ------------------------- | --------------------------------------------------------- |
| Gaussian Process          | Bayesian Optimization과 잘 맞고 불확실성 추정이 자연스러움                |
| RandomForest / ExtraTrees | 구현이 쉽고 tabular feature에 강하며 ensemble variance로 불확실성 근사 가능 |
| XGBoost                   | 표 형태 feature 기반 예측 성능이 좋음                                 |
| MLP Ensemble              | 확장 가능하지만 설명성은 상대적으로 낮음                                    |

scikit-learn의 Gaussian Process는 회귀와 확률적 분류에 사용할 수 있는 비모수 supervised learning 방법이며, Bayesian Optimization 계열에서는 관측값 기반 surrogate model을 만들고 acquisition function으로 다음 평가점을 선택하는 구조가 일반적이다. ([Scikit-learn][3])

---

## 10.5 Acquisition Function

Active Failure Search의 핵심은 다음 테스트를 어떻게 고를 것인가이다.
본 과제에서는 다음 요소를 함께 고려한다.

```text
- 실패 가능성
- 모델 불확실성
- 안전 중요도
- 실패 유형 다양성
- 기존 테스트와의 중복도
- 물리 유효성
```

예시 수식:

```text
A(z) =
    w1 * P(robustness(z) < 0)
  + w2 * uncertainty(z)
  + w3 * safety_priority(z)
  + w4 * novelty(z)
  - w5 * redundancy(z)
  - w6 * invalid_scene_penalty(z)
```

선택 기준:

```text
- 실패 가능성이 높은 테스트
- 아직 모델이 잘 모르는 테스트
- 안전상 중요한 테스트
- 기존에 발견하지 못한 실패 유형을 유발할 가능성이 있는 테스트
- 기존 테스트와 중복이 적은 테스트
```

---

## 10.6 탐색 루프

전체 Active Failure Search는 다음 루프로 동작한다.

```python
dataset = []
for round_idx in range(num_rounds):
    candidate_pool = sample_valid_mutations(scene_graph, n=1000)
    if len(dataset) < min_train_size:
        selected_tests = select_initial_seed_tests(candidate_pool, k=10)
    else:
        surrogate = train_surrogate_model(dataset)
        for candidate in candidate_pool:
            pred_mean, pred_uncertainty = surrogate.predict(candidate.features)
            candidate.acquisition_score = (
                w_fail * prob_failure(pred_mean)
                + w_uncertainty * pred_uncertainty
                + w_safety * safety_priority(candidate)
                + w_novelty * novelty_score(candidate, dataset)
                - w_redundancy * redundancy_score(candidate, dataset)
            )
        selected_tests = select_topk_with_diversity(candidate_pool, k=10)
    results = run_pybullet_simulation(selected_tests)
    evaluated = compute_robustness_and_failure_type(results)
    dataset.extend(evaluated)
```

이 구조가 기존 단순 지도학습 Risk Scorer와 가장 큰 차이점이다.

---

# 11. Physical Oracle 설계

Physical Oracle은 테스트 실행 결과를 판정하는 기준이다.

## 11.1 판정값

| 판정      | 의미                        |
| ------- | ------------------------- |
| PASS    | 작업 성공                     |
| FAIL    | 물리적으로 실패                  |
| WARN    | 실행 가능하지만 불확실성 또는 위험 징후 존재 |
| BLOCKED | 안전상 실행 금지                 |

---

## 11.2 Oracle 종류

| Oracle              | 판정 기준                                               |
| ------------------- | --------------------------------------------------- |
| Reachability Oracle | 로봇 end-effector가 목표 pose에 도달 가능한지                   |
| Collision Oracle    | 로봇 link, 장애물, 물체 간 충돌 여부                            |
| Clearance Oracle    | target 주변 gripper 접근 여유 공간이 충분한지                    |
| Human Safety Oracle | human zone이 작업 경로 또는 작업 반경과 안전거리 이내인지               |
| Destination Oracle  | tray 또는 목적지가 비어 있고 place 가능한지                       |
| Perception Oracle   | unknown region, occlusion, depth confidence 문제가 있는지 |

PyBullet은 URDF/SDF/MJCF 로딩, forward/inverse kinematics, collision detection, ray query 등을 제공하므로 로봇 행동 검증용 시뮬레이션 엔진으로 적합하다. ([GitHub][4])

---

## 11.3 판정 예시

```json
{
  "test_id": "T04_obstacle_near_target",
  "result": "FAIL",
  "failure_type": "insufficient_clearance",
  "robustness": -0.019,
  "reason": "target 주변 최소 여유 공간 4.1cm가 요구 clearance 6.0cm보다 작음",
  "recommendation": "장애물을 target으로부터 최소 6cm 이상 이동하거나 우측 접근 경로 사용"
}

```

---

# 12. 3D Vision 및 인식 구현 계획

## 12.1 1단계: 시뮬레이션 Ground Truth 기반

초기에는 PyBullet 장면의 객체 위치와 크기를 그대로 사용해 Scene Graph를 만든다.

장점:

```text
- 구현 안정성 높음
- Active Failure Search 엔진을 먼저 완성 가능
- 발표 데모 실패 가능성 낮음
```

---

## 12.2 2단계: 시뮬레이션 RGB-D 기반

PyBullet 카메라에서 RGB-D 이미지를 생성하고, 이를 통해 point cloud를 만든다.
Open3D는 point cloud 시각화와 geometry 처리를 지원하므로 3D 처리 모듈에 사용할 수 있다. ([Open3D][5])

처리 흐름:

```text
PyBullet camera RGB-D
→ depth to point cloud
→ object mask 적용
→ object point cloud 추출
→ 3D bounding box 계산
→ Scene Graph 생성
```

---

## 12.3 3단계: 실제 RGB-D 카메라 확장

시간이 허용되면 RealSense 등 실제 RGB-D 카메라 입력을 붙인다.

처리 흐름:

```text
RGB-D camera
→ object detection / segmentation
→ mask + depth 기반 3D 위치 추정
→ support plane 추정
→ proxy object world 생성
→ Active Failure Search 실행
```

객체 검출·분할에는 YOLO segmentation 계열 모델을 사용할 수 있다. Ultralytics YOLO는 Python에서 object detection, instance segmentation, semantic segmentation 등에 활용 가능하다. ([Ultralytics Docs][6])

---

# 13. 구현 로드맵

## Phase 1. PyBullet 기본 작업 구현

목표:

```text
- 로봇팔 로드
- 책상, target, obstacle, tray 생성
- 기본 pick-and-place 동작 구현
- reachability, collision check 구현
```

완료 기준:

```text
red_block을 tray로 이동하는 기본 시뮬레이션 동작
```

---

## Phase 2. Scene Graph 생성

목표:

```text
- 객체 위치, 크기, 역할 저장
- 객체 간 거리와 관계 계산
- support surface와 workspace bounds 정의
```

완료 기준:

```text
PyBullet 장면이 JSON Scene Graph로 변환됨
```

---

## Phase 3. Mutation Space Builder 구현

목표:

```text
- target shift
- obstacle near target
- path blocked
- human zone insertion
- destination occupied
- reach boundary
- perception uncertainty
```

완료 기준:

```text
하나의 Scene Graph에서 1,000개 이상의 유효한 mutation 후보 샘플링 가능
```

---

## Phase 4. Physical Oracle 구현

목표:

```text
- Reachability Oracle
- Collision Oracle
- Clearance Oracle
- Human Safety Oracle
- Destination Oracle
- Perception Oracle
```

완료 기준:

```text
각 테스트 실행 후 PASS / FAIL / WARN / BLOCKED 및 robustness score 자동 산출
```

---

## Phase 5. Active Failure Search Engine 구현

목표:

```text
- 초기 seed test 실행
- surrogate model 학습
- acquisition function 계산
- top-K 테스트 선택
- 시뮬레이션 결과 기반 모델 업데이트
```

완료 기준:

```text
Random Search 대비 동일 테스트 예산에서 더 많은 FAIL/BLOCKED 조건 발견
```

---

## Phase 6. 대시보드 및 리포트 구현

목표:

```text
- Scene Graph View
- Mutation 후보 분포
- Active Search 진행 현황
- PyBullet Replay
- Test Result Table
- Counterexample Report
```

완료 기준:

```text
Scene 생성 → Active Search → 테스트 실행 → 실패 조건 리포트까지 하나의 데모로 시연 가능
```

---

# 14. 평가 방법

## 14.1 핵심 평가 지표

| 지표                                  | 의미                             | 목표                  |
| ----------------------------------- | ------------------------------ | ------------------- |
| Failure Discovery Rate@K            | K개 테스트 실행 시 발견한 FAIL/BLOCKED 수 | Random 대비 30% 이상 증가 |
| Unique Failure Mode Coverage        | 발견한 실패 유형 개수                   | 5종 중 4종 이상          |
| Simulation Budget Reduction         | 전체 후보 전수 실행 대비 필요한 시뮬레이션 수 감소  | 70% 이상 절감           |
| Critical Boundary Discovery         | PASS/FAIL 경계 조건 발견 여부          | 주요 실패 유형별 1건 이상     |
| Minimum Perturbation Counterexample | 최소 장면 변화로 실패 유발 사례             | 3건 이상               |
| Robustness Prediction Error         | surrogate의 robustness 예측 오차    | baseline 대비 개선      |
| Safety Block Rate                   | human risk 조건 BLOCKED 판정율      | 90% 이상              |
| Report Generation Rate              | 실패 원인·권고 자동 생성률                | 100%                |

---

## 14.2 비교 실험

AI의 효과를 보이기 위해 세 가지 방법을 비교한다.

| 방식                    | 설명                                     |
| --------------------- | -------------------------------------- |
| Random Search         | 유효 mutation 공간에서 무작위로 테스트 선택           |
| Rule-only Test        | 사람이 정의한 고정 테스트셋 실행                     |
| Active Failure Search | surrogate + acquisition 기반으로 다음 테스트 선택 |

예상 결과 예시:

| 방식                    | 테스트 수 | FAIL/BLOCKED 발견 수 | 실패 유형 수 |
| --------------------- | ----: | ----------------: | ------: |
| Random Search         |    20 |                 5 |       2 |
| Rule-only Test        |    20 |                 7 |       3 |
| Active Failure Search |    20 |                11 |       5 |

이 비교가 본 과제의 AI 활용 효과를 가장 직접적으로 보여준다.

---

# 15. 기존 유사 기술과의 차이점

## 15.1 Embodied AI 시뮬레이터와의 차이

AI2-THOR는 embodied AI 연구를 위한 interactive 3D 환경이며, ManipulaTHOR는 AI2-THOR 내에서 로봇팔을 이용한 visual manipulation 환경을 제공한다. ([AI2-THOR][7]) Habitat 3.0은 humanoid avatar와 robot이 함께 있는 환경에서 collaborative human-robot task를 연구하기 위한 시뮬레이션 플랫폼이다. ([AI Habitat][8])

| 구분    | 기존 Embodied AI 시뮬레이터               | 본 과제                                         |
| ----- | ---------------------------------- | -------------------------------------------- |
| 목적    | 로봇 정책 학습, benchmark 평가             | Physical AI 개발·운영 검증 자동화                     |
| 입력    | 사전 구축된 3D 환경                       | 실제/시뮬레이션 Scene Graph                         |
| 핵심 기능 | 환경 제공, task 수행                     | 실패 조건 탐색, 반례 테스트 생성                          |
| AI 역할 | policy 학습 중심                       | Active Failure Search 중심                     |
| 산출물   | task success rate, benchmark score | counterexample, failure boundary, 회귀 테스트 리포트 |

---

## 15.2 Scenic류 시나리오 생성 기술과의 차이

Scenic은 cyber-physical system을 테스트·훈련하기 위해 scene 내 객체와 agent의 위치, 방향, 속성 등을 확률분포와 제약으로 기술하고, 이를 sampling하여 구체적인 환경 구성을 만드는 probabilistic programming language이다. Scenic은 Webots, Gazebo 같은 로봇 시뮬레이터와 연동해 robot training/testing/debugging에 활용될 수 있다고 설명된다. ([Scenic][9])

| 구분      | Scenic류 접근              | 본 과제                               |
| ------- | ----------------------- | ---------------------------------- |
| 시나리오 정의 | 사람이 scenario program 작성 | Scene Graph에서 mutation space 자동 구성 |
| 생성 방식   | 확률분포 기반 scene sampling  | Active Failure Search 기반 반례 탐색     |
| 핵심 목표   | 다양한 scenario 생성         | 적은 테스트로 실패 조건 발견                   |
| AI 활용   | 샘플링/제약 중심               | surrogate model + acquisition      |
| 산출물     | 시뮬레이션 scenario          | 실패 경계, 최소 반례, 회귀 테스트셋              |

---

## 15.3 GenSim / RoboGen과의 차이

GenSim은 LLM의 grounding과 coding 능력을 활용해 simulation environment와 expert demonstration을 자동 생성하는 연구다. ([arXiv][10]) RoboGen은 foundation/generative model을 활용해 다양한 robotic skill을 generative simulation으로 학습하는 접근을 제시한다. ([arXiv][11])

| 구분     | GenSim / RoboGen                 | 본 과제                                |
| ------ | -------------------------------- | ----------------------------------- |
| 목적     | 새로운 task와 skill learning data 생성 | 기존 업무 작업의 실패 조건 탐색                  |
| 생성 대상  | task, scene, demonstration       | test scene mutation, counterexample |
| 핵심 AI  | LLM/generative model 중심          | Active Failure Search 중심            |
| 평가 기준  | skill learning, task diversity   | failure discovery, test efficiency  |
| 업무 연결성 | 연구용 task 다양화                     | 개발·운영 검증 생산성 향상                     |

본 과제는 새로운 로봇 작업을 대량 생성하는 것이 아니라, **이미 정의된 업무 작업이 어떤 환경 조건에서 실패하는지 찾는 것**에 초점을 둔다.

---

## 15.4 단순 지도학습 Risk Scorer와의 차이

| 구분     | 단순 Risk Scorer     | 본 과제의 Active Failure Search              |
| ------ | ------------------ | ---------------------------------------- |
| 데이터 수집 | 랜덤/규칙 기반으로 한 번에 수집 | 시뮬레이션 결과를 보며 능동 수집                       |
| 모델 역할  | PASS/FAIL 분류       | 다음 테스트 장면 제안                             |
| 목표     | 후보 정렬              | 실패 조건과 경계 조건 탐색                          |
| 출력     | risk score         | counterexample test, boundary case       |
| 평가     | 분류 정확도             | failure discovery rate, budget reduction |
| AI 기여  | 보조적                | 테스트 생성의 핵심                               |

이 차이가 본 과제의 가장 중요한 차별점이다.

---

# 16. 과제 신청서 작성안

아래는 신청서 항목에 바로 넣을 수 있는 형태로 작성한 내용이다.

---

## 과제 정의

### 대상

> 제조·물류 자동화 프로젝트에서 로봇팔 또는 Physical AI 에이전트를 활용한 pick-and-place 작업을 대상으로, 배포 전 작업공간 변화에 따른 행동 실패 가능성을 자동 탐색·검증하는 개발·운영 테스트 영역

구체적인 가정 시나리오는 다음과 같다.

> 고객사 제조·물류 현장에 로봇 기반 자동화 시스템을 적용하기 전, 작업대 위 목표 물체, 장애물, 목적지, 작업자 접근 영역 등 3D 환경 조건 변화에 따라 로봇 행동이 성공하는지, 충돌하는지, 작업 반경을 벗어나는지, 안전상 중단되어야 하는지를 자동 검증한다.

---

### 선정 배경

제조·물류 자동화 영역에서는 로봇팔, AMR, 비전 AI 기반 자동화 시스템 도입이 증가하고 있다. 이러한 Physical AI 시스템은 실제 공간에서 행동하므로, 실험 환경에서 정상 동작하더라도 운영 환경에서는 물체 위치 변화, 장애물 추가, 작업자 접근, 목적지 점유, 카메라 가림, 조명 변화 등으로 실패할 수 있다.

현재 이러한 실패 조건은 주로 사람이 수작업으로 테스트 케이스를 정의하거나, 실제 장비 또는 제한된 시뮬레이션에서 반복 검증하는 방식에 의존한다. 이 경우 테스트 케이스 생성 시간이 오래 걸리고, 위험 조건을 충분히 탐색하기 어렵고, 실패 발생 시 원인이 인식 문제인지, 충돌 문제인지, 도달 가능성 문제인지, 안전 조건 문제인지 빠르게 구분하기 어렵다.

본 과제는 3D Vision, 3D Scene Graph, 물리 시뮬레이션, Active Failure Search를 결합하여 Physical AI 행동 테스트를 자동화함으로써, 로봇/AI 자동화 솔루션의 개발·운영 검증 생산성을 높이고자 한다.

---

### Pain Point

| Pain Point             | 설명                                                                                              |
| ---------------------- | ----------------------------------------------------------------------------------------------- |
| 테스트 케이스 생성이 수작업 중심     | 작업공간마다 목표물 위치, 장애물, 작업자 접근, 목적지 점유 등 실패 조건을 사람이 직접 설계해야 함                                       |
| 실제 장비 기반 반복 테스트 비용이 높음 | 모든 환경 변형을 실제 로봇으로 검증하기 어렵고, 충돌·안전 리스크가 존재함                                                      |
| 실패 조건 탐색이 비효율적         | 랜덤 또는 수동 테스트는 경계 조건과 드문 실패 조건을 놓치기 쉬움                                                           |
| 실패 원인 분석이 어려움          | 실패가 reachability, collision, clearance, human safety, perception uncertainty 중 무엇 때문인지 구분하기 어려움 |
| 현장 변경 시 재검증 생산성이 낮음    | 물체 배치나 작업공간이 변경될 때마다 테스트 케이스를 다시 작성해야 함                                                         |

---

### 평가 지표

| 구분         | 지표                                  | 측정 방법                                                   |
| ---------- | ----------------------------------- | ------------------------------------------------------- |
| 테스트 효율     | Failure Discovery Rate@K            | K개 테스트 실행 시 발견한 FAIL/BLOCKED 수                          |
| AI 탐색 효과   | Random 대비 실패 발견 증가율                 | Random Search와 Active Failure Search 비교                 |
| 실패 유형 커버리지 | Unique Failure Mode Coverage        | collision, clearance, unreachable, human risk 등 발견 유형 수 |
| 시뮬레이션 비용   | Simulation Budget Reduction         | 전체 후보 실행 대비 필요한 테스트 수 감소율                               |
| 경계 조건 탐색   | Critical Boundary Discovery         | robustness ≈ 0인 PASS/FAIL 경계 케이스 발견 여부                  |
| 최소 반례 탐색   | Minimum Perturbation Counterexample | 최소 장면 변화로 실패를 유발한 사례 수                                  |
| 안전성        | Safety Block Rate                   | human risk 조건을 BLOCKED로 판정한 비율                          |
| 설명성        | Failure Report Generation Rate      | 실패 케이스 중 원인·권고사항 생성 비율                                  |
| 3D 인식 품질   | 3D 위치 오차                            | 기준 좌표 대비 추정 좌표 오차                                       |

---

## 개선 계획

### 개선 방법

본 과제는 다음 방식으로 Pain Point를 개선한다.

1. **3D Vision 기반 작업공간 구조화**

   RGB-D 또는 시뮬레이션 카메라를 통해 작업공간의 3D 데이터를 획득하고, 목표 물체, 장애물, 목적지, 지지면, 작업자 위험 영역을 추출한다.

2. **3D Scene Graph 생성**

   객체의 위치, 크기, 역할, 객체 간 거리, 로봇 작업 반경, 장애물-목표물 관계, 경로 차단 가능성 등을 Scene Graph 형태로 구조화한다.

3. **장면 변형 파라미터 공간 정의**

   목표물 위치 이동, 장애물 접근, 경로 차단, human zone 삽입, 목적지 점유, occlusion 추가 등 테스트 가능한 장면 변형 공간을 정의한다.

4. **Active Failure Search 기반 테스트 자동 탐색**

   초기 테스트 실행 결과로 surrogate model을 학습하고, acquisition function을 통해 실패 가능성, 불확실성, 안전 중요도, 테스트 다양성을 고려하여 다음 테스트 장면을 능동적으로 제안한다.

5. **물리 시뮬레이션 기반 검증**

   선택된 테스트 장면을 PyBullet에서 실행하고, reachability, collision, clearance, human safety, destination availability 기준으로 PASS/FAIL/WARN/BLOCKED를 판정한다.

6. **실패 조건 및 경계 조건 리포트 생성**

   각 테스트 결과, robustness score, 실패 원인, 최소 반례, 개선 조치를 자동 정리하여 개발자 또는 운영자가 활용할 수 있는 검증 리포트를 생성한다.

---

### 개선 목표

| 항목           | 개선 목표                                                                            |
| ------------ | -------------------------------------------------------------------------------- |
| 테스트 후보 생성    | 하나의 3D Scene Graph에서 1,000개 이상 유효 mutation 후보 생성                                 |
| 최종 실행 테스트    | Active Failure Search 기반 round별 10개 내외 테스트 선택                                    |
| 실패 유형        | 5종 이상 판정: collision, clearance 부족, unreachable, destination occupied, human risk |
| 실패 발견 효율     | 동일 테스트 수 기준 Random Search 대비 FAIL/BLOCKED 발견 수 30% 이상 증가                         |
| 실패 유형 커버리지   | 5종 중 4종 이상 자동 발견                                                                 |
| 시뮬레이션 절감     | 전체 후보 전수 실행 대비 테스트 실행 수 70% 이상 절감                                                |
| 최소 반례        | 최소 perturbation counterexample 3건 이상 도출                                          |
| Safety Block | human zone 위험 조건 BLOCKED 판정율 90% 이상                                              |
| 리포트 자동화      | 실행된 테스트 100%에 대해 결과·원인·권고사항 자동 생성                                                |

---

## AI기술 활용

### 활용 계획

본 과제에서 AI는 단순히 LLM을 호출해 테스트 케이스를 작성하는 데 사용하지 않는다.
핵심 AI는 **Active Failure Search Engine**이다.

---

#### 1. 3D Vision 기반 객체·장면 인식

RGB-D 또는 시뮬레이션 카메라 입력으로부터 작업공간 내 객체를 검출하고, depth 정보를 결합해 3D 위치와 크기를 추정한다.

활용 기술:

```text
- Object Detection / Segmentation
- Depth 기반 3D 좌표 추정
- Point Cloud processing
- 3D bounding box estimation
- Support plane estimation

```

---

#### 2. 3D Scene Graph 기반 물리 feature 추출

Scene Graph에서 다음 feature를 추출한다.

```json
{
  "target_robot_distance": 0.62,
  "target_to_nearest_obstacle": 0.041,
  "path_min_clearance": 0.032,
  "reach_margin": 0.13,
  "obstacle_on_path": 1,
  "destination_occupied": 0,
  "human_zone_min_distance": 0.28,
  "unknown_region_overlap": 0,
  "occlusion_ratio": 0.12
}
```

---

#### 3. Surrogate Model 기반 Robustness 예측

AI 모델은 다음 함수를 근사한다.

```text
f(scene_graph_features, mutation_parameters) → robustness
```

또는:

```text
f(scene_graph_features, mutation_parameters) → failure_probability, failure_type
```

모델 후보:

```text
- Gaussian Process
- RandomForest / ExtraTrees ensemble
- XGBoost
- MLP ensemble
```

---

#### 4. Acquisition Function 기반 다음 테스트 선택

AI는 단순히 후보를 분류하지 않고, 다음에 실행할 테스트 장면을 제안한다.

```text
A(z) =
    실패 가능성
  + 예측 불확실성
  + 안전 중요도
  + 테스트 다양성
  - 중복도
  - 물리 유효성 위반 penalty
```

이를 통해 제한된 테스트 예산 안에서 더 많은 실패 조건을 탐색한다.

---

#### 5. LLM 활용 범위

LLM은 핵심 로직이 아니라 보조 기능으로 제한한다.

| 기능                        |   사용 여부 | 이유                        |
| ------------------------- | ------: | ------------------------- |
| 테스트 후보 직접 생성              | 사용하지 않음 | 물리 유효성 보장이 어려움            |
| collision/reachability 판정 | 사용하지 않음 | 시뮬레이터와 수치계산이 적합           |
| 자연어 작업 명령 → JSON 변환       |   선택 사용 | 사용자 편의 기능                 |
| 결과 리포트 문장화                |   선택 사용 | 설명 생성에 적합                 |
| 실패 유형 taxonomy 초안 작성      |   개발 보조 | 최종 로직은 rule/threshold로 고정 |

즉, 본 과제는 프롬프트 엔지니어링 과제가 아니라, **3D 물리 feature와 시뮬레이션 feedback을 이용한 능동 테스트 탐색 과제**이다.

---

### 최적화 계획

#### 1. 3D 위치 추정 품질 최적화

| 이슈            | 최적화 방법                         |
| ------------- | ------------------------------ |
| depth noise   | mask 내부 median depth 사용        |
| outlier point | statistical outlier removal 적용 |
| 객체 위치 흔들림     | temporal smoothing 적용          |
| 객체 크기 오차      | point cloud bounding box 보정    |
| 지지면 추정 오류     | table plane prior 또는 RANSAC 적용 |

---

#### 2. Mutation Space 품질 최적화

| 실패 유형                  | 생성 전략                                           |
| ---------------------- | ----------------------------------------------- |
| clearance 부족           | gripper 폭보다 약간 작은 간격으로 obstacle 배치              |
| reachability 실패        | max reach 근처와 바깥쪽에 target 배치                    |
| path collision         | robot-target path 주변에 obstacle 배치               |
| human risk             | planned path와 safety distance 이내에 human zone 삽입 |
| destination occupied   | tray 내부 또는 goal region에 obstacle 배치             |
| perception uncertainty | target 주변 occlusion 또는 unknown region 추가        |

---

#### 3. Active Failure Search 최적화

| 항목           | 최적화 방법                                               |
| ------------ | ---------------------------------------------------- |
| 초기 seed 품질   | baseline, boundary seed, Latin hypercube sampling 혼합 |
| surrogate 성능 | GP, RandomForest, XGBoost 비교                         |
| 탐색 균형        | exploitation과 exploration 가중치 조정                     |
| 실패 유형 다양성    | failure type coverage bonus 적용                       |
| 중복 방지        | 유사 mutation 간 redundancy penalty 적용                  |
| 안전 우선순위      | human risk 후보에 safety priority weight 적용             |

---

#### 4. Physical Oracle 최적화

| Oracle       | 최적화 방법                                                    |
| ------------ | --------------------------------------------------------- |
| Reachability | IK 성공 여부와 reach margin 동시 사용                              |
| Collision    | 실행 전 path sampling collision check 적용                     |
| Clearance    | target 주변 최소 거리와 gripper width 비교                         |
| Human Safety | planned path와 human zone 간 최소 거리 계산                       |
| Destination  | goal region occupancy check 적용                            |
| Perception   | unknown overlap, occlusion ratio, confidence threshold 사용 |

---

# 17. 최종 산출물

## 17.1 데모 앱

화면 구성:

```text

┌────────────────────┬────────────────────┐
│ RGB / Depth View    │ 3D Scene Graph View │
│ 객체, 장애물 표시     │ 좌표, 관계, 위험영역 │
├────────────────────┼────────────────────┤
│ PyBullet Simulation │ Active Search Table │
│ 로봇 행동 실행        │ 후보, score, 결과    │
├────────────────────┴────────────────────┤
│ Counterexample Report                    │
│ 실패 원인, robustness, 개선 권고           │
└─────────────────────────────────────────┘

```

---

## 17.2 소스코드 구조

```text
scene2test/
  app.py
  config/
    task_config.yaml
    robot_config.yaml
    thresholds.yaml
  src/
    scene_builder.py
    scene_graph.py
    mutation_space.py
    feature_extractor.py
    active_failure_search.py
    surrogate_model.py
    acquisition.py
    sim_runner.py
    physical_oracle.py
    reporter.py
  data/
    generated_scenes/
    search_logs/
    test_results/
  models/
    surrogate_model.pkl
  reports/
    final_test_report.md
```

---

## 17.3 결과표 예시

| Test ID | Scenario               | Acquisition Score | Result  | Robustness | Failure Type           |
| ------- | ---------------------- | ----------------: | ------- | ---------: | ---------------------- |
| T01     | baseline               |              0.21 | PASS    |      0.082 | -                      |
| T02     | obstacle target 4cm 근접 |              0.87 | FAIL    |     -0.019 | insufficient_clearance |
| T03     | target reach 경계 이동     |              0.79 | FAIL    |     -0.032 | unreachable            |
| T04     | human zone path 진입     |              0.94 | BLOCKED |     -0.041 | human_risk             |
| T05     | tray 점유                |              0.74 | FAIL    |     -0.026 | destination_occupied   |
| T06     | unknown region overlap |              0.68 | WARN    |     -0.011 | perception_uncertainty |

---

# 18. 최종 발표 메시지

발표에서는 다음 문장으로 과제의 핵심을 설명하면 좋다.

> 기존 Physical AI/로봇 자동화 테스트는 사람이 예상한 일부 조건만 수작업으로 검증하는 경우가 많다. 본 과제는 3D Vision으로 작업공간을 Scene Graph로 구조화하고, 장면 변형 가능 공간을 정의한 뒤, Active Failure Search를 통해 실패 가능성이 높은 테스트 장면을 능동적으로 찾아낸다. 선택된 테스트는 PyBullet 물리 시뮬레이션에서 실행되며, PASS/FAIL/WARN/BLOCKED와 실패 원인, 최소 반례, 개선 조치를 자동 리포트한다.

더 짧게는 다음과 같다.

> **로봇이 실제 환경에서 실패하기 전에, 3D 장면을 기반으로 AI가 실패 조건을 먼저 찾아내는 Physical AI 테스트 자동화 시스템**

---

# 19. 최종 정리

본 과제는 단순히 3D Vision을 붙인 로봇 데모가 아니다.
또한 LLM에게 테스트 케이스를 만들어 달라고 하는 프롬프트 기반 과제도 아니다.
최종 핵심은 다음이다.

> **3D Scene Graph 기반 Active Failure Search Engine**

이 엔진은 다음을 가능하게 한다.

```text
- 현재 작업공간을 3D Scene Graph로 구조화
- 변형 가능한 테스트 장면 공간 정의
- 물리 robustness score 계산
- 시뮬레이션 결과 기반 surrogate model 학습
- acquisition function으로 다음 테스트 장면 선택
- 실패 조건과 경계 조건 능동 탐색
- 최소 반례와 회귀 테스트셋 생성
- 개발·운영 검증 리포트 자동 생성
```

이렇게 정리하면 과제 평가 기준과도 잘 맞는다.

| 평가 관점      | 매칭 근거                                                                              |
| ---------- | ---------------------------------------------------------------------------------- |
| 과제 정의      | Physical AI/로봇 솔루션 검증 업무의 수작업 테스트 문제를 해결                                           |
| Pain Point | 테스트 생성 시간, 실패 조건 탐색, 실패 원인 분석, 재검증 생산성 문제 명확                                       |
| 평가 지표      | Failure Discovery Rate, Simulation Budget Reduction, Counterexample 수 등 정량화 가능     |
| 과제 완성도     | PyBullet 기반으로 1인 구현 가능한 end-to-end 데모 구성 가능                                        |
| 기술 활용도     | 3D Vision, Scene Graph, Active Failure Search, Surrogate Model, Physical Oracle 결합 |
| 제한사항 대응    | 단순 LLM 호출 아님, 단일 오픈소스 복붙 아님, 자체 테스트 탐색 엔진 구현                                       |

최종 과제명은 다음을 추천한다.

> **3D Scene Graph 기반 Active Failure Search를 활용한 Physical AI 행동 회귀 테스트 자동화 시스템**

최종 한 줄 설명은 다음과 같다.

> 제조·물류 로봇 자동화 환경에서 3D Vision으로 작업공간을 구조화하고, Active Failure Search를 통해 실패 가능성이 높은 장면 조건을 능동적으로 탐색하여 Physical AI 행동의 성공·실패·위험 요인을 자동 검증하는 개발·운영 생산성 향상 시스템.

[1]: https://arxiv.org/abs/2209.06735?utm_source=chatgpt.com "Falsification of Cyber-Physical Systems using Bayesian Optimization"
[2]: https://concept-graphs.github.io/?utm_source=chatgpt.com "ConceptGraphs: Open-Vocabulary 3D Scene Graphs for Perception and Planning"
[3]: https://scikit-learn.org/stable/modules/gaussian_process.html?utm_source=chatgpt.com "1.7. Gaussian Processes — scikit-learn 1.9.0 documentation"
[4]: https://github.com/bulletphysics/bullet3/blob/master/docs/pybullet_quickstart_guide/PyBulletQuickstartGuide.md.html?utm_source=chatgpt.com "bullet3/docs/pybullet_quickstart_guide/PyBulletQuickstartGuide.md.html at ... - GitHub"
[5]: https://www.open3d.org/docs/release/tutorial/geometry/pointcloud.html?utm_source=chatgpt.com "Point cloud - Open3D 0.19.0 documentation"
[6]: https://docs.ultralytics.com/usage/python?utm_source=chatgpt.com "Python Usage - Ultralytics Docs"
[7]: https://ai2thor.allenai.org/?utm_source=chatgpt.com "AI2-THOR"
[8]: https://aihabitat.org/habitat3/?utm_source=chatgpt.com "Habitat 3.0: A Co-Habitat for Humans, Avatars and Robots"
[9]: https://scenic-lang.org/?utm_source=chatgpt.com "The Scenic Programming Language"
[10]: https://arxiv.org/abs/2310.01361?utm_source=chatgpt.com "GenSim: Generating Robotic Simulation Tasks via Large Language Models"
[11]: https://arxiv.org/abs/2311.01455?utm_source=chatgpt.com "[2311.01455] RoboGen: Towards Unleashing Infinite Data for Automated Robot Learning ..."
