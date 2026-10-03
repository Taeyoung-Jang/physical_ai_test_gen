# P2 — 행동 근거 기반 AFS/Random 로컬 캠페인

2026-09-27 UTC.

## 요청과 시작 상태

사용자의 “네 다음 단계 진행하세요”에 따라 P1 다음인 P2를 진행했다.
`AGENTS.md`, `.blueprint/Failure_Case_Goal.md`, 측정 계획과 통합 감사/로드맵을 확인했다.
시작 시 working tree는 clean이었고 앞선 P1은 저장소에 반영된 상태였다.

확정 범위는 현재 실행 가능한 3축 clear-path 장면의 로컬 캠페인이다.
로봇 기술·goal 계약·로봇 프롬프트·서버 프로토콜을 바꾸지 않고,
P0 유효성/지표와 P1 행동 근거/메모리를 다음 후보 선택 및 동일 예산 비교에 연결했다.
이 턴에는 유료 API/GPU rollout을 실행하지 않았다.

## 구현

### 고정된 비교 계약

- `scene2test/src/failure_client/experiments/research_protocol.py` 추가.
- strict config: seed 목록, method·seed별 유효 예산, 전체 시도 상한, cold start,
  AFS 요청 상한, 모델, 시간/호출 예산, 전략 순환 순서, 로봇 자원 위치.
- 현재 domain은 box mass 0.2–10 kg, box/floor friction 각각 0.05–1.5로 고정.
- 공통 초기 uniform 장면은 양쪽에서 별도로 실행해 각각 예산을 차감한다.
- Random은 전체 domain에서 독립 uniform draw. AFS가 좁힌 영역을 Random 분포로 쓰지 않는다.
- method 시작 순서는 seed로 정하고 실행을 교차한다. robot 반복 seed를 설정할 기능은
  현재 runner에 없으므로 임의로 설정했다고 표시하지 않는다.
- init에 설정·코드·의존성 버전·XML/YAML/mesh/ONNX 해시를 저장하고 재개/실행 전후에 재검사.
  알 수 없는 XML include/비-mesh 외부 자산은 임의로 건너뛰지 않고 거부한다.
- 원격 모델 가중치나 계정 접근 가능성을 검사/동결한 것은 아니다. 반환 모델·관측 condition의
  변경이 발견되면 원 결과를 보존하고 비교를 중단한다.

### 행동 AFS 피드백

- `failure_client/methods/behavior_feedback.py` 추가.
- 기존 behavior-AFS의 Proposal/Space, hash 고정 request builder, 범위/증거 ID 검증 재사용.
- 입력: 자기 method·seed의 P1 행동 구간, 상자 변위, 상태/도구/접촉 근거,
  성공/실패/혼합 반복 집계, 실제 observed bracket, SceneGraph와 고정 로봇/목표 조건.
- 다른 method 또는 다른 seed의 결과를 읽어 AFS를 강화하지 않음. 외부 warm history도 없음.
- 기본 상세 episode 최대 8개, 구간 최대 12개/episode. 최신 + 가능한 PASS/FAIL을 우선하고
  선택 개수/전체 개수/제한을 제공. 사례별 전체 반복 집계·bracket도 보관/전달.
- `llm → boundary → exploration → repeat` 4개 slot 순환.
  boundary bracket이 없으면 선언된 방식대로 LLM probe를 요청하며 Random으로 몰래 대체하지 않음.
- LLM의 한쪽/양쪽 탐색 공간에서 새 endpoint 선택. 같은 행동 요약의 근처 실패가 3회 이상이면
  그 근처 endpoint에 cooldown. 의미상 원인/교정된 실패 확률로 주장하지 않음.
- P1의 같은 조건·단일 축·반대 결과 bracket만 중점 probe에 사용하고 혼합 반복은 확정 경계로 쓰지 않음.
- CandidateObservation 및 작은 observe/checkpoint adapter 재사용.
  로컬 scene 계약이므로 기존 HTTP registry의 FailureDiscoveryMethod plugin으로 등록했다고 주장하지 않음.

### 내구성·중단 재개

- `failure_client/storage/research_store.py`: 기존 ClientRepository의 SQLite transaction을 재사용.
  별도 campaign DB에 checkpoint와 append-only transition ledger를 한 트랜잭션으로 저장.
