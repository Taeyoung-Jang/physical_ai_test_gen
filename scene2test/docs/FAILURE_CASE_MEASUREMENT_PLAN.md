# 실패 발견·행동 검증·회귀 자산화 구현 계획

2026-09-28 최신: [P3 유형·회귀 첫 구현](BEHAVIOR_TAXONOMY_AND_REGRESSION.md)을 반영했다.
종료 후 응답 usage 감사, opt-in 3개 행동-실패 연관 규칙, 고정 시도 예산의 실행 가능한 회귀 suite를 추가했다.
PASS/FAIL은 원본 목표 기준으로 유지한다. 나머지 3종은 미지원, coverage는 관측 하한만 보고하며,
신규 유료 회귀/탐색 성능이나 4/6 달성은 아직 검증하지 않았다. 아래 상태 설명은 각 작성 시점 기준이다.

2026-09-28 후속: [다중 장애물 17축 AFS](OBSTACLE_AFS.md)를 opt-in v3 도메인으로 연결했다.
고정 블록 2개의 위치·크기·높이·회전을 goal-agent 물리/관측·AFS·메모리에 반영했다.
비교 실험 완료는 개발의 선행 조건이 아니다. 범용 미로/방/terrain 적재, 유형 detector,
회귀 실행 runner는 아직 남아 있다. 로봇의 점프/조작 기술 개발과 AFS 개발은 분리한다.

2026-09-28 AFS 후속: [가설 중심 선택 v2](AFS_SEARCH_V2.md)로 후반 행동 근거 누락,
정확한 접촉 횟수 기반 중복 서명, novelty-only 선택을 보완했다. 관측 경계/행동 중복/비용
보조 지표를 추가했으며 로봇 개선을 선행 조건으로 삼지 않는다. 새 live 비교는 아직 없다.

2026-09-28 후속: P3의 첫 기하 확장으로 [통로 폭·배치 AFS](CORRIDOR_AFS.md)를 구현했다.
v1 3축과 구분된 v2 5축 domain이며, CPU/합성 검증 단계다. 실제 성공 대조·유형 detector·
회귀 실행은 아직 남아 있다. 아래의 초기 구현 범위와 향후 계획을 이 갱신과 구분한다.

2026-09-27 UTC 갱신. 상태: **P0 측정기, P1 시간별 행동 근거·failure memory,
P2 로컬 3축 AFS/Random campaign 첫 구현 반영; 유형 detector/회귀 실행은 미구현**.
구현 범위와 실행법은 [실패 발견 측정기](FAILURE_DISCOVERY_MEASURES.md)와
[행동 시간선·failure memory](BEHAVIOR_FAILURE_MEMORY.md)를 참고한다.
P2 실행·예산·재개 범위는 [행동 AFS 캠페인](BEHAVIOR_AFS_CAMPAIGN.md)을 참고한다.
실제 유료/GPU pilot 및 core/media manifest 분리는 아직 검증/구현하지 않았다.

기준 문서: [Failure_Case_Goal.md](../../.blueprint/Failure_Case_Goal.md).
평가 의미는 사용자의 최신 원칙과 [목표 중심 평가 구현](GOAL_OUTCOME_AFS_IMPLEMENTATION.md)을 따른다.
이번 우선순위는 로봇 기술 개발이 아니라 **AFS의 탐색 효과 측정**과 **행동 근거가 있는 재사용 가능한 실패 사례**다.

## 1. 완료 시 얻어야 할 것

동일한 로봇·목표·관측 조건·장면 공간·실행 예산에서 다음 질문에 답한다.

1. AFS가 유효 테스트 중 목표 미달성 사례를 얼마나 발견했는가? 목표 **30% 이상**.
2. 같은 예산의 Random보다 얼마나 더 발견했는가? 목표 **상대 20% 이상 향상**.
3. 사전 정의한 6개 유형 중 몇 종류를 근거와 함께 발견했는가? 목표 **4종 이상**.
4. 무엇을 관찰해 다음 실험을 골랐고, 어떤 조건에서 성공/실패가 바뀌었는가?
5. 로봇 버전이 바뀌었을 때 같은 장면으로 재현·회귀 검증할 수 있는가?

수치 목표는 연구 가설/달성 목표이지 구현 완료만으로 보장되는 성능이 아니다.
계산기의 정상 작동, 실제 실험 완료, 수치 목표 달성을 별도로 보고한다.

