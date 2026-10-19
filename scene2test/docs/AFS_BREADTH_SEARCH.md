# 환경 요소 배정과 조합 AFS 탐색

`afs_breadth_luna.json`은 기존 분기 AFS에 `exploration_policy: breadth-v1`을 명시적으로 추가한다. 작은 변경을 유지하면서 바닥 마찰, 물체 물성, 장애물 형상, 배치, 사람 배치에도 실행 기회를 배정한다. 기존 `afs_expanded_ten_luna.json`은 단일 축 정책을 그대로 사용한다.

이 모드는 검토된 외부 이력을 이용하는 개발 탐색이다. 실패율 30%와 실제 측정된 대표 유형 4종을 목표로 하지만, 실행 배정 자체는 발견 성과나 Random 대비 Gain을 뜻하지 않는다. GPT의 예측 유형은 실제 측정 유형과 분리한다.

## 행동 진단과 신규 집합 기준 선택

새 설정 `config/afs_behavior_diversity_luna.json`은 같은 배정·예산에 `feedback_policy: action-diagnostics-v1`을 추가한다. 기존 `afs_breadth_luna.json`은 기존 선택 의미를 유지한다. 새 모드도 로봇, 목표, 분류 규칙, 토큰·시간 제한을 바꾸지 않는다.

새 모드는 다음을 구분한다.

- `historical_discovered_families`: 외부 참고 이력에서 발견한 유형.
- `current_discovered_families`: 이번 세션의 실제 유효 실패에서 발견한 유형.
- `cumulative_discovered_families`: 과거와 신규의 합집합.

호스트의 `missing_supported_families` 우선순위는 이번 세션을 기준으로 계산한다. 과거에 발견했어도 이번 집합에서 아직 발견하지 못한 유형은 선택 기회를 유지한다. 과거 비용이나 발견을 신규 성과 분모에 넣는 것은 아니다.

`behavior_observations.action_diagnostics`와 최근 가설 검토에는 전체 행동의 경로 거절 수, 최초 거절 행동과 근거, 같은 좌표의 반복 거절, 과제 목표 밖에서 끝난 중간 목표 도착, 조작 요청 유무가 들어간다. `action_pattern_feedback`은 이런 행동을 동반한 유효 실패의 횟수를 과거와 신규로 나눈다. 서로 겹치는 진단 통계이며 새로운 실패 유형 수가 아니다. 누락 자료는 0으로 만들지 않고 UNAVAILABLE 또는 부분 관측으로 표시한다.

LLM에는 같은 행동이 반복되면 허용된 다른 기준 장면·배치와 예상 행동을 검토하도록 요청한다. 물체 질량이나 마찰을 바꿨더라도 조작 요청이 없었다면 물리적 밀기 능력을 검증했다고 해석하지 않는다. 이는 진단 기반 제안 지침이지 로봇 행동 강제나 자동 원인 판정이 아니다. 기존 배정, 축 쿼터, 중복·범위 검사와 bounded rejection은 그대로 유지한다. 새 지형이나 사람 이동 기능을 추가한 것은 아니다.

완료된 `20261018T160156_325966Z_numeric_recovery`에는 적용하거나 재개하지 않는다. 다음은 저장된 FAIL과 PASS를 읽는 무료 사전 검사다. DB·API·로봇 실행은 없다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py plan --config config/afs_behavior_diversity_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00002/rollout
```

다음 명령은 API 키가 설정된 터미널에서 **별도 유료 세션**을 시작한다. 신규 유효 12개, 최대 16회 시도, AFS 20요청이며 기준 로봇이 10회 호출이면 최대 160회 로봇 호출이다. 제외 실행에서는 검토를 위해 중단한다. 실제 발견 유형 증가 여부는 이 새 실행에서 확인해야 한다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --config config/afs_behavior_diversity_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00002/rollout
```

## 제안과 선택

GPT-6-luna는 근거가 있는 후보들을 제안하고, Python 선택 코드는 사전에 공개한 실행 배정 계약에 맞는 하나를 선택한다. 랜덤 선택이 아니며 코드가 후보의 물리적 실패 가능성을 알아내는 모델도 아니다.

| 환경 요소 묶음 | 해당 축 |
| --- | --- |
| 바닥 물성 | floor_friction |
| 물체 물성 | box_mass_kg, box_friction |
| 장애물 형상 | 장애물 크기, 높이, 회전 |
| 배치 | 통로 폭, 상자와 장애물 위치 |
| 사람 배치 | human_x_m, human_lateral_fraction |

쿼터와 직전 축 사용 제한을 통과한 묶음 중 신규 시도 횟수가 가장 적은 묶음을 다음 실행에 배정한다. 동률이면 위 표 순서다. 예산이 충분하고 후보가 유효하다면 배치 후보가 계속 먼저 제안돼도 물성 실험을 밀어내지 못한다. 종료 목표나 오류로 먼저 멈출 수 있으므로 모든 묶음 또는 모든 축의 실행을 보장하지는 않는다.

실험 시도 순서에 따라 다음 형태를 순환한다.

- 작은 변경: 단일 축, 전체 허용 범위 폭의 10% 이상 30% 미만 변경.
- 큰 변경: 단일 축, 전체 허용 범위 폭의 30% 이상 변경.
- 조합: 서로 다른 묶음에 속한 두 축, 각 축은 전체 허용 폭의 10% 이상 변경.

