# 최종 이동의 도착 처리와 목표 체류 검증

2026-10-02. 목표 영역에 들어왔지만 마지막 호출 종료 때문에 체류시간을 채우지 못한
사례를 점검하고, 별도 로봇 실행 조건 `goal_dwell_v1`을 추가했다. 목표 평가를 완화하거나
기존 FAIL을 PASS로 바꾸지 않는다. 이 문서는 변경 범위와 제한된 후속 검증 명령을 설명한다.

후속: 첫 사용자 실행은 목표 미도달 FAIL이었으며 체류 유지는 실행되지 않았다.
현재 코드는 [경로 추종과 수치 명령 피드백](ROBOT_NAVIGATION_FEEDBACK.md)도 반영한다.
아래 명령도 현재 로봇 버전으로 실행되므로 과거 체류 옵션만의 효과 비교가 아니다.

## 확인한 문제와 변경 범위

2026-09-29 완료된 장애물 파일럿의 AFS 사례는 최종 목표에서 약 0.119m까지 갔지만,
체류시간 약 0.775초에서 마지막 navigate_to가 끝났다. 원래 목표는 거리 0.25m 미만에서
연속 1초 유지다. 호출 예산도 10회 소진되어 기존 계약에 따라 FAIL이었다.
Random PASS 사례는 남은 호출의 추론 대기 중 1초를 채웠다. 종료 시점에 대한 민감성이지
경로 불가능성이나 로봇의 물리적 한계를 확정한 결과는 아니다.

| 실행 옵션 | 최종 목적지 도착 시 처리 | 중간 경유점 |
|---|---|---|
| `position_only_v1` 기본값 | 요청 좌표 0.12m 미만이면 즉시 반환 | 동일 |
| `goal_dwell_v1` 선택 옵션 | 도착 후 해당 행동의 남은 시간 안에서 기존 자세 유지 제어 실행 | 기존처럼 즉시 반환 |

선택 옵션은 GPT가 스스로 `navigate_to`의 목표로 **최종 목적지 좌표**를 지정한 경우에만
적용한다. 좌표 일치 허용치는 1e-6m다. 최종 목표 영역 안에 있는 임의 경유점으로 자동 확대하지 않는다.
AFS나 평가기가 이동 경로·중간 목표를 지정하지 않는다.

- 최초 0.12m 도착 위치와 방향을 유지 기준으로 삼는다. 물리 상태를 고정하거나 순간이동하지 않는다.
- 자세 유지 중 목표 반경 0.25m 밖으로 벗어나면 체류시간이 초기화되고 기존 경로 추종을 재개한다.
- GPT가 요청한 `duration_s`와 명시적 시뮬레이션 상한 중 먼저 도달하는 시점에서 행동을 끝낸다.
- 추가 호출, 행동 시간 연장, 예산 종료 후 유예시간은 없다. 물리 적분은 기존 고정 timestep 단위다.
- 시간이 부족하거나 도달하지 못하면 계속 FAIL일 수 있다. 성공은 독립 GoalEvaluator만 판정한다.
- `stop`, 경로 없음, 중간 경유점에는 자동 도착 보완을 적용하지 않는다.
- `legacy_guarded`와 새 옵션을 함께 지정하면 실행 전에 거부한다.

기본 호출 10회, 목표 조건, 시간 상한 없음, API timeout, 출력 토큰 기본 상한 없음,
사용량 기록, 접촉·낙상 이벤트의 비종료 의미, MP4 전용 기록은 유지한다.
점프·집기·새 경로 계획기를 추가한 작업이 아니다.

## 저장되는 진단과 AFS 피드백

새 실행의 `protocol.json`은 navigation completion 전체 계약과 코드 해시를 기록한다.
기존 프로토콜에서 해당 필드가 없으면 읽기 시 position-only 의미로 해석하지만 파일은 수정하지 않는다.
조건 해시에 새 계약이 포함되므로 두 동작을 같은 조건의 경계나 반복으로 합치지 않는다.

- `goal_context_NNN.json`: 해당 관측 시 GPT에 전달한 목표 계약, 도착 처리 옵션, 목표 진행 상태.
- `decisions.jsonl`의 이동 tool_result: 행동 시작·마감 시간, 최초 0.12m 도착 시각, hold 시간,
  행동 종료 시 목표 거리와 현재·남은 체류시간.
- `result.json`: 최종 목표 거리와 체류시간 상태를 `goal_progress`에 저장.
- `terminal_diagnostics.json`: 종료 phase/reason, 남은 호출·시뮬레이션 예산,
  마지막 navigation 정보, 체류 중 예산 종료 여부. 성공 가능성이나 원인을 단정하는 필드는 아니다.
- `report.html`: 목표 체류시간과 종료 진단을 표시. GIF는 만들지 않는다.

행동 종료 시 거리·체류시간은 P1 행동 근거와 AFS의 전체 action_timeline에도 전달한다.
이전 기록에 측정값이 없으면 생략한다. 누락을 0으로 채우거나 기존 목표 결과·실패 유형을 바꾸지 않는다.
이 값은 **각 행동 종료 시점**의 기록이며 이후 추론 대기까지 포함한 최종 상태와 같지 않을 수 있다.