## 2. 실패 판정과 관측을 분리한다

세 층을 독립적으로 저장한다.

| 층 | 의미 | 예 |
|---|---|---|
| Task outcome | 최초 목표의 최종 달성 여부 | PASS / FAIL / INCONCLUSIVE |
| Behavior measurements/events | 그 과정에서 실제 관측한 행동·물리량 | 접촉, 물체 이동량, 경로 재계획, 낙상 자세, 회복 |
| Failure attribution | 목표 미달성과 관련된 유형 및 근거 | obstacle_interference, 증거 시각, 판정 규칙 버전, 불확실성 |

- 목표를 달성하면 접촉·넘어짐·밀기 실패가 있었어도 기본 `goal_outcome_v1`에서는 PASS다.
- 목표 미달 상태로 사전 고정된 호출/명시적 시간 예산 소진 또는 로봇의 stop이면 FAIL이다.
- API·스키마·수치 오류·외부 중단·필수 결과 누락은 INCONCLUSIVE/수집 불완전으로 구분한다.
- 옛 `FORBIDDEN_CONTACT`/`BLOCKED` 조기 종료를 새 목표 FAIL로 재분류하지 않는다.
- 평가기는 경유점, 밀기 방향, 객체 처리 순서, 로봇 명령을 지정하지 않는다.
- 잘못된 subgoal 순서는 **최초 task contract가 순서를 요구할 때만** 검사한다.
  로봇이 스스로 바꾼 계획의 순서를 평가자가 임의로 오답 처리하지 않는다.
- 경로 이탈은 로봇 자신의 당시 계획에 대한 진단값이다. 참조 경로 준수를 새 성공 조건으로 넣지 않는다.
- 안전 이벤트는 목표 달성 여부와 별도로 계속 보고한다. 안전 제약까지 성공 조건으로 삼는
  벤치마크가 필요하면 실행 전에 별도 task/profile을 선언하고 기존 결과와 섞지 않는다.

현재 목표는 base XY `[7, 0]`, 반경 0.25m 미만에서 1초 유지다. 기립 상태나 상자의 최종 위치는
추가 목표가 아니다. 이 계약의 변경은 AFS의 장면 변형이 아니라 새 평가 조건이다.

## 3. 현재 코드에서 재사용할 것과 부족한 것

| 영역 | 현재 근거 | 계획 |
|---|---|---|
| 로봇 실행·목표 판정 | `robot_vlm/goal_runner.py`, `task_outcome.py` | 현재 계약 유지, 결과를 공통 측정 레코드로 읽기 |
| 행동 증거 | states/contacts/events/decisions/skill/API 로그, protocol, manifest, MP4 | 시계열 measure와 증거 구간 추출 |
| 행동 기반 AFS | `llm_afs/behavior.py`, `behavior_request.py` | 기존 LLM 가설·완화·경계·대안 실험을 폐루프에 연결 |
| 방법 인터페이스 | `failure_client/methods/base.py`의 propose/observe/checkpoint | Random 및 행동 AFS 어댑터에 재사용 |
| 저장·실패 집계·내보내기 | `failure_client/archive`, `reporting`, `storage` | 유효 rollout 집계, 사건/회귀 자산 필드 추가 |
| 실행 복구 | `failure_client/experiments` | 가능한 상태 저장/재개 기능 재사용; 로컬 runner용 얇은 실행 어댑터 |
| 기존 비교 파일럿 | `procedural_world/search.py` | 유효 예산/추적 설계 참고; 다른 로봇·평가 조건의 수치는 혼합하지 않음 |
| Panda 행동 검증 | `lam_guided/types.py`, `policy_oracle.py`, `failure_memory.py` | 구조 참고 및 별도 importer; Panda 전용 grasp/IK 판정을 G1에 이식하지 않음 |

중요한 제한:

- 현재 goal-agent가 받는 `clear-path-fixture-v1`은 **상자 질량·상자 마찰·바닥 마찰** 중심의 고정 기하다.
  planner footprint/clearance 변경은 AFS에 허용되지 않는다.
- `llm_afs/expanded.py`에 다양한 지형 생성 축이 있다는 사실은 goal-agent가 그 지형을 실행한다는 뜻이 아니다.
- 기존 일반 client orchestrator의 주요 중단 기준은 candidate 수다. 새 비교에서는 유효 실행 수를
  별도로 관리해야 하므로 기존 orchestrator를 그대로 호출하면 공정 비교가 완성되지 않는다.
