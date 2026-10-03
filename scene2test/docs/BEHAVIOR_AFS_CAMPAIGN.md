# P2 — 행동 근거 피드백·AFS/Random 캠페인

2026-09-28 갱신: 새 캠페인은 [가설 중심 선택 v2](AFS_SEARCH_V2.md)를 기본 사용한다.
전체 행동 요약/중요 사건, 행동 패턴 cooldown, 목적 우선 선택, mixed 반복 우선,
탐색 보조 지표와 INCONCLUSIVE 관측 토큰을 추가했다. 아래는 초기 구현 설명이며,
선택 세부사항은 v2 문서가 우선한다. 기존 frozen campaign을 새 코드로 강제 재개하지 않는다.

첫 제안의 근거 ID 한 글자 누락만 명시적으로 복구하는 예외 절차는
[AFS_EVIDENCE_RECOVERY.md](AFS_EVIDENCE_RECOVERY.md)를 참고한다. 원본 보존·비용 계승·별도
코드 고정·operator-assisted 표시가 필수이며 일반 drift 우회나 자동 재시도가 아니다.

2026-09-27 UTC. 현재 3축 goal-agent backend를 대상으로 한 **첫 구현**이다.
[P0 측정기](FAILURE_DISCOVERY_MEASURES.md), [P1 행동 근거/메모리](BEHAVIOR_FAILURE_MEMORY.md)를
실행·관측·다음 제안에 연결했다. 새 서버나 로봇 기술은 추가하지 않았다.
구현·합성 테스트와 실제 GPU/LLM 성능 증거는 구분한다. 이번 구현 작업에서는 유료 API나 로봇을 실행하지 않았다.

## 동작 흐름

```text
설정·코드·로봇 자원 해시 고정
  → AFS/Random 초기 장면을 각각 독립 실행
  → 기존 목표 평가 + archive 검증
  → AFS 자기 seed의 행동 근거·성공/실패/혼합 반복·관측 bracket
  → LLM 제안 / 경계 중점 / 독립 탐색 / 재현 반복
  → 유효 예산까지 교차 실행 → P0 비교 지표와 P1 자산 보고서
```

AFS는 장면 변수만 바꾼다. 로봇에게 이동 방향, 접촉 금지, 상자 배치 위치나 새로운 성공 조건을 지시하지 않는다.
기존 `goal_outcome_v1`의 최초 목표가 최종 판정 기준이다. 접촉·낙상·기술 실패는 행동 근거다.

## 기본 실험 조건과 비용 상한

설정 파일: [`config/behavior_afs_benchmark.json`](../config/behavior_afs_benchmark.json).
수정은 **init 전에** 한다. 시작한 캠페인의 예산·모델·설정은 변경할 수 없다.

| 항목 | 기본값 |
|---|---|
| search seed | `[17]` — 단일 seed 개발용 pilot |
| 유효 실행 예산 | method·seed별 8회, 양쪽 합계 16회 |
| 전체 rollout 시도 상한 | method·seed별 12회, 양쪽 합계 24회 |
| 공통 초기 장면 | seed별 uniform 2개; 양쪽에서 각각 실행하므로 총 4회 예산 소비 |
| AFS 요청 상한 | seed별 8회 |
| 로봇 모델 / AFS 모델 | 각각 `gpt-6-astra` |
| 로봇 episode 호출 예산 | 최대 10회 |
| 환경 축 | 상자 질량 0.2–10 kg, 상자/바닥 마찰 각각 0.05–1.5 |
| 로봇 조건 | push 허용, 기존 내부 계획기/관측/목표 계약 유지 |
| simulation 시간 | `null`: 무제한. 기본 120초 제한은 없음 |
| HTTP timeout | 로봇 300초, AFS 300초; 자동 API 재시도 없음 |
| 외부 process watchdog | `null`: 없음. 선택 시 task budget과 별개인 운영 중단 |

기본 전체 상한은 **로봇 API 240회 + AFS API 8회**다. 실제 호출 수나 요금이 아니다.
중단된 요청의 사용량이 없으면 비용을 0으로 간주하지 않는다. 상태/보고서에 알려진 토큰·wall time과
누락 건수를 구분한다. API 계정 청구 비용까지 완전하게 수집하는 기능은 아니다.

