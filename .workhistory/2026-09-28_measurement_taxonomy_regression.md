# 사용량·출처 보완, 근거 기반 유형 측정, 고정 예산 회귀 실행

## 요청과 기준

- 사용자: slalom 실제 성공 검토에 이어 제안한 후속 작업을 전부 시작하도록 요청.
- 세 범위: 종료 후 응답 사용량/소스 출처 보완, 유형 측정, 저장 사례를 실제 실행할 회귀 runner.
- 기준: `.blueprint/Failure_Case_Goal.md`, goal_outcome_v1, FAILURE_CASE_MEASUREMENT_PLAN.
- 시작 시 worktree clean. 기존 증거와 사용자 커밋은 보존. 이번 변경은 커밋/푸시하지 않음.
- 로봇 행동을 평가자가 지정하지 않음. GPT 프롬프트/제어기/목표/기술/정적 no_path 처리 변경 없음.
- 신규 유료 API/GPU 실행은 하지 않음. 기본 시뮬레이션 120초 제한과 GIF를 복구하지 않음.

## 1. 사용량 및 소스 출처

`failure_client/evaluation/call_usage.py` 추가. manifest-bound decision, pending response,
per-call journal을 observation ID로 합치고 response ID/token 수를 검증한다.
같은 응답의 중복 기록은 한 번만 세며 call-ID/response-ID/token 충돌은 합계에서 제외한다.
음수/비정수/total 불일치, 미기록/비정상 선택 로그를 경고한다.
이 비용 문제를 goal FAIL로 바꾸지 않는다. 검증된 중단 archive의 관측 비용도 유지한다.
EpisodeRecord에 usage_audit를 추가하고 캠페인/오프라인/회귀 요약에 누락 호출과 미측정 기록을 표시한다.

OpenAI Docs 스킬로 공식 usage 해석을 확인했다. input/output과 cached/reasoning 세부 값을 중복 합산하지 않는다.
출력 토큰은 visible text만이 아니다. 공식 근거: https://developers.openai.com/api/docs/guides/token-counting
모델 가격이나 청구 금액은 추정하지 않았다.

`goal_runner.py`의 새 protocol source_hashes에 `fixture_obstacles`를 추가했다.
과거 slalom protocol에 이를 소급 기입하지 않았다. 기존 동결 캠페인의 코드 검사도 우회하지 않는다.

## 2. 시간·행동·기하 근거를 갖는 유형 규칙

`failure_taxonomy.py`, profile `goal-behavior-v1` 추가.
종료 직전 5초의 goal 밖 정체(거리 변화 ≤0.15m, base 이동 ≤0.35m, 샘플 간격 ≤0.25s)를 공통 조건으로 한다.

- collision: move/navigate 단계의 알려진 정적 geom 접촉, 마지막 2초까지의 연관,
  지속 ≥0.2초/최대 힘 ≥10N. 발–바닥, movable box, push, 불완전 접촉을 원인으로 단정하지 않는다.
- obstacle_interference: 마지막 10초 blocked 계획/이동 결과 ≥2회 + base–투영 geometry 거리 ≤0.55m + 정체.
- goal_occupied: 전체 goal 원이 동일 upright 장애물의 투영 내부에 5초간 포함 + 낮은 바닥 + 정체.
  기울어진 물체의 점유는 UNKNOWN, 근접도에 한해서 보수적 AABB 사용.
- scene-config/XML, appended box qpos audit, evidence SHA/행/시간을 확인한다.
- PASS는 유형 N/A; 여러 유형 중첩은 primary UNKNOWN. 인과 상태 UNCONFIRMED.
- 도달 불가/사람 위험/인식 오류는 UNSUPPORTED. 부분 coverage는 null + 관측 하한으로 표시.
- no_path, 접촉 또는 GPT 설명만으로 도달 불가/원인을 확정하지 않는다.

`measure_failure_discovery.py --with-taxonomy`와 report의 taxonomy.json/HTML 추가.
새 obstacle 설정만 taxonomy_profile을 활성화한다. AFS 자신의 method/seed 기록을 파생 분류한 후
compact_evidence.operational_taxonomy로 다음 제안에 전달한다. raw checkpoint/원본 goal 결과,
외부 history 격리, Random 분포, 동등 유효 예산은 변경하지 않는다.
실패 메모리는 성공 대조/혼합을 유지하고 순수 실패 반복의 단일 일관 라벨만 case primary로 둔다.

## 3. 실행 가능한 회귀 suite

`experiments/behavior_regression.py`, `tools/run_behavior_regression.py` 추가.
기존 LocalGoalRunner, ResearchStore/ClientRepository transaction, atomic_json 재사용.