- 기존 HTTP navigation 서버에 goal-agent 실행 계약이 이미 있는 것으로 가정하지 않는다.
  서버 API 확장이나 모든 경로 통합을 이번 측정 작업의 선행 조건으로 만들지 않는다.
- 현재 로봇은 GPT 시각/계획 + 내부 계획기 + CUDA 보행/제한적 push 조합이다.
  일반적인 end-to-end VLA의 행동 검증을 완료했다고 표현하지 않는다.

## 4. 세 핵심 지표의 계산 계약

`B`: method·seed별 사전 고정된 유효 rollout 예산.
`N`: 증거 검증을 통과하고 동일 평가 계약에서 PASS 또는 FAIL로 완료된 rollout 수.
`F`: 그중 FAIL 수. 생성한 JSON 수, 후보 수, 접촉 횟수가 아니다.

| 지표 | 계산 | 목표 |
|---|---|---|
| Failure Discovery Rate | `FDR = F / N` | `FDR_AFS >= 0.30` |
| Failure Discovery Gain | `Gain = (FDR_AFS - FDR_Random) / FDR_Random` | `Gain >= 0.20` |
| Failure Diversity Coverage | `Coverage = 증거가 있는 발견 유형 수 / 6` | `발견 유형 수 >= 4` |

예: 양쪽 100회 유효 테스트에서 Random 25회 실패, AFS 30회 실패이면
FDR은 각각 25%, 30%, Gain은 **20%**, 절대 차이는 **5%p**다. 20%p 향상이 아니다.

### 분모·중복·예외

- `N=0`은 0%가 아니라 계산 불가다. Random 실패 0회이면 Gain은 `null / baseline_zero`로 내보내고
  절대 실패 수 차이와 %p 차이만 보고한다. 무한대나 임의 epsilon으로 목표 달성을 주장하지 않는다.
- 같은 run을 다른 경로나 manifest 복사본으로 다시 입력해도 한 번만 센다. 별도 실행 반복은 별도 rollout이다.
- cold start, 성공 쪽 probe, 경계 확인, 재현 반복도 실행했다면 모두 `B`를 소비한다.
  실패만 고르거나 확인 반복을 무료로 추가해 AFS 성능을 높이지 않는다.
- 고유 장면 수·고유 실패 장면 수·반복 실패 수를 반드시 함께 보고한다.
  동일 장면 반복으로 FDR이 높아지는 현상을 숨기지 않으며, 신규 탐색/확인 반복별 보조 집계도 제공한다.
- invalid scene, INCONCLUSIVE, 미완료 결과는 `N`에 넣지 않되 모든 시도와 원인·비용을 남긴다.
  최대 시도/인프라 오류율 제한에 걸리면 campaign은 INCOMPLETE이지 성공적인 비교 완료가 아니다.
- 기존 GIF 최종화 중단처럼 필수 결과/manifest가 없는 기록은 영상을 보고 공식 FAIL로 복원하지 않는다.
  진단 근거로 보존하고 새 완결 실행을 확보한다.
- `valid_execution=true` 또는 `success=false` 하나만 읽어서 유효 FAIL로 세지 않는다.

### 예산과 공정성

- 같은 장면 domain, layout 분포, 초기 조건, 목표, 로봇 코드/프롬프트/모델·가중치,
  관측 정보, 기술 사용 권한, 물리 설정, 평가 규칙과 episode 예산을 고정한다.
- Random은 공통 전체 domain에서 사전 정의한 분포로 뽑는다. AFS가 좁힌 공간 안에서만
  Random을 뽑거나, 두 방법에 다른 장면 필터를 쓰지 않는다.
- 공통 cold-start 자료를 쓰면 두 방법의 `B`에서 같은 비용으로 계산한다.
  외부 warm history를 쓰는 실험은 그 크기·수집 비용을 별도 공개하는 다른 비교 조건이다.
- 비교 seed 목록을 사전에 정하고 결과가 좋은 seed만 선택하지 않는다. scene/search seed와
  robot 반복 seed를 구분한다. 같은 seed라도 외부 모델 응답의 동일성을 보장하지 않는다.
- 로봇의 모델 응답 지연 중에도 시뮬레이션 시간이 진행되는 현재 조건을 명시한다.
  method 실행 순서를 교차/무작위화하고 지연을 보고한다. 평가 중 지연 처리 방식을 바꾸지 않는다.
