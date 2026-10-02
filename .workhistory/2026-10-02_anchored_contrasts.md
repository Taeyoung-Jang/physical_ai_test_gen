# 성공 기준을 고정한 AFS 단일 축 대조 구현

2026-10-02 UTC. 사용자는 두 번째 동일 조건 PASS 검토 후 다음 작업 진행을 요청했다.
로봇 기능 개발을 추가하지 않고 성공한 로봇 조건에서 환경만 바꾸는 후속 AFS 흐름을 구현했다.
이번 작업은 코드·테스트·문서와 오프라인 계획 생성이며 **새 로봇 실행 및 유료 API 호출은 0회**다.

## 사용한 근거와 실험 범위

- 기준 원본: `/workspace/g1_failure/runtime/robot_goal_agent/20261002T060144_446312Z`
- 반복 원본: `/workspace/g1_failure/runtime/robot_goal_agent/20261002T080932_214891Z`
- 두 기록은 이전 검토와 새 판독기 검사에서 동일 조건의 VALID/PASS로 확인됐다.
- 출력: `/workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002`
- 새 로봇 조건을 만들지 않는다. Luna·CUDA 제어 코드/자원·원래 목표·10회 호출·무제한 simulation·
  300초 HTTP read·goal_dwell_v1·push 허용을 원본에서 상속한다.

운영자가 정한 첫 대조는 통로 폭 4.0m 기준 재실행, 3.6m, 3.2m다.
최대 3 rollout/로봇 API 30회, 초기 AFS 제안 API 0회다. LLM 선정이라고 표시하지 않았다.
나머지 16개 탐색 축과 비탐색 설정은 그대로이며, 폭에 의존하는 물체의 실제 Y 좌표는 함께 바뀐다.
이는 설정 단일 축 대조이지 절대 좌표를 모두 고정한 순수 벽 간격 인과 실험은 아니다.

외부 성공 기록을 이용하는 개발 탐색이므로 기존 AFS/Random arm·seed 이력 제한을 우회하지 않는다.
기존 캠페인 재개, 옛 FAIL 재분류, 새 PASS를 이전 비교 분모에 추가하는 작업은 하지 않았다.
Random 대조가 없는 이번 흐름에서 FDR Gain/통계적 우위를 주장하지 않는다.

## 구현 내용

`scene2test/src/failure_client/experiments/afs_contrast.py`

- P0 판독기와 P1 메모리로 유효 기록·장면 XML/설정·동일 condition/geometry를 검사한다.
- 같은 성공 장면의 두 독립 기록은 PASS 2/FAIL 0 대조 근거로 보존하며 복사본은 중복 제외한다.
- 한 축 후보를 만드는 순수 plan과 검증, 현재 로봇 코드·자원·runtime의 원본 일치 사전 검사를 추가했다.
- 정적 SceneGraph/PNG 지도와 미리보기를 생성한다. no_path를 이유로 후보를 거르지 않는다.
- 다음 선택은 혼합 반복 우선, 관측 bracket의 미측정 중점, 그 외 기존 hypothesis-v2 LLM endpoint다.
  기준 기록을 조작하거나 로봇 행동을 지정하지 않는다.

`scene2test/src/failure_client/experiments/behavior_regression.py`

- 기존 SQLite intent/checkpoint·subprocess 실행·고정 예산·중단 수집을 재사용한다.
- opt-in `anchored_scene_contrast_v1` plan만 단일 축/조건 보존을 추가 검사한다.
- 로봇 실행 후 전체 condition_id가 원본과 달라지면 INCONCLUSIVE로 제외한다.
- 대조 결과를 OBSERVED_PASS/OBSERVED_FAIL로 표시한다. 환경이 바뀐 실패를 로봇 성능 퇴행이라고
  표시하지 않는다. 대조 후보의 stage는 discovery/boundary, 기준 재실행은 repeat다.
- 새 실행 비용·상속 이력 비용·후속 AFS 선택 비용을 분리한다. 새 보고서에 P1 증거/반복/bracket/
  MP4 링크를 포함한다. 보고서의 재귀 manifest는 하위 증거 bundle도 해시로 기록한다.

`scene2test/tools/run_afs_contrast.py`

- `plan`, `init`, `status`, `report`, `next`는 기본 무료/로봇 미실행이다.
- `run --live`는 기본 한 시도만 수행한다. 전체 계획 완료 후 재호출해도 재실행하지 않는다.
- `next`는 전체 유효 완료 이후에만 가능하다. 혼합 반복이면 최대 1회, 관측 중점/LLM 후보면
  기준 반복 포함 최대 2회의 **새 계획**을 만들고 로봇 실행은 별도 `run --live`에 맡긴다.
- 관측 경계나 혼합 결과가 없으면 기본은 request/context만 기록한다. `next --live`는 필요한
  경우에만 AFS API 1회, 모델 Luna, 기존 medium effort·엄격 schema·무출력토큰상한·무재시도를 유지한다.