- plan은 read-only, init은 자산/코드 동결만 수행. run은 --live 및 로컬 키가 필요.
- 검증된 PASS/FAIL 원본 또는 memory.json index 입력. 원본 archive가 있어야 하며 해시 재검사.
- 동일 condition+scene baseline을 묶되 혼합 결과 보존. 복사 증거는 중복 제외.
- 원본 goal/scene/evaluation/call/simulation/push/HTTP 조건을 유지. 원본 로봇 자산 일치 필요.
- 현재 코드 버전과의 비교이며 역사적 코드 복원 아님. 모델 변경은 명시적 --model만 가능.
- 사례당 고정 1–10시도(기본2), 입력 최대32 archive. 제외도 예산 차감, 성공할 때까지 재시도하지 않음.
- intent 먼저 저장, atomic 관측 후 pending 해제. 중단 시 완결 증거 수집만 하고 재발송 금지.
- 살아 있을 수 있는 PID, 애매한 결과 없는 intent는 정지. 명시적 사후 제외/계속만 지원.
- 변경 자산/코드/원본, goal/scene 불일치, target 조건/model drift, 복사본 replay를 거부/제외.
- 상태/JSON/HTML/MP4 링크, protocol 차이, 관측 비용 및 누락을 출력. GIF 생성 없음.
- 비교는 RETAINED_PASS/FAIL, OBSERVED_IMPROVEMENT/REGRESSION, MIXED, PENDING/INCONCLUSIVE.
  COMPLETE는 고정 시도 완료이지 전부 성공 아님. 제외 포함 완료는 COMPLETE_WITH_EXCLUSIONS.
- 회귀 비용은 별도이며 AFS/Random 예산/결과에 무료로 추가하지 않음. 통계적 유의성 주장 없음.

## 실제 저장 증거의 오프라인 점검

성공 원본: `/workspace/g1_failure/runtime/robot_goal_agent/20260928T151133_926563Z`

- 새 보고서: `/workspace/g1_failure/runtime/failure_measures/20260928T164822_192417Z/report.html`
- VALID PASS 유지, API7회 중 usage7회. 입력164,000 / 출력2,971.
- 예전 decision-only6회 입력126,023/출력2,650과의 차이는 종료 후 응답37,977/321.
- 세 유형은 failure N/A, 진단 NOT_DETECTED. 원본 artifact는 변경하지 않음.
- 개발 중 첫 보고서 `/workspace/g1_failure/runtime/failure_measures/20260928T163906_653131Z`도 보존.

실패 원본: `/workspace/g1_failure/runtime/robot_goal_agent/20260928T093634_165692Z`

- 새 보고서: `/workspace/g1_failure/runtime/failure_measures/20260928T164825_734001Z/report.html`
- VALID FAIL 유지, API10회/usage10회, 입력315,307 / 출력7,780.
- 마지막5초 정체는 관측(거리 범위0.008930m/base 이동0.030000m, 잔여goal거리3.096218m).
- 추가 contact/repeated-blocked/goal-occupancy 요건이 없어 세 규칙 NOT_DETECTED, primary 미분류.
  '유형 미분류'는 goal 성공, 근본 원인 없음 또는 실패 유형 수0 확정을 뜻하지 않는다.

오프라인 초기화한 실제 자산 기반 suite:
`/workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928`

- slalom 성공 baseline1개, Luna, repeats2, 로봇 API 최대20회, AFS0회, simulation unlimited.
- 기존 G1 자산과 원본 resource hash 일치 검사 통과. READY, 로봇은 아직 시작하지 않음.
- 최종 frozen-suite preflight 통과, actual launches=0.
- 초기 상태 보고서: `/workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928/reports/20260928T165244_670872Z/report.html`.
- init/run/status/report와 재개 명령은 `docs/BEHAVIOR_TAXONOMY_AND_REGRESSION.md`에 한 줄씩 기록.
- obstacle pilot plan-only도 통과: taxonomy profile 활성, 6+6 최대12시도,
  robot120회/AFS2회 상한. 해당 명령은 파일/API/로봇 실행을 만들지 않았음.

## 검증

- 초기 비용/goal subset: 64 passed (22.13s).
- 사용량/유형/기존 지표·통로 subset: 79 passed (26.08s).
- 첫 회귀 실행 fault-injection subset: 14 passed (27.35s).
- 첫 전체 관련 검사: 415 passed (143.52s). API/GPU 없이 CPU·합성 archive/실행기 검증.
- 최종 추가 음성 사례 포함 전체: **421 passed (148.64s)**.
- Ruff 변경 Python 파일 검사: **All checks passed**. git diff --check 통과.

최종 전체 명령 (`scene2test` 디렉터리):

```bash
.venv/bin/python -m pytest tests/client tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_corridor_scene.py tests/test_goal_outcome_runner.py -q
```

검증은 토큰 중복/누락/충돌, PASS 보존, 접촉과 실패 분리, 다중 유형/기울어진 기하/성긴 state,
메모리/AFS 근거 연결, 고정 예산, 결과 비교, child 완료 후 crash 수집, 애매한 intent/PID,
해시·자산 drift, 원본 보호, 무키 CLI plan, 보고서/MP4 링크를 포함한다.

## 제한과 후속

새 live 회귀 성공이나 17축 AFS 우월성 증거는 아직 없다. 규칙3개는 합성 양성/음성과 기존 실험
오프라인 음성으로 확인한 첫 구현이며, 별도 실제 양성/대조 검증이 필요하다.
나머지3개 유형의 관측/판정 계약, 4/6 목표, 다중 seed 통계, 범용 terrain/maze 적재,
portable 외부 자산 복원과 core/media manifest 분리는 후속이다.
로봇 점프/새 조작 개발을 이번 AFS 계측/회귀 구현의 선행 조건으로 만들지 않았다.