- 호출 예산과 HTTP deadline은 고정하되 **기본 120초 상한을 복구하지 않는다**.
  운영상 watchdog 중단은 선언한 task budget과 구별하고, 외부 취소를 로봇 FAIL로 세지 않는다.
- 유효 예산뿐 아니라 전체 시도, 로봇 API 호출/토큰, AFS API 호출/토큰, wall/sim/추론 시간을 보고한다.
  AFS의 추가 추론 비용을 제외한 채 비용 효율까지 우수하다고 주장하지 않는다.

### 여러 seed의 보고

- 각 seed의 `FDR@B`, `Gain@B`, `families@B`와 평균/분산·전체 합산값을 제공한다.
- 전체 Gain은 전체 실패/전체 유효 수로 얻은 비율끼리 비교한다. seed별 Gain의 단순 평균과 구분한다.
- 적응적 연속 샘플을 독립 시행으로 간주하지 않는다. 충분한 독립 campaign seed가 있으면
  paired seed 단위 bootstrap 등의 불확실성 추정을 적용하고 방법/seed 수를 기록한다.
- 소수 seed의 점추정이 목표를 넘은 것과 일반화된 우월성 증거를 구분한다.
  seed 하나의 실행이나 범위가 불안정한 CI로 통계적 우월성을 선언하지 않는다.
- 여러 seed를 합친 유형 합집합은 총 `K*B` 테스트 결과다. 그것을 단일 `B`에서 4종 발견한 것처럼 쓰지 않는다.

## 5. 6종 taxonomy와 실제 계측

이 표는 구현할 규칙의 출발점이다. 임계값·시간창·관측 출처를 버전된 규칙으로 확정하고,
양성/음성 fixture로 검증한 뒤 공식 집계에 사용한다. 모델의 설명문만으로 유형을 확정하지 않는다.

| 유형 | 필요한 measure/증거 | 과대 판정 방지 |
|---|---|---|
| 충돌 | robot/object geom 접촉 구간, normal force/impulse, 당시 동작과 목표 진척 저하 | 발–바닥 지지나 의도한 물체 접촉만으로 실패 아님; unrelated 접촉+예산 소진을 원인으로 단정하지 않음 |
| 도달 불가 | 명시된 robot/task 공간 제약, 목표 영역 접근 조건, 독립 검증 가능한 제약 위반 근거 | planner의 `no_path`나 IK 1회 실패는 불가능 증명이 아님; 근거 부족 시 UNKNOWN |
| 장애물 간섭 | 진로의 물체 배치, 정체 구간, 재계획·조작 시도, 물체/로봇 변위 및 남은 목표 거리 | 단순 접촉 유형과 구별; 제거/완화 대조가 없다면 원인 확정 대신 근거 수준 표시 |
| 목표 위치 점유 | task goal 영역과 물체의 기하 점유, 점유 시간, 이동 후 잔여 점유와 최종 결과 | 초기 점유만으로 실패 아님; 치우고 도착하면 PASS |
| 작업자 안전 위험 | 사람/안전 영역 geometry, 로봇과의 최소 거리, 위반 지속 시간·시점 | 사람 없는 장면은 N/A; 목표 달성한 위험 행동은 별도 안전 이벤트이며 goal FAIL 아님 |
| 인식 오류 | 로봇에게 실제 제공된 관측, 시각/객체에 관한 구조화된 판단, 평가 전용 GT의 불일치 | 잘못된 움직임만 보고 인식 오류로 추정하지 않음; 가려진 정답을 GT 지도/프롬프트로 주는 조건도 공개 |

분류 레코드에는 `rule_version`, `evidence_refs`, 시간 구간, 관측 신뢰 수준과
`causal_status`를 둔다. `candidate.expected_family`나 GPT의 가설은 예측이지 정답 라벨이 아니다.

공식 diversity 집계는 **실제 목표 FAIL + 검증된 유형 판정 규칙 + 해당 근거**가 있는 사례에 한한다.
각 실패 장면은 보수적으로 하나의 `primary_family` 또는 UNKNOWN을 갖고, 다른 관련 사건은
`secondary_events`로 남긴다. 한 장면을 여러 이름으로 부르면서 4종 달성을 만들지 않는다.
겹치는 충돌/간섭/점유 판정의 구별 기준을 먼저 고정하며, 모호하면 UNKNOWN으로 남긴다.
유형 판정 근거 확보와 물리적 인과 확정은 별도다. 후자는 반복·대조 실험 없이는 주장하지 않는다.