`max_new_attempts`는 한 번의 명령에서 시작할 rollout 수 제한이다.
캠페인의 전체 예산이나 각 episode의 목표 평가 예산을 바꾸지 않는다.
중단된 실행의 수집만 할 때는 `0`을 사용할 수 있으며, 불확실한 외부 작업을 재실행하지 않는다.

## 실행 명령 — 각 코드 블록은 한 줄

`/workspace/g1_failure/src/physical_ai_test_gen/scene2test`에서 실행한다.
RunPod/Linux의 기존 CUDA·MuJoCo·GR00T 설치 환경을 사용한다. init은 파일/패키지를 확인할 뿐
GPU 보행·EGL 렌더링·계정 모델 접근까지 검증하지 않는다.

### 한 명령으로 전체 실행 — 2026-09-28 추가

[`tools/run_afs_pilot.py`](../tools/run_afs_pilot.py)는 아래 수동 절차를 묶은 실행 스크립트다.
기존 캠페인·로봇 실행기·측정기·메모리를 재사용하며 별도 검색 알고리즘을 추가하지 않는다.

작업 디렉터리:

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

계획·최대 호출 예산만 확인한다. 키가 설정되어 있어도 `--live`가 없으면 파일 생성·API·GPU 실행이 없다.

```bash
uv run --no-sync python tools/run_afs_pilot.py
```

`OPENAI_API_KEY`가 로컬 환경 변수에 설정된 상태에서 **아래 한 줄로 전체 실행**한다.
기본 설정의 전체 유효 예산은 AFS 8회 + Random 8회다. 호출 상한은 로봇 240회 + AFS 8회이며
실제 사용량/요금이 아니다. 무제한 simulation 조건은 유지하고 새 기본 시간 제한을 넣지 않았다.

```bash
uv run --no-sync python tools/run_afs_pilot.py --live
```

진행 순서:

1. 기본 설정·코드·자원을 확인하고 `/workspace/g1_failure/runtime/afs_benchmark/<timestamp>`에 새 캠페인을 만든다.
2. 먼저 최대 2회 신규 rollout을 실행하고 `INITIAL_REPORT`를 생성한다.
3. 실행 기록/계약이 정상이면 같은 고정 예산 안에서 남은 실험을 자동 진행한다. 확인 질문은 없다.
4. 끝나면 행동 메모리를 포함한 최종 `REPORT`와 `PILOT_SUMMARY`를 출력한다.

실제로는 rollout을 한 번씩 수행하며 유효성을 확인하므로, 첫 회의 실행 오류를 보고 두 번째를
무조건 시작하지 않는다. **유효한 목표 FAIL은 정상 탐색 결과로 받아 계속한다.**
INCONCLUSIVE/INVALID/누락 기록, API 오류, watchdog/Ctrl+C, 코드/자원 변경은 추가 실행을 중단한다.
기존 수동 `run`보다 보수적인 자동 실행 정책이며 전체 시도 상한/유효 예산은 바꾸지 않는다.
2회 점검은 자동 기록 검사다. MP4를 사람이 검토하거나 로봇의 보행 성능을 승인한 것으로 해석하지 않는다.
기본 첫 2회는 cold start이며, 그 시점에 적응형 AFS를 확인한 것은 아니다.

다른 설정을 쓰려면 새 캠페인 생성 전에 `--config 경로`를 지정한다. 기본 파일은 실행 위치와
무관하게 이 프로젝트의 `config/behavior_afs_benchmark.json`을 찾는다.
`--output-dir 새경로`로 새 캠페인 위치를 지정할 수 있으나 기존 폴더는 덮어쓰지 않는다.

