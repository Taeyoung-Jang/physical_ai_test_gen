# AFS 전체 연결 자가 점검과 예외 경로 수정

날짜: 2026-09-27 UTC.

## 요청·범위

사용자 요청: “전체적인 동작에 문제는 없는지 스스로 점검해 보시고, 문제가 있다면, 수정하세요.”
시작 시 git worktree는 clean이었다. 직전 프롬프트 정합성 수정은 이미 저장소에 반영되어 있었다.

현재 우선순위인 장면 생성 → AFS 후보 제안 → 로봇 subprocess 연결 → goal-only 판정/측정
→ 행동 메모리 → 다음 제안 → 예산·중단 복구·보고 흐름을 점검했다.
Client/Server 계약, 기존 로봇 도구/장면 생성의 관련 오프라인 테스트도 검증 대상으로 삼았다.
`g1-local-nav`, 기존 Panda 실행 경로, 모델 자체의 물리 능력을 통합/변경하는 작업은 아니다.
유료 API·새 GPU rollout·원본 runtime 결과 변경은 하지 않았다.

## 수정 전에 재현한 결함

기존 기준 검사는 **263 passed, 1 skipped, 1 warning, 101.86s**였다.
그러나 추가한 crash/변경/예산 예외 테스트는 수정 전 **9 failed, 21.83s**로 아래 빈틈을 재현했다.
새 테스트의 실패는 실제 저장소 결함을 검증한 결과이며 실제 로봇 실험의 실패 횟수가 아니다.

1. **READY 제안 재개 시 근거 변경 누락.** 검증 완료 후 실행 전에 중단되면 저장 후보를
   바로 재사용했다. 원본 scene.xml을 변경해도 다음 로봇 호출이 실행됐다.
2. **모델 응답 대기 중 변경의 뒤늦은 발견.** 제안 호출 전에는 code/resource를 확인했지만
   응답 후 다음 robot launch 전에 확인하지 않았다. 코드가 바뀌어도 로봇이 한 번 더 실행된 뒤
   발견했고, 과거 행동 근거가 바뀌면 기존 메모리로 그대로 후보를 선택할 수 있었다.
3. **조건 변경 중단 상태의 별도 저장.** 다른 robot condition 결과를 OBSERVED로 저장한 후
   별도 transaction에서 INCOMPLETE를 기록했다. 그 사이 crash 시 RUNNING 상태가 남았다.
4. **완료된 유효 제안의 임의 폐기 가능성.** response.json은 저장됐지만 READY 저장 전인
   응답을 `resolve --abandon-pending`으로 버릴 수 있었다. 이미 지불한 유효 제안을 재개한다는
   문서/운영 계약과 달랐고, 선택적 폐기/불필요한 새 호출을 허용했다.
5. **자식 프로세스 정리 누락과 종료 경쟁.** Popen 후 process.json 기록 실패는 종료 정리
   범위 밖이라 자식이 계속 남을 수 있었다. timeout 이후 killpg와 자식 종료가 겹치면
   ProcessLookupError가 원래 종료 처리를 방해하고 receipt가 누락됐다.
6. **선언 예산을 넘은 archive도 유효로 수용.** max_calls=10인데 기록된 호출 수가 11이어도
   결과 플래그/해시가 일치하면 VALID로 집계했다. 고정 예산 비교 계약에 어긋난다.

## 코드 수정

### `failure_client/experiments/research_campaign.py`

- `_proposal_memory()`로 AFS 자신의 seed에 속한 원본을 재검증하고 최신 feedback context를
  재구성해 저장 context와 hash를 비교한다. 응답 처리 및 READY 재개 경로에서 모두 사용한다.
- 후보 선택 후 robot launch 직전에 `_fresh()`를 다시 호출한다. 변경이 있으면 대기 중인
  제안·응답·사용량은 보존하고 NEEDS_ATTENTION으로 중단한다. 재요청/Random 대체는 없다.
- condition mismatch의 INCOMPLETE 상태를 observation/checkpoint와 같은 transaction으로
  저장한다. 진행 알림 등의 예외가 나도 이미 확정된 중단 상태를 NEEDS_ATTENTION으로 덮지 않는다.
- resolve에서도 프로토콜 무결성을 확인한다. 유효 saved response는 재개를 요구하고,
  거절/스키마 오류/후보 없음만 명시적 해소를 허용한다. 완료된 유효 실험을 선택적으로 삭제하지 않는다.

### `failure_client/experiments/local_goal_adapter.py`

- PID 기록까지 cleanup 범위에 포함한다. BaseException을 잡는 목적은 시작한 자식의 회수뿐이며,
  예상하지 못한 오류는 receipt 기록 후 다시 전달한다.
- `_stop_child()`는 해당 subprocess session에 SIGTERM, 필요 시 SIGKILL을 보내고 wait한다.
  신호 전송 순간의 ProcessLookupError는 이미 종료된 경우로 처리해 회수를 계속한다.
- receipt는 종료가 확인된 뒤 기록한다. 프로세스 회수 자체가 실패하면 완료된 것처럼 기록하지 않는다.
- watchdog과 Ctrl+C는 운영 중단이며 goal FAIL로 바꾸지 않는다. 기본 시간 상한은 변경하지 않았다.

### `failure_client/evaluation/goal_run_reader.py`

- 기록된 API/전체 정책 호출 수가 protocol.max_calls를 초과하면 INVALID로 제외한다.
- API 호출 수가 전체 정책 호출 수보다 큰 모순도 제외한다.
- 전체 정책 호출 수가 없는 기록에는 새 숫자를 추정하지 않는다. 기존 원본과 과거 결과는
  덮어쓰지 않으며 새 측정에서 확인되는 예산 위반만 제외한다. 확인 가능한 비용은 보존한다.