지원하지 않는 센서/유형은 `UNSUPPORTED`, 해당 없는 조건은 `N/A`, 증거 부족은 `UNKNOWN`이다.
이를 0이나 안전으로 대체하지 않는다. 공식 분모는 계속 6이며, 지원 가능한 유형 수를 별도 표시한다.
목표 달성한 안전 위반 등은 보조 event coverage로 보여주되 failure coverage와 섞지 않는다.

### 물리 유효성과 과제 수행 가능성을 구분

NaN, 모델 로딩 실패, 비정상 초기 겹침 등은 실행 유효성 문제다. 반면 길이 막혔거나 목표가 점유된
장면은 연구 대상일 수 있다. 정적 2D 경로가 끊겼다는 이유만으로 조작 가능한 장면을 자동 제외하지 않는다.

`admissibility`와 `feasibility_evidence`를 별도 저장한다. 수행 불가능하다고 검증된 장면을
벤치마크에 포함할지, 수행 가능/미확인 조건과 어떻게 층화할지 domain freeze 전에 정한다.
불가능한 장면만 늘려 로봇의 취약성이나 AFS의 효율을 입증했다고 주장하지 않는다.

## 6. RolloutTrace → measure → failure memory

Panda 전용 `RolloutTrace`를 G1 값으로 억지로 채우지 않고 공통 episode/증거 레코드와 backend별
trace adapter를 둔다. 기존 raw 로그는 수정하지 않고 파생 측정값을 별도 저장한다.

### 공통 레코드

- 식별: campaign/method/seed/candidate/run/repeat ID, 실제 실행 ID와 원본 artifact hash.
- 비교 조건: robot/task/observation/budget/domain/evaluator/taxonomy/measure 버전과 hash.
- 결과: task outcome, 종료 주체·이유, 유효/제외 이유, 원본 증거의 완전성.
- 측정: 값·단위·샘플 간격·집계 구간·측정 출처·지원 상태. 빠진 값은 null + 이유.
- 귀속: primary family, 행동 사건, 증거 참조, 가설/관측/대조 확인 여부.
- 비용: 후보 생성/검증 수, 재시도, 로봇/AFS API, 토큰, 시간. 비용 단가가 없으면 금액을 지어내지 않음.

### 첫 계측 항목

1. goal distance의 초기/최소/최종 값, 진척, goal dwell, 실제 이동거리와 정체 구간.
2. 선택 행동과 실행 결과의 시간선, 재계획·기술 시도/중단/실패·후속 회복 결과.
3. 접촉 구간/최대 힘/충격량, 물체 변위, base 높이·자세 추이와 낙상/직립 복귀 사건.
4. 확보 가능한 geometry 기반 clearance와 goal occupancy. base 원형 clearance와 전신 clearance는 구별.
5. 로봇 자신의 당시 계획에 대한 tracking 오차 및 계획 변경 시점. 경로 없는 구간은 N/A.
6. 해당 task/backend가 지원할 때 객체 선택, 필수 subgoal partial order, human distance/temporal safety.

base tilt는 안정성 여유의 대용 진단값일 뿐이다. 미끄럼, near-fall, 회복 능력을 측정했다고
부르려면 접선 상대속도/지지·동역학 지표 등 필요한 신호와 정의를 별도로 구현해야 한다.
현재 contact 기록은 robot/world 중심이므로 box–floor 등 물체–물체 접촉은 추가 계측이 필요하다.
첫 계측은 수동 기록/사후 분석이며 로봇 프롬프트나 행동에 새 피드백을 몰래 추가하지 않는다.

### 회귀 자산

case마다 장면 및 SceneGraph/XML/지도 revision, 실제 robot/task 조건, 원본 trace/MP4 참조,
실행 설정, 결과/유형 근거, 반복 PASS/FAIL 횟수, 경계 bracket, 재현 명령과 가설적 개선 권고를 저장한다.
runtime 경로 링크만 있는 목록이 아니라 해시 검증 가능한 필수 자산 bundle/의존성 목록을 만든다.
export 시 비밀키·만료 URL·인증 정보는 제외한다.

