# 성공 기준 분기 AFS와 실패 행동 진단

`failure-branch-v3`는 이미 실패한 조건이 다음 장면에 계속 누적되는 문제를 줄인다.
새 실패 가설은 관찰된 성공 장면에서 분기하고, 실패를 완화하는 가설은 관찰된 실패
장면에서 분기한다. 어떤 장면을 기준으로 골랐는지는 LLM이 설명하고 호스트가 검증한다.

우선 목표는 **같은 목표의 서로 다른 환경을 시험한 전체 유효 표본에서 실패율30% 이상과
근거가 있는 실패 유형4종 이상을 함께 관찰**하는 것이다. 한 회차에서4종을 모두 찾는
요구가 아니다. Random 대비20% 향상은 별도의 후속 비교 지표다. 현재 모드는 검토된
외부 이력을 사용하는 개발 탐색이며, 독립 평가나 Random 대비 향상 실적이 아니다.

## 기준 장면 선택

| 제안 의도 | 허용하는 기준 장면 | 확인하는 사항 |
|---|---|---|
| challenge 또는 mechanism_transfer | 관찰 결과가 PASS인 장면 | 기존 실패 조건을 자동으로 물려받지 않는다 |
| relief | 관찰 결과가 FAIL인 장면 | 어느 실패를 완화하는지 명시한다 |

후보마다 `anchor_case_id`, `anchor_rationale`를 필수로 받는다. 요청의 `anchor_catalog`에는
실제로 제공한 행동 근거가 있는 기준 장면의 파라미터와 SceneGraph가 포함된다.
선택한 기준 장면의 실제 에피소드를 `behavior_refs`로 인용해야 한다. PASS/FAIL이 섞인
장면, 제외된 실험, 근거가 제공되지 않은 장면은 기준으로 쓸 수 없다.

후보는 **선택한 기준 장면에서 정확히 한 축만 변경**한다. 최소 변화량도 최신 장면이
아닌 그 기준에서 계산한다. 전체 이력과 중복되는 후보는 거절한다. 동일한 숫자를 제안해도
기준 장면이 다르면 전체 환경이 다를 수 있으므로, 제안 중복 검사는 기준 ID를 함께 본다.

예를 들어 최신 실패 장면의 상자 위치 비율이 `.25`여도, 위치 비율이 `1`인 성공 장면을
기준으로 바닥 마찰을 시험하면 위치는 `1`로 유지한다. 이것은 사전 장면 생성이며
실험 도중 환경을 되돌리는 동작이 아니다. 폭 변경에 따른 객체 Y 좌표 재계산은 기존
생성기의 결합 관계이므로, 한 파라미터 변경이 한 기하 요소 변경을 뜻하지는 않는다.

PASS는 관찰값이지 항상 성공하는 장면이라는 보증이 아니다. 분기는 실패 원인의 독립성이나
인과성을 입증하지 않는다. 사용 가능한 성공 기준이 없으면 새 메커니즘 제안은 허용하지
않고, 허용된 실패 완화 분기만 사용하거나 명시적으로 중단한다.

## 감사와 실험 경계

후보의 `branch_audit`에는 기준 장면·에피소드 ID, 기준 결과, 선택 이유, 변경 축과
전후 값, 나머지 파라미터 동일성 검증을 저장한다. HTML 보고서와 다음 요청의 최근
가설 결과에도 이 정보가 전달된다. 응답 저장 직후 중단되면 저장된 응답을 재검증하고
추가 AFS 요청 없이 이어갈 수 있다. 애매한 유료 호출은 자동 재전송하지 않는다.

기존 실패 지향 순위, 축 쿼터·cooldown·최소10% 변화·신규성·relief cooldown은 유지한다.
예측 유형은 탐색 방향일 뿐 실제 측정 유형으로 집계하지 않는다. 로봇·목표·정책 예산·
평가기·분류 임계값은 바꾸지 않았다. 실험 중 AFS가 로봇 행동을 지정하지 않는다.