10%는 설정의 최소 변화 비율이며 30%는 버전 고정 구분 기준이다. 이는 환경 난이도나 안전 기준이 아니다. 변화가 커질수록 실패가 늘어난다는 단조성도 가정하지 않는다. 조합에서는 요구된 묶음을 적어도 하나 포함한다. 모든 값은 기존 도메인 범위를 유지한다.

연속된 신규 유효 PASS 두 개에서 같은 예측 유형을 겨냥했다면 다음 선택에서는 그 예측 유형을 잠시 제외한다. 두 PASS가 같은 묶음을 변경했다면 다음 배정은 가능한 다른 묶음을 우선한다. 제외 실행은 PASS 연속성을 끊고, 예산은 소비한다. 연속 PASS도 그 유형이 불가능하다는 증거는 아니다.

배정 조건에 맞는 후보들 중 미발견 측정 유형, 탐색 의도, 해당 예측 유형의 시도 횟수, 묶음 시도 횟수, 신규성, 제안 순서로 선택한다. 발견 여부는 검토된 이력과 새 실행의 실제 측정으로 판단하며, 성과 보고의 분모는 신규 유효 실험으로 별도 유지한다.

## 두 요소 조합 계약

후보의 `axis`와 `value`에 첫 변경을, 필수 필드 `extra_changes`에 두 번째 변경을 넣는다. 단일 축은 `extra_changes: []`다. 두 축은 같은 관측 PASS 기준 장면에서 출발하며, GPT가 함께 바꾸는 이유와 대안 설명을 제공한다. 실패 완화는 기존 계약에 따라 관측 FAIL에서만 분기한다.

범위, 유한 수치, 근거 ID, 기준 장면 역할, 각 축 최소 변화량, 중복 전체 장면, 축 쿼터와 직전 축 제한을 모두 검사한다. 선언하지 않은 파라미터는 변하지 않는다. 통로 폭에 따른 파생 좌표 변경은 있을 수 있다. 조합은 두 축과 두 묶음 모두에 시도 횟수를 부과하되 로봇 실험 한 회로 센다.

숫자 범위를 벗어난 후보는 원래 값과 승인 범위를 기록해 제외하고 유효한 대안은 유지한다. 값을 보정하지 않는다. 맞는 후보가 없으면 원인과 제안을 저장하고 남은 AFS 요청 예산 내에서 새로운 제안을 받는다. 형태나 묶음을 몰래 바꾸거나 Random으로 대체하지 않는다. API·스키마·근거 오류, 모호한 유료 요청은 계속 중단한다. 후보 거절도 AFS 예산과 비용을 소비한다. 이미 중단된 세션은 [저장 응답 복구 안내](AFS_NUMERIC_RECOVERY.md)를 참조한다.

환경은 로봇 실행 전 고정한다. AFS는 실행 중 장면이나 로봇 명령을 바꾸지 않는다. 로봇, 목표, 평가기, 호출 제한과 완료 조건은 기준 이력에서 그대로 상속한다. 새 지형, 계단, 방 구조나 움직이는 사람을 추가한 모드는 아니다.

## 예산과 실행

새 설정은 유효 12개 목표, 최대 16회 시도, AFS 요청 최대 20회, 축별 최대 4회, 명시적 반복 0회다. 기준 로봇이 회당 10회 호출이면 상한은 로봇 160회와 AFS 20회다. 이는 새로운 유료 세션 전체의 상한이며 기존 세션 예산 증액이 아니다. 토큰 상한이나 암묵적인 시뮬레이션 시간 상한을 추가하지 않았다.

완료된 세션 `20261018T134620_116429Z`는 재개하지 않는다. 아래는 그 세션의 유효 실험 6개만 읽는 무료 사전 점검이다. 제외된 attempt_00001은 실패 근거로 입력하지 않는다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_afs_autonomous.py plan --config config/afs_breadth_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00002/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00003/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00004/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00005/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00006/rollout
```

API 키가 설정된 터미널에서 다음 명령은 새 유료 세션의 남은 전체 예산을 자동 진행한다. 설정 파일을 수정해 기존 동결 세션을 재개하지 않는다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --config config/afs_breadth_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00002/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00003/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00004/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00005/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T134620_116429Z/attempts/attempt_00006/rollout
```

결과는 `/workspace/g1_failure/runtime/afs_autonomous/<시각>/`에 저장한다. 보고서의 `exploration_allocation`, 후보 `exploration`, `changed_axes`와 `branch_audit`로 배정 이유와 실제 변경을 확인한다. `group_attempts`는 조합이면 두 묶음에 각각 가산하므로 합이 실험 수보다 클 수 있다. COMPLETE 이후 표시된 다음 배정은 참고값이며 `next_slot_is_executable=false`이면 실행하지 않는다. 제외에서는 검토를 위해 중단하며 시도/비용을 보존한다.

## 검증 범위

CPU 합성 테스트는 선택, 조합 검증, 예산, 보고 및 중단 재개를 검증한다. 새 방식의 실제 실패 유형 발견 성과는 새 유료 실행 후 확인해야 한다. 구조화 출력은 [OpenAI 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)에 맞춰 객체 추가 키를 금지하고 모든 필드를 필수로 둔다. 범위와 장면 일관성은 서버 측 코드에서 다시 검증한다.