경계는 비교 가능한 성공/실패 양쪽의 **관측 bracket**부터 저장한다. 축의 단위·정규화 거리·
반복 수·허용 오차·탐색 예산을 기록한다. 다변량 최소 perturbation이나 단조성의 증명이라고 부르지 않는다.
반복 결과가 섞이면 단일 경계 대신 경험적 성공/실패 횟수와 불확실성을 보존한다.

회귀 suite는 정상 대조, 성공/실패 경계 양쪽, 서로 다른 실패 사례로 구성한다.
비교는 PASS→FAIL(회귀), FAIL→PASS(개선), 유지, INCONCLUSIVE를 구별한다.
새 로봇 버전 비교는 의도적으로 robot hash가 다른 별도 모드다. AFS 경계 계산의 동일 조건 검사를
느슨하게 하지 않고, scene/task/evaluator/budget을 고정한 version comparison으로 처리한다.
보관된 실패에서 만든 회귀셋을 곧바로 독립 AFS 성능평가셋으로 재사용하지 않는다.

## 7. 행동 기반 AFS 폐루프

```text
고정된 장면 공간 + task/robot 계약
    → 공통 초기 테스트
    → 실제 rollout / 목표 판정 / 행동 계측
    → failure memory와 미확인 가설 갱신
    → 다음 장면 선택 → 실제 rollout ...
    → 동일 B의 Random 비교 / 경계·회귀 자산 / 보고서
```

LLM-first 방향을 유지한다. 기존 proposal 생성에 측정 근거·실패 중복·미탐색 유형·반복 결과를
추가하고 host가 domain/condition/evidence를 검증한다. LLM의 자신감 수치를 학습된 확률이나
교정된 불확실성으로 취급하지 않는다. 반복 결과의 혼합, 주변 표본 부족, 가설 간 충돌 등
불확실성의 출처를 명시한 탐색 휴리스틱부터 사용한다. ExtraTrees 전환은 이번 필수 작업이 아니다.

사전에 고정하는 탐색 전략은 다음을 함께 갖는다.

- 실패 발견: 실제 근거가 있는 취약 조건의 새 장면을 선택.
- 성공 쪽 탐색: 전부 실패하면 질량 완화 등 반대 방향도 조사. 가벼우면 무조건 쉬운 것은 아님.
- 경계 탐색: 동일 조건에서 성공/실패 양쪽이 확보된 경우 사이를 확인.
- 대안 가설: 질량 설명 외에 마찰·회전 공간·접근 여유 등 지원되는 환경 축으로 대조.
- 다양성/독립 탐색: 미탐색 영역·유형과 무작위 탐색을 유지.
- 재현 확인: 동일 조건 반복으로 우연한 모델 행동과 재현 가능한 현상을 구분.

전략 비율·중복 거리·cooldown·확인 반복 수는 개발 seed에서 정한 뒤 평가 전에 freeze한다.
반복 실패를 더 심하게 만드는 것만으로 높은 FDR을 얻지 않도록 고유 실패, coverage와 경계 발견도 보고한다.
동일 축/동일 행동 근방의 중복 억제는 하되 축 전체를 성급하게 금지하지 않는다.
상자 질량 단독, 마찰 단독 및 필요한 교차 대조를 남겨 근거 없는 인과 설명을 줄인다.

LLM 오류나 proposal 거절도 원인·비용을 저장한다. Random fallback을 쓰려면 사전에
`fallback_policy`를 선언하고 실제 사용 비율을 보고한다. 조용히 대체하고 순수 AFS로 표시하지 않는다.

자동 campaign은 후보/실행/관측 반영 상태를 durable ledger로 관리한다.
중단 후 완료 실행이나 유료 요청을 맹목적으로 다시 보내지 않는다. 결과를 확인할 수 없는 실행은
ambiguous/incomplete로 보존하고 새 attempt를 만들 때 비용과 중복 위험을 기록한다.
핵심 목표 결과는 미디어 보고서보다 먼저 내구성 있게 저장하는 방향으로 최종화를 정비한다.
MP4를 스트리밍 저장하고 **GIF는 계속 비활성화**한다. 버전된 core/media manifest로 미디어 실패와
평가 근거 실패를 구분하며, 기존 manifest 검증을 무조건 완화하지 않는다.

## 8. 4/6 유형 평가에 필요한 최소 장면 확장

현재 3축 고정 상자 장면만으로 4/6 달성을 약속할 수 없다. 먼저 그 공간에서 FDR/Gain의
측정·비교 경로를 완성하고, diversity에는 현재 지원 범위와 미측정 이유를 표시한다.