- OS flock으로 같은 campaign의 중복 driver 방지. 전역 GPU admission 서비스는 아님.
- `failure_client/experiments/research_campaign.py`: 호출 전 intent, proposal 응답/검증,
  rollout 상태, episode 수집·observe의 atomic checkpoint, 전체 시도/유효 수 구분.
- 완료된 archive는 재실행 없이 수집. API 응답이 저장됐으면 그 응답을 다시 검증.
- 완료 여부 불명인 API/rollout은 NEEDS_ATTENTION. 자동 재전송·자동 Random 대체 없음.
- 명시적인 `resolve --abandon-pending`은 사용자가 실제 동작 종료를 확인한 뒤만 사용하도록 문서화.
  살아 있는 PID/완결 archive/검증된 proposal은 무시하지 않음.
- 알려진 비용과 usage/wall time 누락 건수를 함께 표시. 불명 비용을 무료로 간주하지 않음.
- 실제 유효 기록의 robot condition이 바뀌면 기록을 삭제하거나 유리한 표본만 제외하지 않고
  비교 INCOMPLETE로 남김. 요청한 후보와 다른 장면/설정은 campaign-contract-invalid로 구분.
- 새 목표 실행에 속하지 않는 접촉/legacy/incomplete를 goal FAIL로 승격하지 않음.

### 로봇 실행 경계와 CLI

- `local_goal_adapter.py`: 기존 로봇 CLI를 subprocess로 한 번만 실행.
  고정된 새 run 위치, argv/scene/process ID/로그/종료 receipt 저장.
- `tools/run_robot_goal_agent.py`는 `--run-dir` 옵션만 추가. 기본 output-root/기존 CLI는 유지.
  goal_runner 본체·정책·기술·목표 evaluator는 수정하지 않음.
- subprocess watchdog/Ctrl+C는 INCONCLUSIVE로 분리하고 이번 invocation을 중단.
  watchdog은 task simulation budget과 다르며 둘 다 기본 무제한을 유지.
- `tools/run_afs_benchmark.py`: init/run/status/report/resolve.
  init/status/report는 API/GPU 실행 없음. run은 --live 및 로컬 환경 API key를 요구.
- `config/behavior_afs_benchmark.json`: seed 17, 각 arm 유효 8회/최대 시도 12회,
  로봇 호출 10회/episode, AFS 최대 8회 요청.
  전체 상한은 로봇 API 240회 + AFS 8회이며 실제 요금이 아님.
- P0 report에 campaign 진행·비용 섹션 추가. 원본 P0 계산 계약은 유지.
  보고서에 frozen protocol/ledger와 해시 포함, opt-in P1 memory 및 기존 MP4 참조.
  GIF 생성은 추가하지 않음.

## 공식 문서/스킬 적용

LLM 연결에 OpenAI Docs 스킬을 사용했다. [Structured Outputs 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs)의
required/additionalProperties/strict schema와 거절·미완료 응답 처리 기준을 확인했다.
기존 `store=false`/strict schema/context hash를 유지하고 host 검증을 재사용했다.
GPT-6 모델을 다른 모델로 교체하거나 실제 접근 가능성을 확인하는 API 호출은 하지 않았다.
API-key helper는 도구 목록에 없었고 개발/검증은 모두 오프라인으로 수행했다.

## 검증과 수정 과정

추가: `tests/client/test_research_campaign.py` (최종 parameterization 포함 39개).
실제 GPU/LLM 없이 합성 v5 archive와 fake proposer, subprocess double, fault injection을 사용했다.

1. 초기 32개 테스트: **32 passed in 32.50s**.
2. 다중 seed·근거 변경·strict schema/제안 영향·제안 상한·활성 child 재개 보호 추가 후:
   **37 passed in 36.34s**.
3. subprocess 종료/timeout receipt 검증 2개 추가 후 기존 테스트와 통합 실행:

```bash
PYTHONPATH=src .venv/bin/pytest tests/client tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot_goal_agent.py tests/test_robot_request_timing.py -q
```

**231 passed, 1 skipped in 74.65s**.
skip은 `RUN_ROBOT_TIMEOUT_GPU=1`을 명시해야 하는 기존 32초 GPU 지연 실험이다.

주요 검증:

- 양쪽 8회 유효 예산, 공통 cold start 별도 과금, 독립 Random 표본, 반복도 예산 차감.
- 중간 종료/재개와 연속 실행의 후보 순서 일치, 완료 campaign 재실행 방지.
- archive 생성 직후 crash, API 응답 저장 직후 crash에서 외부 실행/호출을 반복하지 않음.
- 미완료/모호한 실행의 자동 재개 거부와 명시적인 해소/제외.
- refusal/incomplete/stale context/추가 robot field 제안 거부 및 비용 보존.
- invalid attempt cap, API request cap, watchdog의 INCONCLUSIVE 처리.
- 실제 record condition 차이의 보존·비교 중단, 잘못된 장면과 중복 core evidence 제외.
- 자기 arm/seed 근거만 전달, 실제 LLM 공간 변화가 다음 환경 후보를 변경.
- mixed repeat가 경계로 잘못 사용되지 않음, observe replay idempotency와 충돌 거부.
- 동시 driver 잠금, 오류 secret redaction, 코드/원본 증거 변경 탐지.
- 새 report의 체크섬, P1 memory/MP4 참조, GIF 제외.

개발 중 Ruff import 정렬/긴 줄/사용하지 않는 import를 정리했다.
코드 검토로 manifest가 있어도 child가 살아 있는 경우 새 rollout을 시작하지 않도록 보강했고,
condition 변경과 요청 cap 소진을 캠페인 미완료로 남기도록 했다.
최종 변경 Python 파일 9개의 Ruff check/format 검사와 git diff --check가 통과했다.
문서·작업 이력의 로컬 링크 35개도 존재를 확인했다.

## 실제 자원으로 수행한 오프라인 smoke

```bash
uv run --no-sync python tools/run_afs_benchmark.py init --config config/behavior_afs_benchmark.json
```

생성 경로:

`/workspace/g1_failure/runtime/afs_benchmark/20260927T153403_953634Z`

이후 같은 캠페인에 status 및 report --with-memory를 실행했다.
보고서 경로:

`/workspace/g1_failure/runtime/afs_benchmark/20260927T153403_953634Z/reports/20260927T153514_845901Z/report.html`

상태 READY, AFS/Random 각각 valid 0/8, attempt 0, AFS request 0.
보고서 FDR은 null, 비교는 not_comparable, memory는 빈 상태다.
이것은 실행 전 준비/보고 기능 검증이며 로봇 실패율이나 AFS 성능 결과가 아니다.
초기화는 로봇 자원 파일/설치 패키지를 읽었지만 모델을 GPU에 로드하지 않았다.

첫 smoke의 source 124개·robot resource 52개 해시를 재계산해 일치를 확인했고,
상위/하위 보고서 manifest의 checksum entry 11개도 검증했다.
그 후 로봇 CLI의 긴 줄을 포맷 정리해 source hash가 바뀌었다. 기존 smoke를 덮어쓰지 않고
최종 코드로 다음 새 캠페인을 초기화했다:

`/workspace/g1_failure/runtime/afs_benchmark/20260927T154345_983631Z`

이 폴더도 READY/실행 0건이다. 첫 smoke 폴더는 개발 검증 이력으로 보존하며
현재 코드의 live 재개 대상으로 사용하지 않는다. 실행 시 코드가 또 바뀌었다면 새 init이 필요하다.

## 남은 범위/다음 단계

- [실행 문서](../scene2test/docs/BEHAVIOR_AFS_CAMPAIGN.md)의 설정/상한을 확인한 뒤 소규모 live pilot.
  전체 16회부터 무조건 돌리는 대신 --max-new-attempts 2로 운영 연결을 점검할 수 있음.
- 연구 목표 30% FDR/Random 대비 20%/4종 달성은 아직 실험하지 않았음.
- 초기화를 통과해도 GPU/EGL/네트워크/계정 모델 접근이 검증된 것은 아님.
- 외부 모델의 확률성/지연, search seed와 robot seed 차이, 부분 비용·원격 모델 가중치 동결 한계를 공개.
- 6종 detector·확장 기하·이미지 기반 AFS·자동 회귀 실행은 미구현.
- core/media manifest 분리와 로봇 최종화 순서 개선도 후속 작업. 기존 missing manifest를 복구하지 않음.
- 원본 실험 자료는 수정하지 않았고 git commit/push는 하지 않음.