중단 후 원인을 확인하고 **같은 폴더로 재개**하려면 아래 `CAMPAIGN_DIR`을 실제 출력 경로로 바꾼다.

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --campaign CAMPAIGN_DIR
```

재개는 고정 설정을 사용하므로 `--config`를 함께 지정할 수 없다. 먼저 pending 결과를 새 호출 없이
수집/검증하고, 완료 불명인 호출은 자동 재전송하거나 버리지 않는다. 수집한 결과가 제외 상태면
추가 실행 전에 다시 멈춘다. 완결된 캠페인은 로봇을 재실행하지 않고 보고서만 생성한다.
코드 변경 전 캠페인은 새 코드로 강제 재개하지 말고 새 캠페인을 만든다. 스크립트 자체도 source hash에 포함된다.

오류 시에도 가능한 범위에서 부분 보고서를 생성한다. `REPORT` 출력만으로 실험 완료를 판단하지
말고 `PILOT_EXIT_CODE`와 캠페인 상태를 함께 확인한다. 정상 완료 0, 오류/미완료 2,
스크립트가 직접 받은 KeyboardInterrupt는 130이다. 로봇 실행기가 처리한 Ctrl+C는 운영 중단으로 2가 될 수 있다.
기록 무결성이 깨져 보고서 생성도 불가능하면 그 오류를 별도로 보존하며 성공으로 표시하지 않는다.

일괄 실행 로그는 매 실행마다 새 `pilot_runs/<timestamp>/`에 남는다:

- `events.jsonl`: 실행 진행 이벤트. 상세 로봇 로그는 기존 attempt의 `process.log`를 본다.
- `initial_check.json`: 첫 점검 후 상태. 점검 전에 오류가 나면 생성되지 않는다.
- `summary.json`: 최종 상태·호출 집계·종료 코드.
- `error.json`, `report_error.json`: 오류가 있을 때만 생성되는 비밀값 제거 예외/스택 정보.

MP4·원본 결과는 기존 `attempts/.../rollout/`에 보존하며 GIF는 생성하지 않는다.
같은 GPU에서 다른 캠페인·수동 로봇 실행을 동시에 시작하지 않는다.

### 1. 초기화 — API/GPU 실행 없음

```bash
uv run --no-sync python tools/run_afs_benchmark.py init --config config/behavior_afs_benchmark.json
```

`AFS_CAMPAIGN=/workspace/g1_failure/runtime/afs_benchmark/<timestamp>`가 출력된다.
아래의 `CAMPAIGN_DIR`에는 **그 폴더의 실제 경로를 직접 넣는다**. 셸 변수 이름이 아니라 대체할 표시다.
init은 새 폴더만 허용한다. ONNX/XML/mesh/YAML 누락, 알 수 없는 외부 XML 의존성은 실행 전에 거부한다.

### 2. 우선 최대 2개 rollout 실행 — 유료 API/GPU 사용

OPENAI_API_KEY는 기존처럼 로컬 환경 변수에 설정한다. 설정 파일·CLI 인자·작업 이력에 키를 넣지 않는다.

```bash
uv run --no-sync python tools/run_afs_benchmark.py run --campaign CAMPAIGN_DIR --live --max-new-attempts 2
```

처음 2회는 교차 순서에 따라 양쪽 cold start이며 아직 적응형 제안에 도달하지 않을 수 있다.
중간 진행은 `CAMPAIGN_EVENT=...`로 표시한다. 각 로봇 실행의 상세 출력은 attempt의 `process.log`에 남는다.
상태와 영상을 확인한 뒤 같은 명령을 반복하거나, 아래처럼 남은 캠페인 전체를 진행한다.

```bash
uv run --no-sync python tools/run_afs_benchmark.py run --campaign CAMPAIGN_DIR --live
```

같은 `run` 명령이 재개 명령이다. 완료된 캠페인을 다시 실행해도 새 rollout을 시작하지 않는다.
전체 캠페인을 다시 시험하려면 새 폴더로 init한다.
다른 캠페인이나 수동 로봇 실행과 GPU를 동시에 사용하지 않는 것이 좋다.
잠금은 **같은 캠페인의 중복 실행**을 막으며, 모든 프로그램에 대한 GPU 전역 스케줄러는 아니다.

### 3. 상태 조회 — API/GPU 실행 없음

```bash
uv run --no-sync python tools/run_afs_benchmark.py status --campaign CAMPAIGN_DIR
```

- `READY`: 초기화 완료/이번 명령의 실행 수 제한/운영 중단 후 대기.
- `RUNNING`: 마지막 기록이 실행 중. 프로세스 crash 뒤에도 이 값이 남을 수 있다.
- `NEEDS_ATTENTION`: API/rollout 완료 불확실, 잘못된 제안, 증거·코드 변경 등으로 확인 필요.
- `INCOMPLETE`: 전체 시도/제안 상한 소진 또는 실험 계약/반환 모델 조건 변경. 비교 완료 아님.
- `COMPLETE`: 양쪽의 모든 seed가 선언한 유효 실행 수를 채움. AFS 우월성이나 목표 수치 달성을 뜻하지 않음.

### 4. 결과/행동 근거 보고서 — API/GPU 실행 없음

```bash
uv run --no-sync python tools/run_afs_benchmark.py report --campaign CAMPAIGN_DIR --with-memory
```

`REPORT=.../reports/<timestamp>/report.html`을 연다. 유효/제외 수, FDR/Gain,
비교 가능 여부, 요청/비용 누락을 확인한다. `행동 구간·실패 메모리·관측 경계` 링크에서 P1 근거를 본다.
부분 실행도 보고 가능하지만 같은 유효 예산을 채우기 전에는 공식 Gain 비교 완료로 표시하지 않는다.
6종 detector가 아직 없으므로 실제 coverage는 계속 미측정이다.

MP4는 각 `attempts/attempt_XXXXX/rollout/rollout.mp4`에 기존 runner가 저장한다.
P1 보고서는 기본 원본 MP4를 참조한다. GIF는 생성하지 않는다.
원본 로봇 기록은 이 도구가 수정하거나 불완전 결과를 복원하지 않는다.

## 후보 선택과 근거 입력

Random은 AFS가 좁힌 구간이 아니라 사전에 고정한 전체 3축 domain의 독립 uniform 표본을 사용한다.
공통 cold start 이후 Random의 표본은 AFS 결과와 무관하다. 각 seed의 시작 method 순서를 seed로
정한 뒤 양쪽을 교차 실행한다. 이는 시간 변화의 영향을 줄이는 설계이지 API latency를 동일하게 만드는 기능이 아니다.

AFS는 기본적으로 다음 4개 slot을 순환한다. cold start/반복/경계/독립 탐색 모두 유효 예산에 포함한다.

1. `llm`: 최신 행동 근거로 기존 behavior-AFS schema의 1–4개 탐색 공간을 요청한다.
   호스트가 context hash, 증거 ID, 허용 축/범위/형식을 검증하고, 모든 공간의 low/high 후보를
   모아 **다음 rollout에 사용할 endpoint 하나만** 고른다. 공간당 하나나 양 끝점 동시 실행이 아니다.
   각 후보는 지정된 한 축만 바꾸며 나머지 축은 최신 장면 값으로 고정한다.
   중복/cooldown 제외 후, 기존 관측 장면까지의 최소 정규화 거리가 가장 큰 후보를 선택한다.
   거리는 각 축의 전체 허용 범위로 정규화한 차이 중 최댓값이며, 동점이면 제안 순서
   (공간 순서, low 먼저)를 유지한다. 실패 확률 예측 점수가 아니라 신규성 휴리스틱이다.
2. `boundary`: P1이 확인한 동일 조건·단일 축의 반대 결과 bracket에서 미측정 중점을 선택한다.
   bracket이 없으면 LLM에 새 probe를 요청한다. 이것은 미리 선언한 정책이며 몰래 Random으로 바꾸는 fallback이 아니다.
3. `exploration`: 전체 domain에서 독립 uniform 탐색을 한다.
4. `repeat`: 성공/실패 대조를 순환하며 현재 관측 횟수가 적은 사례를 재현 확인한다.
   혼합 결과도 유지한다. 반복을 새 실패 메커니즘으로 세지 않는다.

LLM 입력에는 로봇/목표 조건, SceneGraph, 허용 축, 남은 유효 예산, 사례별 PASS/FAIL 횟수,
물체 변위, 행동·접촉·낙상·도구 구간과 파일/행 근거를 제공한다.
**다른 method나 다른 seed의 결과는 전달하지 않는다. 외부 warm history도 사용하지 않는다.**
기본 최대 8개 episode의 상세 근거를 선택하되 최신 기록과 가능한 PASS/FAIL 대조를 우선한다.
구간은 실행당 비지지 접촉 포함 최대 12개를 전달하고 전체 수/제한을 공개한다.
전체 기록은 원본에 남으며, 모든 사례의 반복 집계와 bracket도 입력에 포함한다.
현재 AFS 입력은 계측/구조화된 기록이며 MP4나 camera 이미지를 AFS 모델에 보내는 기능은 아니다.
로봇 쪽의 기존 RGB 입력은 그대로 유지한다.

같은 행동 요약의 근처 실패가 3회 이상이면 그 근처 LLM endpoint에는 cooldown을 적용한다.
이는 제한된 진단 휴리스틱이며 실패 원인 검출기가 아니다. 중복/범위 오류/모든 endpoint 거부/LLM 오류 시
자동으로 다른 모델·Random으로 대체하지 않고 요청·응답·오류를 보존한 뒤 멈춘다.
LLM의 `boundary_probe` 이름만으로 확정 경계를 만들지 않는다.

### 실행 경로별 프롬프트 계약

`behavior_request.request()`는 공통 연구 원칙에 아래 선택 정책 중 하나만 붙인다.
선택 정책과 context schema가 다르면 API 요청 생성 전에 거부한다. context hash, 엄격한
출력 schema, 증거 ID 검증은 그대로 유지한다. 정책 식별자는 저장되는 `request.json`의
`instructions`에서도 확인할 수 있다.

- P2 `run_afs_benchmark.py`: `campaign-single-endpoint-v1`.
  제안당 최대 한 후보를 선택한다고 명시한다. 경계 중점·독립 탐색·반복은 별도 host slot이며
  LLM 제안 하나에 부가 실행되는 실험이 아니다. LLM의 `boundary_probe`도 이 요청에서는
  low/high 후보를 제공할 뿐, 그 자체로 중점 선택을 지시하지 않는다.
- 단독 `run_behavior_afs.py`: `standalone-suite-v1`.
  기본적으로 양 끝점 장면 파일을 생성한다. 같은 축의 관측 bracket이 있는 `boundary_probe`는
  제안 구간이 아니라 관측 bracket의 중점으로 대체한다. 반복/독립 탐색도 생성하되
  중복/cooldown으로 일부 후보가 제외될 수 있다. **장면 생성이지 로봇 실행 완료가 아니다.**

2026-09-27 수정 전에는 공통 프롬프트가 양 끝점을 실행한다고 설명해 P2 구현과 달랐다.
이번 수정은 그 설명을 경로별 실제 동작에 맞춘 것이며, 후보 선택 알고리즘·로봇 행동·평가 기준은
변경하지 않았다. 프롬프트 명확성과 테스트 원칙은
[OpenAI Prompt engineering 문서](https://developers.openai.com/api/docs/guides/prompt-engineering)를 참고했다.

API는 기존 Responses 호출기를 재사용한다. strict JSON Schema와 context hash 고정,
host 의미 검증을 함께 유지한다. 거절/미완료 응답은 실험 후보가 아니다.
schema의 required/additionalProperties 규칙은 [OpenAI Structured Outputs 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를 확인했다.
모델 이름 변경이나 계정 접근 가능성 검증은 이번 작업에 포함하지 않았다.

## 중단·재개와 수동 확인

SQLite에 외부 호출 **직전 intent**를 먼저 기록한다. source code/의존 패키지 버전/로봇 자원 파일은
init 및 재개·각 실행 전후에 확인한다. 달라졌다면 새 실험 조건이므로 기존 캠페인에 섞지 않는다.
원격 모델 가중치 자체를 동결할 수는 없으며, 기록된 반환 모델/로봇 조건이 바뀌면 비교를 중단한다.

이번 프롬프트 수정도 frozen source hash를 바꾼다. 수정 전 코드로 init한 캠페인은 기존
프로토콜을 수정해 억지로 이어가지 말고, 위 `init` 명령으로 **새 캠페인 폴더**를 만든다.
과거 폴더와 실험 증거는 그대로 보존한다. 아직 rollout이 없는 기존 폴더도 같은 원칙을 따른다.

- robot archive가 완결됐고 child가 종료됐으면 재실행 없이 수집한다.
- API 응답 파일만 저장된 채 중단됐다면 그 응답을 다시 검증하고 후보를 이어서 실행한다.
- 이미 `READY`인 제안도 재개 시 원본 행동 근거와 context를 다시 검증한다.
  응답 대기 중 근거가 달라지면 후보를 실행하지 않으며, 코드/자원도 후보 선택 후 실행 직전에
  다시 확인한다. 실행 후에만 변경을 발견해 다른 조건의 로봇을 한 번 더 실행하는 것을 방지한다.
- episode 수집·observe checkpoint는 한 DB transaction으로 저장해 중복 소비를 막는다.
- 조건/반환 모델 변경에 따른 `INCOMPLETE` 중단 상태도 해당 episode와 같은 transaction에 저장한다.
  저장 직후 crash나 진행 알림 오류가 나도 중단 조건을 잃고 실험을 이어가지 않는다.
- 요청이 실제 발송/완료됐는지 알 수 없으면 다시 보내지 않는다. 자동 재시도 0회다.
- watchdog/Ctrl+C의 외부 중단은 INCONCLUSIVE이며 이번 명령을 멈춘다. 목표 FAIL이 아니다.
- 자식 프로세스 시작 후 PID 기록/대기에 오류가 나면 시작한 프로세스 그룹을 종료·회수한 뒤
  가능한 경우 receipt를 남기고 원래 오류를 전달한다. 신호를 보내는 순간 자식이 먼저 종료된
  경우도 정상적으로 회수한다. 호스트 전체 종료/강제 kill까지 처리한다는 보장은 아니다.
- 필수 결과/manifest 누락은 기존 P0 규칙대로 제외한다. core/media manifest 분리 및 runner 최종화 순서 개선은 아직 후속 작업이다.

`NEEDS_ATTENTION`이면 먼저 `last_error.json`, `proposals/<id>/error.json`, `process.log`,
`status`의 pending ID를 확인한다. 오류 문장·traceback은 기존 redaction 함수를 거쳐 저장한다.
비밀키를 로그나 해소 사유에 넣지 않는다.

외부 프로세스/API 요청이 더 이상 실행 중이지 않음을 **사용자가 확인한 후에만**, 완료 여부를
확인할 수 없는 작업을 버리는 명령이 있다. 아래는 ID를 실제 pending 값으로 바꾸는 예시다.

```bash
uv run --no-sync python tools/run_afs_benchmark.py resolve --campaign CAMPAIGN_DIR --abandon-pending attempt_00000 --note "Verified no child is active; completion unavailable"
```

완료 archive 또는 검증된 proposal이 있으면 버리기를 거부하고 정상 재개를 요구한다.
응답 파일은 저장됐지만 아직 `READY`로 기록되지 않은 경우에도 후보로 사용 가능한 응답이면
버리기를 거부한다. 거절/형식 오류/유효 후보 없음은 명시적으로 해소할 수 있지만 자동 재요청은 하지 않는다.
PID가 살아 있으면 자동 종료하지 않고 거부한다. PID 재사용도 보수적으로 실행 중으로 판단할 수 있다.
버린 시도의 비용/전체 시도 횟수는 사라지지 않으며 goal 실패로 재분류되지 않는다.
다음 `run`은 새 attempt/request를 만든다. 과거 API 과금 취소를 보장하지 않는다.

## 저장 구조와 구현 경계

```text
/workspace/g1_failure/runtime/afs_benchmark/<campaign>/
  protocol.json             # 초기 frozen config/design/environment와 digest
  campaign.sqlite3          # intent/attempt/proposal/observe checkpoint + transition ledger
  proposals/proposal_XXXXX/ # request/response, 오류가 있으면 error.json
  attempts/attempt_XXXXX/
    candidate.json, scene_config.json, command.json
    process.json, process.log, receipt.json
    rollout/                # 기존 goal-agent 원본 기록·MP4
  reports/<timestamp>/      # P0 측정 + 선택 P1 자산, campaign protocol/ledger와 hash
  latest_report.json, last_error.json (생성된 경우)