다음에는 goal-agent backend가 실제로 읽는 versioned scene contract를 확장한다.
우선 장애물 위치·크기·통로 폭·배치·목표 영역 점유 등 기하 축을 연결한다.
기존 procedural generator를 재사용하되 SceneGraph·지도·MuJoCo XML·로봇에게 보이는 정보의
객체 ID/좌표/revision 일치와 실제 물리 반영을 테스트한다. task goal과 robot 조건은 AFS가 바꾸지 않는다.
고정 3축 domain 실험과 확장 domain 실험의 수치는 별도로 낸다.

충돌/간섭/점유의 검출부터 검증하고, 도달 불가 유형은 독립적인 제약 근거를 확보할 수 있을 때 추가한다.
작업자/인식 유형은 사람 geometry·관측/판단 기록과 명확한 평가 규칙이 준비된 다음 포함한다.
초기 목표는 검증된 최소 4종을 지원하는 것이며 비슷한 현상을 이름만 바꿔 4종으로 만들지 않는다.
현재 GT 전체 지도를 제공하는 로봇 조건에서 인식 난이도는 제한될 수 있다.
관측 제공 범위를 바꾸는 인식 실험은 별도 robot-observation 조건으로 고정해 비교한다.

범위 제외: 새 grasp/jump 기술 훈련, 일반 SLAM/실사 segmentation 구축, 레거시 서버의 대규모 재설계,
Panda/G1 결과 합산, 범용 VLA 성능 주장. 필요한 계측/장면 연결만 현재 작업에 포함한다.

## 9. 구현 순서와 완료 기준

| 단계 | 작업 | 완료 기준 |
|---|---|---|
| P0 — 측정 계약/계산기 | episode 정규화·증거 검증, FDR/Gain/Coverage, 분모/예외·비용 | 오프라인 fixture에서 수작업 정답과 일치; 원본을 바꾸지 않고 JSON/CSV/HTML 출력 |
| P1 — 행동 계측/메모리 | trace adapter, 시계열 measure, 유형 evidence, 경계/회귀 case export | 한 사례의 목표 판정→행동→유형 근거→MP4 구간→재현 조건을 추적 가능; unsupported 명시 |
| P2 — AFS/Random 폐루프 | 로컬 실행 adapter, 유효 B, LLM propose/observe, checkpoint/resume | 같은 domain/robot/seed/B로 양쪽 실행; 중단 재개 중복 집계 방지; 반복 비용 포함 |
| P3 — 유형 범위/회귀 실행 | 필요한 기하·관측 확장, taxonomy 양성/음성 검증, regression suite runner | 최소 4종을 실제로 평가할 수 있는 조건 확보; 목표-only 규칙 유지; 회귀/개선 구분 |
| P4 — 동결 비교 평가 | 개발용과 분리된 seed에서 반복 비교, coverage/비용/불확실성 보고 | 30%/20%/4종 각각 충족·미충족·증거 부족을 보고; 모든 실행 근거 보존 |

P0/P1의 기본 구조는 6종을 수용하되 detector 완성 전 값을 만들어 넣지 않는다.
P2의 작은 3축 pilot과 P3의 확장 실험을 구분하며, P4는 지원 범위와 검출 규칙 검증이 끝난 뒤 시작한다.
처음에는 mock/CPU fixture와 보관 자료를 이용한다. 실제 유료/GPU 예산은 campaign config에 명시하고
사용자가 실행 범위를 확인한 뒤 live 비교를 수행한다. 이번 계획 수립에서는 live 실행하지 않는다.

### 구현 위치와 남은 제안

첫 구현에 `research_records.py`, `goal_run_reader.py`, `discovery_metrics.py`,
`discovery_report.py`, `tools/measure_failure_discovery.py`가 추가되었다.
P1 첫 구현에 `behavior_measures.py`, `regression_cases.py`, `behavior_report.py`와
측정 CLI의 `--with-memory`/`--bundle-video` 옵션이 추가되었다.
phase/contact/fall/action 구간, 감사된 상자 변위, 성공/실패/혼합 반복, 단일 축 관측 bracket과
선택 증거 bundle을 지원한다. 유형 귀속은 UNKNOWN이며 자동 실행·외부 자원 재현 검증은 하지 않는다.
P2 첫 구현에 `research_campaign.py`, `research_protocol.py`, `local_goal_adapter.py`,
`storage/research_store.py`, `methods/behavior_feedback.py`, `tools/run_afs_benchmark.py`가 추가되었다.
P0/P1·기존 transaction/observation 계약을 재사용하는 로컬 adapter이며 HTTP method registry plugin은 아니다.
동일 유효 예산/자기 seed의 행동 피드백/중단 재개를 합성 기록으로 검증했다. 실제 비교 성능은 미검증이다.