- 요청 intent/원문 response/usage/error를 보존하며 호출 후 원본 근거와 동결 환경을 재검사한다.
  `--response`로 저장된 응답을 추가 API 없이 재검증할 수 있다. 재전송을 자동 선택하지 않는다.
- 예산은 라운드별 고정이며 무한 자동 반복이 아니다. 입력 이력 32개 상한을 넘으면 명시적으로 멈춘다.

`scene2test/src/llm_afs/behavior_request.py`

- 새 `anchored-contrast-endpoint-v1` 선택 지침을 추가했다. 기존 benchmark와 standalone 지침은 보존했다.
- 실제 처리인 후보 하나+기준 반복, 외부 이력, 별도 로봇 실행 승인, 혼합/중점 우선순위를 설명한다.
  이 도구에 없는 고정 exploration slot을 있다고 설명하지 않는다.
- OpenAI Docs 스킬로 [공식 프롬프트 지침](https://developers.openai.com/api/docs/guides/prompt-engineering)을
  확인해 역할과 작업 절차를 분리했다. 모델 변경이나 API 제품 동작에 대한 새 가정은 추가하지 않았다.

`scene2test/src/failure_client/archive/regression_cases.py`

- P1 reproduction 정보와 `REPRODUCE.txt`에 navigation_completion을 보존했다.
  새 goal_dwell_v1 증거를 export할 때 원래 completion 옵션을 빠뜨리는 문제를 발견해 수정했다.
  옛 protocol에 옵션이 없으면 기존 profile 판독의 position_only_v1을 사용한다. 원본은 수정하지 않는다.

## 검증 결과

다음 테스트는 합성 archive·mock provider·mock subprocess를 이용하며 실제 G1 성공 증거가 아니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
.venv/bin/python -m pytest tests/client tests/test_behavior_request.py tests/test_behavior_afs.py tests/test_behavior_afs_cli.py -q
```

최종 **358 passed, 114.10초**. 앞선 중간 검사 355 passed 및 개별 34 passed는 이 집합과 중복되므로
별도 합산하지 않는다. 새 대조 테스트는 plan의 오프라인성/단일 축/설정 상속/예산, 잘못된 값,
코드·조건 mismatch, 원본 보존, crash 후 무재전송 수집, 조건 drift 제외, 혼합 반복 우선,
중점 선택, all-FAIL 경계 금지, LLM context 검증, CLI 무료 준비/단일 mock 호출/응답 재사용,
미완료 API 응답의 비용·오류 보존과 미리보기·보고서·completion 재현 명령을 검사했다.

변경한 7개 Python 파일 Ruff check/format check 통과, `git diff --check` 통과.

실제 원본 두 개로 `plan`과 `init`을 수행해 위 runtime 폴더를 생성했다.
원본 로봇 소스/자원/runtime 해시가 현재 환경과 일치해 초기화가 통과했다.
생성 후 status는 READY, pending null, 세 사례 attempted 0이었다. `_fresh()` 읽기 전용
재검사도 `FROZEN_PREFLIGHT=OK`였다. 상속 비용은 입력 257754/출력 3802토큰·로봇 호출 11회로
기록되며 신규 호출은 아니다. 새 실행 비용은 아직 관측 없음으로 유지했다.
정적 3.2m PNG를 직접 확인했다. 벽·상자·정적 블록·시작/목표·참고 선이 표시되고
`INITIAL state - NOT a rollout` 표기가 있다. 실제 보행 영상이나 정책의 정답 경로가 아니다.

## 저장과 다음 실행

- `protocol.json`, `campaign.sqlite3`: 별도 개발 계획과 고정 조건/예산.
- `preview/index.html`, `preview/scene_000..002.png/json`, graph JSON: 실행 전 정적 미리보기.
- 실제 실행 후 `attempts/.../rollout/rollout.mp4`, `reports/.../report.html` 생성 예정.
- 자세한 실행 명령은 `scene2test/docs/AFS_ANCHORED_CONTRASTS.md`와 README에 연결했다.

다음 한 시도 명령은 다음과 같다. 현재 셸에 사용자가 API 키를 설정한 후 실행한다.

```bash
uv run --no-sync python tools/run_afs_contrast.py run --suite /workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002 --live --max-new-attempts 1
```

아직 실제 폭 대조 결과·실패 경계·후속 LLM 가설의 품질은 검증되지 않았다. 복구/밀기/점프 능력 개선을
AFS의 선행 작업으로 추가하지 않는다. GIF·120초 기본 상한·기본 출력 토큰 상한을 복원하지 않았다.
기존 dirty worktree와 실험 자료를 보존했고, 커밋·push는 하지 않았다.

문서화에는 write-page 스킬을 적용해 구현 사실, 초기 운영자 선택, 합성 검증과 실제 실행 미완료를
구분했다. 이력·README·로드맵·AGENTS 메모리를 갱신했다.