```

기존 ClientRepository의 transaction, CandidateObservation, P0 importer/계산기와 P1 memory를 재사용한다.
goal-agent 장면 계약과 HTTP operations 계약이 다르므로 **로컬 adapter**이며 일반 HTTP method registry plugin은 아니다.
서버 프로토콜/기술 권한/로봇 프롬프트/goal 평가기는 변경하지 않았다.
로봇 CLI에는 새 폴더만 허용하는 `--run-dir`을 추가해 attempt마다 고정된 수집 위치를 확보했다.

trusted-local ledger는 실제 수집 순서와 비용/예산 추적을 제공하지만 외부 인증 서명은 아니다.
완전히 동일한 core evidence는 복사본으로 보수적으로 제외한다. 독립 실행이라도 원 기록으로
구별하지 못하면 중복 제거가 될 수 있다. 운영 로그와 일부 API 실패의 토큰 비용은 여전히 불완전할 수 있다.
추가된 보고서/메모리를 독립적인 최종 성능평가셋으로 간주하지 않는다.

합성 테스트로 검증한 것은 예산/격리/반복/재개/계약 거부와 파일 근거 연결이다.
실제 30% FDR, Random 대비 20% 향상, 4/6 유형 달성은 아직 검증하지 않았다.
다음은 사용자가 설정을 확인한 소규모 live pilot이며, 그 이후 장면/유형 detector·회귀 실행 범위를 확장한다.