새 설정 `config/afs_failure_branch_luna.json`은 Luna, 유효6개 목표, 최대8시도·AFS8요청,
축별 최대2회, 자동 반복0회를 사용한다. 현재 로봇 조건에서는 최대80회 로봇 호출이다.
제외 회차도 예산을 소모하며 검토를 위해 중단한다. 토큰 상한, 암묵적 시뮬레이션 상한,
GIF 저장은 추가하지 않았다. 입력 이력 비용과 신규 실험·선택 비용은 분리한다.

## 기존 실패가 유형으로 집계되지 않은 이유

`tools/audit_failure_phases.py`는 검증된 기존 아카이브만 읽는다. 전체 행동의 도구 오류와
접촉 시간선을 기존 종료 구간 측정·규칙 조건과 함께 저장한다. 전체 시퀀스에서 오류가
있었다고 해서 종료 구간 규칙을 만족했다고 간주하지 않는다.

최근 실패 지향 세션의 진단은 다음과 같다.

| 회차 | 목표 결과 | 기존 규칙의 주요 미충족 조건 |
|---|---|---|
| 0 | FAIL | 종료 정체는 있지만 전체 목표 영역 점유가 아니며, 최근 막힘 도구 횟수0 |
| 1 | FAIL | 종료 정체 조건 불충족, 과거 막힘 오류는 최근 판정 구간 밖 |
| 2 | FAIL | 목표 영역 전체 점유는 있으나 종료 정체 조건 불충족 |
| 3 | 제외 | API 시간 초과, 유효 실패나 발견 유형으로 집계하지 않음 |

충돌 규칙에 필요한 최근 유효 접촉도 이 실패들에서 확인되지 않았다. 회차0의 밀기 요청은
`alignment_out_of_range`로 거절되었다. 이는 실제로 밀어 보니 무거워서 실패했다는 근거가 아니다.
세 FAIL은 그대로 유효하지만 현재 규칙상 미분류다. 진단은 새 라벨을 부여하거나 기존
아카이브·DB·결과·분류 임계값을 수정하지 않는다. 누락 측정은0으로 대신하지 않는다.

생성된 진단 결과:
`/workspace/g1_failure/runtime/failure_phase_audit/20261018T074329_464497Z/report.html`

판정 계약을 확대할 필요가 있다면 전체 행동의 어떤 근거를 어떤 유형으로 인정할지 먼저
별도로 정의하고 검증해야 한다. 이 변경에는 그러한 규칙 확대를 포함하지 않았다.

## 실행 방법

이전 동결 세션 `20261018T032610_668533Z`나 recovery 세션을 새 소스로 재개하지 않는다.
기존 결과를 보존하고, 아래처럼 검토된 성공2개·실패3개를 입력으로 **별도 예산의 새 세션**을
시작한다. 제외된 회차는 PASS/FAIL 기준으로 넣지 않는다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

무료 사전 검사이며 API·로봇·세션 디렉터리를 생성하지 않는다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py plan --config config/afs_failure_branch_luna.json --run /workspace/g1_failure/runtime/robot_goal_agent/20261018T004636_410637Z --run /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery/attempts/attempt_00001/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00001/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00002/rollout
```

API 키가 설정된 터미널에서 다음 명령은 **새 유료 탐색 전체**를 시작한다. 코드 변경 후
오프라인 검증까지만 완료했으며, 새 모드의 실제 실패 발견 성능은 아직 측정하지 않았다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --config config/afs_failure_branch_luna.json --run /workspace/g1_failure/runtime/robot_goal_agent/20261018T004636_410637Z --run /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery/attempts/attempt_00001/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00001/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00002/rollout
```

진단만 새로 저장하려면 다음을 사용한다. API 키나 GPU는 필요하지 않다.

```bash
uv run --no-sync python tools/audit_failure_phases.py --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00001/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00002/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/attempt_00003/rollout
```

JSON·HTML은 `/workspace/g1_failure/runtime/failure_phase_audit/<새 시각>/`에 저장한다.
입력 아카이브 내부 저장과 기존 출력 덮어쓰기는 거절한다.