기본 옵션을 유지하더라도 새 코드는 GPT에 도착 계약·진행 상태를 추가로 전달한다.
따라서 과거 코드·프롬프트의 정확한 재현 모드는 아니다. 이전에 동결된 캠페인이나 회귀 suite를
새 코드로 재개하지 말고 새 출력 디렉터리를 사용한다. 원본은 그대로 보존한다.

## 먼저 한 번 실행하는 명령

기존 RunPod의 CUDA·MuJoCo·GR00T 환경과 현재 셸의 `OPENAI_API_KEY`가 필요하다.
키 설정은 [루트 README](../../README.md)를 따른다. 아래 live 명령은 유료 API/GPU 실행이다.
로봇 호출 최대 10회이며 AFS 제안 호출은 없다. 과거 행동을 재생하는 것이 아니라 새 판단으로 실행한다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

기존 0.119m 근접 실패 장면을 사용한다. 실행 출력은 새로운 시각의 robot_goal_agent 폴더에 저장된다.

```bash
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --navigation-completion goal_dwell_v1 --scene-config /workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00006/scene_config.json
```

이 단독 실행과 아래 suite를 모두 실행하면 별도 비용이다. **처음에는 하나만 선택**한다.
새 옵션으로 같은 궤적이나 PASS가 반드시 재현된다는 보장은 없다.

## 세 사례의 고정 예산 회귀 계획

근접 실패 attempt_00006, 성공 대조 attempt_00009, 장애물 간섭 연관 사례 attempt_00004를
각 2회 실행한다. 총 6회 시도, 최대 로봇 API 60회, AFS 호출 0회다.
제외된 시도도 슬롯을 사용하며 자동 대체·유료 재시도는 없다. 금액 상한을 뜻하지 않는다.
이는 선택한 사례의 버전 비교이지 AFS와 Random의 새 비교 실험이 아니다.

다음 명령은 **읽기 전용 plan**으로 API/GPU 없이 예산과 원본 유효성을 확인한다.

```bash
uv run --no-sync python tools/run_behavior_regression.py plan --run /workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00006/rollout --run /workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00009/rollout --run /workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00004/rollout --repeats 2 --navigation-completion goal_dwell_v1
```

새 suite를 만든다. 이것도 API/GPU 실행 없이 로컬 파일과 조건 해시만 저장한다.
이미 존재하는 출력 경로를 덮어쓰지 않는다. 생성 이후 실행 코드를 바꾸면 다시 새 suite가 필요하다.

```bash
uv run --no-sync python tools/run_behavior_regression.py init --run /workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00006/rollout --run /workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00009/rollout --run /workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z/attempts/attempt_00004/rollout --repeats 2 --navigation-completion goal_dwell_v1 --output-dir /workspace/g1_failure/runtime/behavior_regression/goal_dwell_luna_20261002
```

먼저 **한 슬롯만 유료 실행**한다. 다음 case 순서는 plan/init 출력에 기록된다.

```bash
uv run --no-sync python tools/run_behavior_regression.py run --suite /workspace/g1_failure/runtime/behavior_regression/goal_dwell_luna_20261002 --live --max-new-attempts 1
```

결과 확인 후 같은 명령으로 한 슬롯씩 이어간다. 성공/실패 자체는 정상 결과이며,
제외·모호한 중단이 있으면 근거를 먼저 확인한다. `--continue-after-exclusion`을 미리 넣지 않는다.
총 6회가 끝나면 동일 명령으로 예산을 늘리거나 추가 실행하지 않는다.

## 검증 범위와 이후 판단

CPU MuJoCo·모의 정책/제어기 테스트로 다음을 확인한다. 스크립트로 바꾼 테스트 좌표는 G1 성능 증거가 아니다.

- 기존 동작의 마지막 도착 시 체류 부족 FAIL과 새 옵션의 동일 테스트 입력 PASS.
- 목표 이탈 시 체류 초기화, 중간 경유점·경로 없음·stop의 기존 종료.
- 행동·시뮬레이션 예산 부족 시 FAIL 유지, 추가 호출/시간 없음.
- 새 계약의 정책 전달, 아카이브 검증, AFS/회귀 조건 불일치 제외, 원본 보존.
- 체류시간 근거가 AFS 요약에 보존되지만 목표 판정을 바꾸지 않음.

실제 저장 사례 3개의 plan 검증을 수행했다. 이후 첫 사용자 GPU/API 실행은 유효 FAIL이었고,
도착하지 않아 체류 유지의 실제 효과는 미검증이다. 후속 추종기 변경은 위 문서를 따른다.
추론 대기시간을 물리 시뮬레이션에 포함하는 기존 정책도 유지하므로, 응답 지연의 영향까지
제거한 변경은 아니다. 모든 행동에 공통 종료 유예를 추가하는 정책도 아니다.
새 결과에서는 목표 진입·체류·종료 이유를 먼저 비교한다. PASS가 나오더라도 과거 FAIL을
고치거나 전체 로봇 개선율로 해석하지 않는다. 이후 동일 새 조건의 성공/실패 표본을 확보해
AFS 경계 탐색을 이어가며, 이전 조건의 표본과 섞어 bracket을 만들지 않는다.
