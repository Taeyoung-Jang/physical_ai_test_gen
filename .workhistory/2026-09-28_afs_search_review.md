# AFS 우선 개선 검토 — 로봇 조건을 고정하고 탐색 품질 개선

2026-09-28 UTC. 사용자 요청: 로봇 개선보다 AFS 관점의 개선 항목 검토.
이번에는 코드/설정/실험 결과를 수정하거나 유료 실행하지 않았다. 검토 내용만 기록한다.

## 범위와 판단

로봇의 실패는 AFS가 관측할 대상이다. 로봇 기술 개발을 AFS 개선의 선행 조건으로 삼지 않는다.
목표/로봇 모델/프롬프트/실행기/예산을 고정하고, AFS의 증거 선택·실험 선택·중복 억제·
관측 경계 검증을 개선한다. 성공 대조를 찾는 작업도 장면 탐색의 일부다.
정상 실행의 목표 미달은 FAIL로 유지하며, 성공을 얻으려고 판정 기준을 바꾸지 않는다.

읽은 구현: `failure_client/methods/behavior_feedback.py`,
`failure_client/experiments/research_campaign.py`, `llm_afs/behavior.py`,
`llm_afs/behavior_request.py`, `failure_client/evaluation/behavior_measures.py`,
`failure_client/archive/regression_cases.py`, `failure_client/reporting/discovery_metrics.py`,
`clear_path/scene_space.py`. 기준은 `.blueprint/Failure_Case_Goal.md`와 측정 계획이다.

## 1. 재현한 문제: 중요 행동이 AFS 입력에서 누락됨 — 최우선

대상 archive: `/workspace/g1_failure/runtime/robot_goal_agent/20260928T093634_165692Z`.
`read_goal_run(method="unassigned")` → `build_failure_memory` →
`feedback_context(history_limit=8, remaining=4, scene_schema="clear-path-corridor-v2")`를
읽기 전용으로 호출했다. 실제 캠페인에 편입하거나 AFS API를 호출하지 않았다.

- 전체 행동 구간: phase21, contact2102, action_window10.
- AFS 전달 전에 발–바닥 지지 접촉을 제외하면31개 구간이다.
- `intervals[:12]`가 시간순 앞12개만 선택한다.
- 실제 선택 결과: phase8 + action_window4. 행동은 observation_version0–3만 포함된다.
- 후반 observation_version6/9의 `blocked_endpoint`, version7의 후퇴·측방 회복 행동은
  전체 메모리에 있지만 개별 행동 근거로 LLM 입력에 전달되지 않는다.
- 전체 행동 횟수/최종 거리 등 집계는 남으므로 모든 후반 정보가 사라지는 것은 아니다.
  그러나 실패 과정 해석에 필요한 상태 전환과 회복 맥락을 잃는다.

제안: 단순 앞부분 자르기를 버리고 전체 episode의 간결한 행동 시간선을 보존한다.
상세 구간은 실패 직전, tool 거부, 회복 전후, 진척 변화 및 대표 초반 구간을 균형 있게 선택한다.
선택/누락 이유, token/항목 한도, 원본 evidence ref를 기록한다. 처음/마지막 구간만 보다가
중간의 결정적 사건을 또 놓치지 않도록 사건별 quota와 전체 요약을 함께 둔다.
완료 기준: 이 archive에서 두 blocked_endpoint와 회복 행동이 전달되고, 오래된/누락 로그에서는
UNKNOWN을 유지하며 한도 초과/순서/해시/재개 검증 테스트가 통과한다.

## 2. 후보 선택이 실험 목적을 충분히 반영하지 않음

현재 LLM은 success_probe/boundary_probe/cross_mechanism 가설과 축 구간을 제안하지만,
host는 low/high 후보 중 기존 장면과의 정규화 최대축 거리 기반 novelty가 가장 큰 한 점을 고른다.
가설의 식별력이나 성공 대조 필요성이 실제 우선순위에 들어가지 않는다.
또 모든 제안은 latest 장면을 anchor로 삼으므로 이전 유용한 성공/실패 장면으로 돌아가
다른 축을 조사하는 실험을 명시적으로 표현하기 어렵다.

제안: 버전된 실험 선택 계약을 도입한다. 가설 ID, 검증할 관측, anchor case ID,
변경 축/고정 축, 예상되는 반증 패턴, 반복 필요성, 요청 후보 순위를 보존한다.
LLM의 설명이나 confidence는 보정된 실패 확률/인과 근거로 취급하지 않는다.
선택은 현재 증거 상태에 맞는 목적을 먼저 결정하고 목적 내에서 novelty/비용으로 정한다.
LLM 기반을 유지하며 ExtraTrees 도입을 선행 조건으로 만들지 않는다.

사전에 고정할 상태별 규칙의 예:

- 비교 가능한 PASS 없음: 성공 대조/대안 설명을 찾는 probe 우선.
- PASS/FAIL 관측 쌍 있음: 해당 조건의 중간점·반복으로 관측 bracket 조사.
- 동일 장면 결과 혼합: 재현성 조사; 확정 경계로 부르지 않음.
- 유사 행동 실패가 반복됨: 해당 이웃 우선순위 감소, 다른 축/장면 영역 조사.
- 독립 탐색/재현 예산은 남겨두되 한 실패 주변에 전부 소진하지 않음.

이 규칙은 향후 구현 제안이다. 현재 고정 llm/boundary/exploration/repeat 순환을
이미 적응형 배분으로 교체했다고 주장하지 않는다. 새 정책은 새 캠페인에서 freeze한다.

## 3. 수치가 다른 장면과 행동이 다른 실패를 구분

현재 cooldown signature는 종료 이유 + 정확한 action_counts + event_counts hash다.
발–바닥 접촉 횟수가 조금 달라도 hash가 달라져 같은 정체 과정이 다른 서명으로 보일 수 있다.
반대로 순서/진척/위치가 다른 행동도 같은 횟수이면 합쳐질 수 있다.

제안: tool 상태 전환, 진척/정체, 회복 전후 변화, 물체 이동 여부, 기하 여유를
허용 오차·버전과 함께 요약한 행동 서명을 사용한다. 지지 접촉 횟수를 주된 구분자로 쓰지 않는다.
서명은 탐색용 유사성이지 확정 원인/공식 실패 유형이 아니다. 별도 확인 반복은 허용하며
중복 억제 때문에 신뢰성 측정을 막지 않는다. INCONCLUSIVE는 로봇 행동 실패 학습에서 분리한다.

## 4. 이번 관측을 이용하는 장면 실험 예

아직 실행하지 않은 예다. 폭4m가 현재 domain 상한이므로 단순히 더 넓히기는 불가능하다.
상자 질량/마찰/바닥 마찰/폭과 로봇 조건을 그대로 두고,
`box_lateral_fraction=0`과 `+0.8`, `-0.8`을 비교하는 배치 probe를 고려할 수 있다.
이 조건에서 상자 중심 Y는0 및±1.12m다. 경로 기하가 바뀌면 blocked-start/진척/결과가
어떻게 달라지는지 관찰하며 우회 방향이나 로봇 행동을 지정하지 않는다.
무접촉 우회 기록이므로 상자 질량을 더 낮추는 가설보다 배치 가설이 직접적인 근거를 가진다.
다만 질량을 영구 배제하거나 배치 변경의 성공을 미리 가정하지 않는다.

PASS가 관측되면 같은 조건의 FAIL과 배치 축 bracket을 만들고 반복으로 확인한다.
계속 FAIL이면 정체 위치/도구 상태가 바뀌었는지도 조사하고 대안 축을 검토한다.
바닥 마찰 변화는 별도 probe로 분리하며 낮은 마찰이 반드시 어렵거나 쉽다고 가정하지 않는다.
외부 수동 실행을 정식 cold benchmark의 무료 warm history로 넣지 않는다. 위 archive를
쓰는 개발/warm 탐색은 출처·기존 수집 비용을 공개하고 정식 비교와 분리한다.

## 5. 지표와 확장 순서

기존 FDR/Gain/6종 coverage 목표를 유지한다. 보조 지표로 다음을 검토한다:

- 비교 가능한 첫 성공 대조·첫 관측 PASS/FAIL bracket까지 사용한 rollout/API/토큰.
- 반복 확인 횟수와 혼합 결과를 함께 표시한 bracket 폭 변화.
- 행동 서명 기준 새 실패 양상/중복 비율 (공식 유형 coverage와 별도).
- 가설별 다음 실험 결과: 지지, 반증, 판단 유보. 결과 없는 가설은 그대로 가설.
- 비용 누락은0으로 두지 않으며 제외 실행에서 관측된 usage도 보존.

고유 실패 장면 수/반복 수/일부 비용은 이미 구현돼 있으므로 새 기능처럼 중복 개발하지 않는다.
양쪽 전부 FAIL이면 FDR100%여도 상대 Gain0%다. 이때 예산을 더 써서 유사 FAIL을 쌓는 것보다
성공 대조·반복성·다른 행동 양상 조사가 유용하다. 그것이 Gain 목표 달성을 대신하지는 않는다.
6종 family detector는 아직 없고, 서명 클러스터를 이름만 바꿔4종으로 세지 않는다.

장면 확장은 이후 상자 크기/X, 다중 장애물/목표 점유 등 실제 goal-agent backend와
SceneGraph/XML/관측이 함께 지원하는 범위부터 한다. 새 domain은 Random에도 동일하게 적용한다.
점프 기술 개발, 로봇 경로 계획기 수정, prompt/예산 변경은 이번 AFS 개선 범위 밖이다.

권장 구현 순서: 중요 증거 보존 → 행동 중복 억제 → 가설/anchor 기반 후보 선택·상태별 배분
→ 비용/경계 보조 지표 및 회귀 자산 검증 → 필요한 장면/유형 확장.
우선 저장 archive와 CPU/synthetic tests로 검증하고 추가 live 예산은 별도로 검토한다.
