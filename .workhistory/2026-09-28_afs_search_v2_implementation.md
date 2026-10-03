# AFS v2 반영 — 행동 근거·가설 선택·반복 억제·탐색 측정

2026-09-28 UTC. 사용자 승인: AFS 관점 개선안을 코드에 반영.
[직전 검토](2026-09-28_afs_search_review.md)를 바탕으로 구현했다.

## 작업 범위와 보존

- 작업 시작 시 git status를 확인했다. 이전 통로5축 구현 등 미커밋 변경을 보존했다.
- 로컬 campaign AFS의 입력/선택/보고를 개선했다. 로봇 코드·모델·프롬프트·최종 목표·
  episode 예산·Random 분포를 이번 작업에서 바꾸지 않았다.
- API/GPU live 실행, 로봇 재실행, commit/push는 하지 않았다.
- 기존 runtime 결과/캠페인 checkpoint를 수정하지 않았다. 오프라인 파생 보고서만 새 폴더에 생성했다.
- 원본 FAIL/INCONCLUSIVE 분류를 바꾸지 않았으며 GIF를 활성화하지 않았다.

## 구현 상세

### 1. AFS 입력 근거

신규 `failure_client/methods/search_evidence.py`의 `compact_evidence`:

- 모든 action_window를 간단한 timeline으로 전달한다(현재 importer episode 상한20개).
- 상세 구간은 초기/종료, 사건 종류별 대표, 도구 오류/후속 행동, 실행 phase 진척 변화,
  나머지 시간대 대표로 최대12개 선택한다.
- 선택 이유/원본 구간 인덱스/종류별 전체와 선택 개수/상세 누락 수를 기록한다.
- 원본 파일 hash와 행 참조, 부분/누락 상태를 보존한다. observation window를 정확한
  실행 구간으로 재해석하거나 후속 이동을 자동 회복 성공으로 부르지 않는다.

`behavior_feedback.feedback_context`가 이 요약을 사용한다.
전체 episode 선택은 기존 latest/PASS/FAIL/최근 자료 정책과 history_limit을 유지한다.
다른 arm/seed나 외부 수동 기록을 캠페인 history에 몰래 섞지 않는다.

### 2. 행동 유사성과 중복 억제

`behavior-pattern-v1`은 도구 상태 전환 순서, 종료 이유, 유효 사건/접촉 대상,
목표 거리와 진척의0.5m bin, 상자 XY 변위0.1m bin 및 측정 availability를 사용한다.
연속 동일 행동 상태를 합치고 지지 접촉/정확한 접촉 횟수는 서명에서 제외한다.
states/actions가 없으면 패턴을 생성하지 않는다. 거친 bin은 경계 근처에서 바뀔 수 있으며
이를 원인/실패 유형/정확한 재현성 판정으로 주장하지 않는다.

최신 FAIL과 같은 패턴의 근방 실패3개 이상이면 정규화 최대축 거리0.05 이내 endpoint를
cooldown한다. 명시적 확인 반복과 관측 bracket 중점은 유지한다. 동일 파라미터 중복도 계속 거른다.

### 3. 실험 목적 중심 선택

`CampaignConfig.selection_policy`의 새 기본은 `hypothesis-v2`다.
Luna smoke/corridor 설정에 명시했지만 모델/예산 숫자는 유지했다.

- PASS 없을 때 success_probe 우선; 유사 실패 반복 시 cross_mechanism 우선.
- 같은 목적 내에서는 LLM의 가설 배열 순서를 우선하고 그 space의 low/high 사이에서
  novelty를 비교한다. 여전히 하나의 endpoint만 실행한다.
- 후보별 중복/cooldown 제외 사유, eligible 후보, 우선 mode 중 후보가 없던 것,
  선택 mode, anchor case/episode, 가설 ID를 `selection_audit`에 기록한다.
- boundary 슬롯은 mixed case 반복을 먼저 보고, 없으면 관측 bracket 중점,
  그마저 없으면 새 가설 요청을 한다. repeat 슬롯도 mixed case를 우선한다.
- 독립 탐색/반복 슬롯은 유지하고 모든 실행이 예산을 소비한다.
  후보 없음/API 불명 오류의 자동 Random 대체·재전송은 추가하지 않았다.
- `novelty-v1`로 거리 우선 ranking을 비교할 수 있지만 이것은 옛 코드 전체 재현 옵션이 아니다.

