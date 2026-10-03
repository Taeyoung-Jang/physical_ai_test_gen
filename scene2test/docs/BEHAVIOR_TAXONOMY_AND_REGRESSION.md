# 행동 근거 유형 측정·사용량 감사·실행 가능한 회귀 테스트

2026-09-28. 기존 slalom 성공 실행 검토 후 요청한 세 후속 작업이다.
로봇의 결정, 내부 계획기, 기술, 최초 goal 판정은 변경하지 않았다.
**새 유료 API/GPU 실험은 실행하지 않았다.** 합성 실행/CPU 검사와 기존 실제 archive의
오프라인 재측정을 구분한다. 모든 실행 명령은 `scene2test`에서 수행한다.

## 1. 종료 뒤 응답도 사용량에 포함

기존 decision-only 집계는 goal 도달 직후 완료된 미실행 응답을 놓칠 수 있었다.
새 `robot-call-usage-v2`는 원본 manifest에 등재되고 해시가 일치하는
`decisions.jsonl`, `pending_call.json`, `api_call_NNN.jsonl`을 읽는다.

- observation/call ID별로 모으고 response ID·input/output/total 일관성을 검사한다.
- 같은 응답이 여러 파일에 있어도 한 번만 센다. 실행하지 않은 완료 응답도 비용 근거다.
- 서로 다른 호출이 동일 response ID를 쓰거나 사용량이 충돌하면 해당 호출을 합계에서 제외하고 경고한다.
- 일부 누락은 `PARTIAL`, 전부 미측정은 null이다. 부분 합계와 `calls_missing_usage`를 함께 확인한다.
- 선택적인 사용량 로그가 깨졌다는 이유만으로 원래 goal PASS를 FAIL로 바꾸지 않는다.
- cached/reasoning 세부 토큰을 input/output에 다시 더하지 않는다. 출력 토큰은 보이는 답변만이 아니다.
  [공식 토큰 설명](https://developers.openai.com/api/docs/guides/token-counting)을 참조한다.
- 이것은 응답에 기록된 사용량이지 청구서·금액 계산이 아니다.

독립 goal runner의 새 `protocol.source_hashes.fixture_obstacles`는
`clear_path/obstacles.py`를 포함한다. 과거 protocol/manifest는 수정하지 않는다.
이전 동결 캠페인은 기존 코드로만 재개해야 한다. 새 집계가 필요하면 별도 오프라인 보고서를 만든다.

## 2. 목표 실패와 별개인 유형 측정

옵션 `--with-taxonomy`, 규칙 버전 `goal-behavior-v1`.
실제 goal FAIL 중 시간·행동·geometry 근거가 있는 연관성을 분류한다.
**원인 확정, 이동 불가능 증명 또는 로봇 행동에 대한 새 제한이 아니다.**

공통 정체 조건: 종료 직전 5초, state 간격/종료 누락 ≤ 0.25초, goal 밖에 머묾,
goal 거리 범위 ≤ 0.15m, 창 시작 대비 최대 base XY 이동 ≤ 0.35m.
샘플이 부족하면 UNKNOWN이다. 창에는 추론 대기도 포함된다.

| 유형 | 추가 측정 조건 | 제외/한계 |
|---|---|---|
| `collision` | move/navigate 중 알려진 정적 geometry와의 접촉이 마지막 2초 이내까지 존재, 지속 ≥ 0.2초, 최대 normal force ≥ 10N, 정체 | 발–바닥, 기존 movable box 접촉, push 단계는 제외. 잘린 접촉/이름 불일치 근거로 단정하지 않음 |
| `obstacle_interference` | 마지막 10초에 accepted plan_path/navigate_to의 no_path/blocked_endpoint ≥ 2회, 마지막 base–물체 투영 거리 ≤ 0.55m, 정체 | no_path 한 번으로 불가능 판정하지 않음. 전신 clearance가 아니라 base 점과 물체 투영 거리 |
| `goal_occupied` | 5초 내내 동일 upright 물체의 XY 투영 내부에 전체 goal 원이 포함, 물체 바닥 ≤ 0.1m, 정체 | 초기 점유만으로 분류하지 않음. 기울어진 물체 점유는 UNKNOWN; 조작/점프 불가능 증명 아님 |

XML/config 일치와 robot audit의 appended box qpos 주소를 검증한다.
회전된 upright 직육면체는 local 좌표로 검사한다. 기울어진 물체의 근접성은 보수적 AABB다.
임계값, 상태, evidence artifact/hash/line, 시간 구간은 `taxonomy.json`에 저장한다.

- PASS는 실패 유형 N/A이며 관련 진단값은 별도 보존한다.
- 한 실행에 여러 규칙이 맞으면 primary family는 UNKNOWN이다.
- 같은 장면의 반복이 서로 다른 유형을 제시해도 coverage를 중복 증가시키지 않는다.
- `unreachable`, `human_safety_risk`, `perception_error`는 아직 UNSUPPORTED다.
- 분모는 6이다. 부분 지원이면 `failure_diversity_coverage=null`,
  `coverage_status=partial_operational_rules`, 관측 하한은 `observed_family_coverage_lower_bound`로 별도 표시한다.
  **3개 규칙 구현은 3개 실제 유형 발견 또는 목표 4/6 달성이 아니다.**
- 인과 확인은 성공 쪽 완화·단일 축 대조·반복 실험이 필요하다.

새 obstacle AFS 설정은 `taxonomy_profile: goal-behavior-v1`을 사용한다.
이 경우 해당 AFS arm/seed 자체의 기록만 분류하여 다음 LLM context에
`operational_taxonomy`로 추가한다. 가설과 관측·인과 미확정 상태를 구분하며,
Random이나 외부 slalom 기록을 AFS history로 몰래 주입하지 않는다.
기존 v1/v2 설정은 기본 `none`; 목표 평가, FDR 분모, Random 분포는 그대로다.

실제 slalom 기록 재측정: API 키/GPU 불필요, 새 보고서만 작성한다.

```bash
uv run --no-sync python tools/measure_failure_discovery.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260928T151133_926563Z --with-memory --with-taxonomy
```

저장 위치: `/workspace/g1_failure/runtime/failure_measures/<시각>/`.
`report.html`, `taxonomy.json`, `episodes.jsonl`, `metrics.json`, `memory/index.html`을 확인한다.
기존 성공 기록은 VALID PASS, 7개 호출의 관측 사용량은 입력 164,000 / 출력 2,971토큰이다.
최종 goal 달성 판정을 바꾸지 않았으며 이 성공은 실패 유형 coverage에 들어가지 않는다.

## 3. 저장 사례의 자동 회귀 실행

`tools/run_behavior_regression.py`는 기존 LocalGoalRunner와 client SQLite transaction/ledger를 재사용한다.
일반 HTTP registry 플러그인, AFS 탐색 또는 과거 프로그램을 복원하는 도구는 아니다.

### 계약

- `--run`을 반복하거나 `--memory memory.json`으로 성공/실패 사례를 입력한다.
  memory의 원본 archive 경로가 살아 있어야 하며 현재 해시/결과를 다시 검증한다.
  exported evidence bundle만으로 모든 외부 자산을 복원하는 기능은 아니다.
- 같은 condition+scene의 baseline 반복은 하나의 사례로 묶고 혼합 결과도 보존한다.
- baseline의 goal/evaluation profile, scene, 호출·시뮬레이션 예산, push 가능 여부, HTTP timeout을 고정한다.
- 요청 모델도 baseline 그대로 사용한다. `init --model ...`은 명시적 모델 버전 비교다.
- 원본 robot XML/mesh/YAML/ONNX가 현재 자산과 일치해야 한다. 새 로봇 embodiment 비교는 별도 작업이다.
- 현재 코드·의존성·자산을 init 시 동결하고 실행 전/후 및 재개 시 검증한다.
  baseline과 새 실행의 source/model/protocol 차이는 `attempts.json`에 기록한다.
- 이것은 **현재 버전으로의 replay 비교**다. 과거 source hash와 같은 코드라는 주장,
  외부 모델의 결정성·통계적 성능 변화의 확정은 하지 않는다.
- 사례당 repeats 기본 2회(1–10 허용), 입력 archive 최대 32개. 반복은 고정 **시도 예산**이다.
  제외된 실행도 한 자리를 소비한다. 성공할 때까지 재실행하지 않는다.
- AFS 호출은 0회. baseline 수집 비용은 새 실행 비용에 합산하지 않으며 원본에는 보존된다.
  이 결과를 과거 AFS/Random 실험의 무료 확인 반복이나 Gain 표본으로 추가하지 않는다.

### 실행 명령 (한 줄씩 복사)

먼저 plan만 확인한다. 파일 생성·API·GPU 실행이 없다.

```bash
uv run --no-sync python tools/run_behavior_regression.py plan --run /workspace/g1_failure/runtime/robot_goal_agent/20260928T151133_926563Z --repeats 2
```

slalom 성공 사례 1개 × 2회 = 최대 2번의 로봇 실행, 로봇 API 최대 20회다.
모델은 원본 `gpt-6-luna`, 기본 120초 제한은 추가하지 않는다.

새 suite를 초기화한다. 자산·코드를 검사하고 저장하지만 아직 로봇은 실행하지 않는다.
아래 이름이 이미 있으면 덮어쓰지 않는다. 그 suite를 쓰거나 새 이름을 지정한다.

이 작업에서 아래 `slalom_luna_20260928` suite를 오프라인으로 이미 초기화했다.
현재 환경을 그대로 사용하는 경우 init을 다시 하지 말고 status 확인 후 run 단계로 진행한다.
코드를 수정했다면 새 이름으로 다시 init해야 한다.

```bash
uv run --no-sync python tools/run_behavior_regression.py init --run /workspace/g1_failure/runtime/robot_goal_agent/20260928T151133_926563Z --repeats 2 --output-dir /workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928
```

이후부터 유료 API/GPU 실행이다. [README의 키 설정](../../README.md)을 적용한 터미널에서 실행한다.
우선 한 번만 실행/확인한다. 이 옵션은 invocation 상한이며 task 호출 예산은 바꾸지 않는다.

```bash
uv run --no-sync python tools/run_behavior_regression.py run --suite /workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928 --live --max-new-attempts 1
```

정상 결과를 확인한 뒤 같은 동결 예산의 남은 반복을 실행한다.

```bash
uv run --no-sync python tools/run_behavior_regression.py run --suite /workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928 --live
```

상태/보고서는 무료이며 API 키가 필요 없다.

```bash
uv run --no-sync python tools/run_behavior_regression.py status --suite /workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928
```

```bash
uv run --no-sync python tools/run_behavior_regression.py report --suite /workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928
```

### 결과와 중단 복구

각 `attempts/attempt_NNNNN/`에 command/process/receipt와 `rollout/`을 보관한다.
`reports/<시각>/report.html`에는 원본 대비 결과와 MP4 링크가 있다. GIF를 생성하지 않는다.
`protocol.json`은 동결 계획/의존성, `campaign.sqlite3`는 intent·원자적 observation checkpoint다.

| 비교 결과 | 의미 |
|---|---|
| `RETAINED_PASS` / `RETAINED_FAIL` | baseline과 새 반복이 같은 목표 결과 |
| `OBSERVED_REGRESSION` | 성공 baseline에서 새 반복들이 실패 |
| `OBSERVED_IMPROVEMENT` | 실패 baseline에서 새 반복들이 성공 |
| `MIXED` | baseline 또는 새 반복에서 성공·실패 혼합 |
| `PENDING` / `INCONCLUSIVE` | 아직 반복 미완료 / 제외 실행 때문에 비교 결론 불가 |

`COMPLETE`는 고정 반복 완료이지 모든 사례 PASS라는 뜻은 아니다.
`COMPLETE_WITH_EXCLUSIONS`는 시도는 소진됐지만 제외 기록이 있어 결론이 불완전함을 뜻한다(exit 2).
단 한 번의 성공/실패나 작은 반복 수로 통계적 개선/퇴행을 단정하지 않는다.

실행 전 intent를 저장한다. 중단 후 유효 archive가 있으면 수집만 하고 재발송하지 않는다.
살아 있을 수 있는 PID나 결과 없는 ambiguous intent는 자동 재실행하지 않는다.
`run --max-new-attempts 0 --live`는 pending 수집만 시도하고 새 로봇을 시작하지 않는다.
제외 발생 시 `NEEDS_ATTENTION`에서 멈춘다. 원인을 조사한 뒤 남은 **기존** 시도만 허용하려면
`run ... --live --continue-after-exclusion`을 명시한다. 제외 슬롯은 복원하지 않는다.
결과가 없는 ambiguous intent만, 해당 프로세스가 종료됐음을 확인한 뒤
`resolve --suite <경로> --exclude-pending --note "조사 내용"`으로 제외할 수 있다.
완결 증거는 resolve로 버릴 수 없다. 코드 drift 검사를 우회하지 말고 새 suite를 만든다.

## 남은 연구 범위

이 단계는 분류·회귀 파이프라인 구현과 기존 성공 archive 점검이다.
새 live 회귀/17축 AFS 비교, 규칙의 실제 양성·음성 사례 검증, 나머지 3개 유형의 관측 계약,
다중 seed 성능 검증과 범용 maze/terrain 연결은 별도 후속이다.
초기 성공·실패를 모두 보존하고, AFS의 성공 쪽 완화·경계·대안 탐색을 계속 평가한다.
로봇 점프 기술 개발을 AFS 측정의 선행 조건으로 삼지 않는다.