- `failure_client/evaluation/research_records.py`: backend 독립 episode·측정·귀속 계약.
- `failure_client/evaluation/behavior_measures.py`: 단위·시간창을 가진 행동 측정. taxonomy 규칙은 후속 범위.
- `failure_client/reporting/discovery_metrics.py`: 순수 집계 함수, 예산별 curve와 비교 상태.
- `failure_client/archive/regression_cases.py`: 증거/장면 bundle, 반복·bracket·회귀 manifest.
- `failure_client/experiments/research_campaign.py`: 기존 저장/복구 부품을 쓰는 local-runner 경계.
- `failure_client/methods/` 아래 behavior-AFS adapter: 기존 인터페이스 활용; registry/backend 호환은 명시적으로 구현.
- `tools/measure_failure_discovery.py`, `tools/run_afs_benchmark.py`, `tools/run_failure_regression.py`:
  각각 읽기/집계, 실행 비교, 회귀 검증용 CLI. **현재 측정과 로컬 캠페인 CLI가 구현됐으며 회귀 CLI는 계획이다**.

기존 protocol의 version/consumer를 깨지 않도록 opt-in 모듈과 adapter부터 넣는다.
Panda-only trace 필드를 G1의 실제 측정값처럼 채우거나 기존 archive를 재분류하지 않는다.

## 10. 필수 테스트와 보고서

P0부터 자동 테스트에 고정할 사례:

1. 양쪽 100회 중 30/25 실패 → 30%/25%, Gain 20%, 차이 5%p.
2. 0회, Random 0실패, 모두 PASS/모두 FAIL, 음수 Gain, 예산 미완료.
3. 복제 run 중복 제거와 실제 반복의 구별; cold-start/확인 반복의 예산 차감.
4. API/OOM/필수 파일 누락·손상/서로 다른 계약/legacy 조기 종료 제외 및 원인 공개.
5. 접촉·낙상 이후 목표 달성은 PASS, 진단 이벤트만으로 유형 coverage를 늘리지 않음.
6. goal FAIL이어도 원인 근거 없으면 UNKNOWN; unsupported 값을 0으로 채우지 않음.
7. 4개의 적격 primary family → 4/6; 한 장면의 여러 사건/후보 가설만으로 4종을 만들지 않음.
8. seed별 B coverage와 전체 seed 합집합 구별; 동일 run의 불일치 결과는 오류.
9. 비교 domain/robot/budget mismatch 거부; 의도적인 robot-version 회귀 비교는 별도 계약.
10. checkpoint 재개, 실행은 끝났으나 결과 수집이 중단된 경우, MP4 최종화 실패의 상태 분리.

기본 산출물은 `/workspace/g1_failure/runtime/afs_benchmark/<campaign_id>/` 아래 둔다.
`protocol.json`, ledger, episode/measure records, `metrics.json`, `metrics.csv`, `report.html`,
failure/regression manifest 및 원본 실행 링크를 제공한다. 대용량 raw 로그·MP4는 중복 저장하지 않되
회귀 export는 필요한 자산을 이동 가능한 형태로 고정한다.

보고서는 다음을 한 화면에서 구분한다.

- 목표 30%/20%/4종 대비 관측값과 판정 근거, 비교 가능 여부.
- 유효 테스트 수에 따른 누적 실패 수·고유 실패 수·유형 coverage 곡선.
- 6종 × 근거/지원 여부 표, 행동 시간선, 대표 MP4와 해당 시각.
- 실패/성공 경계, 반복 결과, 회귀/개선 내역.
- 무효·미완료·제외 건수, 로봇/AFS 호출·토큰·시간, 전체 실행 목록.

**P0/P1 및 3축 P2 로컬 캠페인의 첫 구현을 반영했다.** 실제 live pilot, 추가 계측/유형 detector,
core/media 최종화 개선과 회귀 실행은 남아 있다. 계획의 모든 계측·판정기가 구현된 것은 아니다.