AFS 프롬프트의 선택 지침과 host ranking을 같이 변경했다. 기존 `spaces` 출력 schema,
허용 축 enum, 범위/근거 ID/hash 검증은 유지했다.
OpenAI Docs skill에 따라 [공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를
조회해 required 필드/추가 필드 금지 계약을 확인했다. 모델을 바꾸거나 새 API 옵션을 넣지 않았다.

### 4. 탐색 지표와 가설별 결과

신규 `failure_client/reporting/search_diagnostics.py`:

- method/seed별 최초 관측 PASS와 최초 관측 bracket 시점의 유효 rollout/총 시도/관측 로봇 비용.
- 현재 bracket 양끝 반복 수·폭과 예산별 변화, 혼합 반복 case.
- 관측된 실패 행동 패턴 수/반복 비율, 패턴 미상 실패 수.
- campaign의 선택 가설/반증 조건을 실제 episode 결과와 anchor 대비 목표 거리 변화에 연결.
  자유문 가설의 진위/인과는 자동 판정하지 않는다.

P0 FDR/Gain/6종 coverage 정의는 그대로다. 새로운 행동 패턴 수를 공식 유형 수로 세지 않는다.
첫 bracket이 추후 혼합 반복으로 사라지는 경우를 곡선과 현재 bracket으로 함께 표시한다.
보고서(`--with-memory` 포함)에 HTML 요약표, 상세 JSON, `search_diagnostics.csv`를 추가했다.
campaign report뿐 아니라 일반 오프라인 measurement report에도 적용된다.

### 5. 관측 비용 누락 보완

`goal_run_reader`의 INCONCLUSIVE 조기 반환 시 verified decision usage를 읽어
input/output token 합계와 관측 usage 건수를 보존한다. 손상/중복 usage는 unknown+경고로 남긴다.
측정된 비용이 있다는 이유로 interrupted rollout을 VALID/FAIL로 바꾸지 않는다.
manifest 미완성·응답 없는 요청·옛 checkpoint의 비용을 추정하거나 자동 덮어쓰지 않는다.
campaign summary는 robot_tokens와 AFS request UTF-8 bytes를 추가한다. bytes는 token 수가 아니다.

## 검증

유료 API/로봇 동작 없이 실행했다.

1. 초기 선택/메모리/재개/정합성 테스트: **88 passed, 38.82s**.
2. Client 전체 + behavior AFS/CLI/request + 통로 기하 + goal-outcome runner:
   **294 passed, 103.62s**.
   명령: `.venv/bin/python -m pytest tests/client tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_corridor_scene.py tests/test_goal_outcome_runner.py -q`
3. 최종 보고서 표시/설정 변경 후 해당 테스트 재검증: **106 passed, 51.17s**.
   명령: `.venv/bin/python -m pytest tests/client/test_afs_search_improvements.py tests/client/test_discovery_measures.py tests/client/test_behavior_memory.py tests/client/test_luna_pilot.py tests/client/test_corridor_campaign.py -q`
4. 신규9개 테스트는 후반 행동 보존, event quota, 누락 상태, support-count 불변 서명,
   도구 순서 구분, 목적/가설 순위, cooldown/대안/반복, mixed 우선,
   bracket 철회·비용·resume·보고서 연결을 다룬다.
5. 변경 Python 파일 Ruff 검사 통과, `git diff --check` 통과.

### 실제 저장 기록의 오프라인 확인

Luna 통로 원본: `/workspace/g1_failure/runtime/robot_goal_agent/20260928T093634_165692Z`.

- archive는 계속 VALID/FAIL.
- action_timeline10개 전체, blocked endpoint observation_version6/9,
  version7의 move를 새 입력에 포함하는 assert 통과.
- 상세 구간12개; search state=no_success_control; success_probe 우선.
- 관측 입력 JSON UTF-8 35,187bytes, 요청 JSON43,589bytes. 실제 token/청구금액이 아니다.
- 새 입력으로 LLM 제안을 받거나 로봇을 실행하지 않았다.
- 수동 실행은 method=unassigned로 두며 캠페인 warm history로 넣지 않았다.

과거 중단 기록: 기존 AFS campaign의 attempt_00010/rollout을 읽기만 했다.
INCONCLUSIVE/inconclusive_execution 판정은 그대로이며,
기록된7회 usage의 input149,560/output4,947tokens가 이제 reader에서 보존된다.
이 합계는 미응답 요청을 포함한 전체 비용이 아니고 옛 campaign 저장 값은 수정하지 않았다.

### 새 파생 보고서

명령: `.venv/bin/python tools/measure_failure_discovery.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260928T093634_165692Z --with-memory`

- `/workspace/g1_failure/runtime/failure_measures/20260928T102859_582606Z/report.html`
- valid1, excluded0; comparison=missing_comparison_design; cases1, brackets0.
- `search_diagnostics.csv` 존재 및 보고서 manifest52개 hash 검증 통과.
- 원본 MP4를 참조하며 새 로봇 영상/GIF는 만들지 않았다.
- 이 단일 기록 보고서는 AFS 성능 비교나 성공/실패 경계 확보 결과가 아니다.

### 실행 계획 점검

`.venv/bin/python tools/run_afs_pilot.py --config config/behavior_afs_corridor_luna.json`
→ PLAN_ONLY, 새 파일/API/GPU 실행 없음.
Luna/Luna, 5축, hypothesis-v2, AFS/Random 각6회, 로봇 최대120회 + AFS 최대2회,
시뮬레이션 시간 상한 없음이 출력됨을 확인했다.

## 문서·후속 경계

`docs/AFS_SEARCH_V2.md`에 설명/한계/복사 가능한 명령을 기록하고 README·campaign/corridor·
측정 계획·로드맵·AGENTS를 갱신했다. 과거 동결 캠페인은 새 코드로 강제 재개하지 않는다.

이번에는 최신 case를 anchor로 유지했다. LLM의 임의 과거 anchor 선택, 학습된 실패 확률,
자동 causal adjudication, 추가 장면 축/6종 detector/회귀 실행기는 후속 범위다.
정적 코드/합성 회귀 통과는 실제 AFS 제안 품질·Random 대비 Gain·GPU 성공률·요금 절감
달성을 의미하지 않는다. 다음은 고정 조건/예산의 새 AFS pilot으로 선택 품질을 확인하는 일이다.