로봇 goal evaluator, 정책 프롬프트, push/보행 기술, 후보 선택 전략, 모델/API 설정은 변경하지 않았다.
GIF 생성과 기본 120초 제한도 복구하지 않았다.

## 회귀 검증

`tests/client/test_campaign_integrity.py`에 예외 재현 및 정상 복구 검사를 추가했다.
초기 9개 결함 재현에 이어 RuntimeError 후 terminal 상태 보존, 잘못된 응답의 수동 해소,
SIGKILL 종료 경쟁, PASS/FAIL 모두의 초과 예산 제외, 정확한 예산 허용을 검증한다.

첫 수정 후 관련 검사:

```bash
PYTHONPATH=src .venv/bin/pytest tests/client/test_campaign_integrity.py tests/client/test_research_campaign.py tests/client/test_discovery_measures.py -q
```

**99 passed, 44.56s**. 이후 보완 테스트를 추가해 확대 검사를 진행했다.

확대 오프라인 검사:

```bash
PYTHONPATH=src PYBULLET_MODE=DIRECT RUN_ROBOT_TIMEOUT_GPU=0 RUN_ROBOT_ERROR_GPU=0 RUN_ROBOT_PUSH_GPU=0 .venv/bin/pytest tests/client tests/server tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot*.py tests/test_llm_afs*.py tests/test_expanded_afs*.py tests/test_clear_path*.py tests/test_procedural_world.py tests/test_terrain*.py tests/test_scene_search*.py -q
```

결과: **513 passed, 5 skipped, 1 warning, 162.53s**.
장면/지형 생성·SceneGraph/map/XML, AFS 형식/후보/피드백, Client/Server 계약,
로봇 tool dispatch/조작 경계, goal-only 판정, 측정·메모리·캠페인 복구를 포함한다.
실제 GPU 선택 검사 5개는 명시적으로 비활성화했다. 경고 1개는 기존 Starlette TestClient의
httpx 사용 deprecation이며, 이번 결함과 무관한 의존성 교체는 하지 않았다.
전체 저장소의 모든 역사적 Panda 단계 스크립트까지 실행했다는 의미는 아니다.

추가로 실제 OS 프로세스 회수 검사를 위해 로봇 CLI를 **sleep만 하는 Python 자식**으로 대체한
2개 테스트를 추가했다. metadata 기록 실패 및 0.1초 watchdog에서 해당 자식의 종료/wait/receipt를
확인한다. 테스트가 실패하더라도 자기 자식만 kill/wait하는 정리 블록으로 누수를 방지한다.
이 2개는 위 513개 확대 검사 이후 추가한 검사이며, 최종 예외 테스트 파일은 19개다.

```bash
PYTHONPATH=src .venv/bin/pytest tests/client/test_campaign_integrity.py -q
```

최종 결과: **19 passed, 12.82s**. 위 확대 검사의 17개와 중복되므로 513+19를
전체 고유 테스트 수로 합산하지 않는다. 변경 Python 파일 4개의 Ruff check/format check와
최종 `git diff --check`도 통과했다. 형식 검사에서 reader의 긴 한 줄을 정리한 것 외에
추가 정적 검사 오류는 없었다.

## 실제 자원 기반 오프라인 CLI smoke

`mktemp -d /tmp/afs-selfcheck.XXXXXX`로 별도 임시 진단 디렉터리를 만들고 아래를 실행했다.
실제 실험 결과의 기본 경로 `/workspace/g1_failure/runtime`는 변경하지 않았다.

```bash
uv run --no-sync python tools/run_afs_benchmark.py init --config config/behavior_afs_benchmark.json --output-dir /tmp/afs-selfcheck.4B1jfe/campaign
uv run --no-sync python tools/run_afs_benchmark.py status --campaign /tmp/afs-selfcheck.4B1jfe/campaign
uv run --no-sync python tools/run_afs_benchmark.py report --campaign /tmp/afs-selfcheck.4B1jfe/campaign --with-memory
```

세 명령 모두 정상 종료했다. 상태 READY, 양쪽 attempt/valid=0, AFS 요청 0건이다.
source 124개·로봇 자원 52개를 실제로 읽고 해시를 고정했으며 `_fresh()` 재검증도 통과했다.
GPU에 모델을 올리거나 실제 모델/계정 연결을 확인한 것은 아니다.

임시 HTML 보고서:

`/tmp/afs-selfcheck.4B1jfe/campaign/reports/20260927T162608_505243Z/report.html`

상하위 보고서의 manifest 항목 11개 해시를 재검증했다. 비교는 not_comparable, FDR은 null이며
실험 0건을 실패율 0%로 표시하지 않음을 확인했다. 이 /tmp 출력은 영구 실험 데이터가 아닌
단기 진단 산출물이며, 본 작업 이력에 결과를 남긴다.

## 운영·연구 해석

코드/source hash가 변경되므로 다음 실제 실험은 새 campaign init으로 시작해야 한다.
기존 캠페인의 protocol hash를 새 코드에 맞춰 덮어쓰지 않는다. 기존 runtime 결과는 모두 보존한다.
자동 재호출·예산 확대·로봇 행동 제한/능력 변경 없이 예외 경로를 보강한 작업이다.

오프라인 검증은 실제 계정 모델 접근, GPU 보행, 카메라 렌더링, 장시간 네트워크 안정성이나
AFS의 FDR/Gain 우월성을 입증하지 않는다. 6종 detector/실제 coverage, 이미지 기반 AFS,
core/media manifest 분리 및 자동 regression 실행은 기존 미구현 범위로 남는다.
임의 시점의 호스트 강제 종료·파일 동시 변경을 완전히 막는 외부 트랜잭션/분산 잠금은 제공하지 않는다.
