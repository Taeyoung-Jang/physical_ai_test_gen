# AFS/Random 전체 파일럿 일괄 실행 스크립트

날짜: 2026-09-28 UTC.

## 요청·시작 상태

사용자는 새 캠페인 초기화 → 2회 점검 → AFS/Random 각 8회 → 결과 분석/보고를
전부 수행할 수 있는 스크립트 하나를 요청했다. 실제 유료 실험 시작이 아니라 실행 도구 작성 요청이다.
작업 시작 시 worktree는 clean이었다. 기존 self-audit 수정은 이미 저장소에 반영되어 있었다.

## 구현

- `scene2test/tools/run_afs_pilot.py` 추가. 기존 ResearchCampaign과 보고서를 그대로 재사용한다.
- `--live` 없는 기본 실행은 계획/상한만 출력한다. 키 유무와 관계없이 파일 생성, 캠페인 초기화,
  실제/모의 로봇, API 호출을 하지 않는다.
- `--live`는 로컬 OPENAI_API_KEY가 있어야 한다. 키를 인자/파일에 기록하지 않는다.
- 새 실행은 기본 프로젝트 설정으로 runtime/afs_benchmark에 새 폴더를 만든다.
  설정 파일 경로는 cwd에 의존하지 않는다. `--config`, 새 `--output-dir`만 선택적으로 지정한다.
- 재개는 `--campaign`으로 지정하고 기존 고정 설정을 사용한다. --config와 동시에 지정할 수 없다.
- 먼저 `run(max_new_attempts=0)`으로 저장된 pending 결과를 수집/검증한다. 완료 불명 호출은
  기존 캠페인의 보수적 복구 규칙에 따라 멈추며 재호출/수동 해소를 자동 수행하지 않는다.
- 최대 2회 신규 rollout 후 메모리 포함 중간 보고서를 만들고, 이후 예산 완료까지 자동 진행한다.
  내부적으로 한 번씩 실행·검사해 첫 실행 오류 뒤에도 다음 로봇을 계속 호출하지 않는다.
- 유효 목표 FAIL은 검색 데이터이므로 계속한다. 제외/미완료 기록·운영 중단·API/무결성 오류는
  즉시 중단한다. 이는 일괄 실행 wrapper의 보수적 정책이며 기존 수동 run의 시도/예산 정책을 바꾸지 않는다.
- 정상 완료와 오류 모두 마지막 보고서를 시도한다. 부분 보고서 성공이 앞선 실행 오류의 종료 코드를
  0으로 덮지 않게 했다. 보고서 자체 오류도 따로 기록한다.
- `pilot_runs/<timestamp>`에 events.jsonl, initial_check.json, summary.json과 필요한 오류 정보를
  저장한다. 오류/stack은 기존 redaction 함수를 사용하며 원본 rollout은 수정하지 않는다.
- 완료 캠페인 재개는 보고서만 생성하며 새 로봇/모델 호출이 없다. 기존 폴더로 새 init은 거부한다.
- research_protocol의 source hash 대상에 새 스크립트를 추가했다. 이전 코드로 init한 캠페인은
  새 코드와 섞지 않으며 새 캠페인을 사용해야 한다.

자동 2회 점검은 archive/계약 검사이지 MP4의 시각 평가나 로봇 능력 승인 절차가 아니다.
AFS 연구 성능, 실패 유형 자동 판정, 자유 형식 영상 분석을 새로 구현했다고 주장하지 않는다.
기존 모델, goal-only 판정, 3축 domain, 로봇 행동, GIF 비활성화, 무제한 simulation 기본값을 유지했다.

## 사용법

`scene2test`에서 계획 확인:

```bash
uv run --no-sync python tools/run_afs_pilot.py
```

키가 로컬 환경 변수로 설정된 상태에서 전체 유료/GPU 실행:

```bash
uv run --no-sync python tools/run_afs_pilot.py --live
```

원인 확인 후 같은 캠페인 재개:

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --campaign CAMPAIGN_DIR
```

기본 목표: AFS 8 + Random 8 유효 실행. 전체 시도 상한 24, 로봇 호출 상한 240 + AFS 요청 상한 8.
상한은 실제 호출 수/비용이 아니다. 상세 명령·종료 코드·산출물은 `BEHAVIOR_AFS_CAMPAIGN.md`에 기록했다.

## 검증

`tests/client/test_afs_pilot.py`는 합성 archive/FakeRobot/FakeProposer만 사용한다.
초기 **14 passed, 28.59s**. 전체 기본 16회 완료, 중간/최종 보고서, 완료 후 재실행 없음,
직접 campaign 실행과 같은 후보 순서, 잘못된 기록/중단/보고서 오류 시 추가 실행 중단,
불명 API 재호출 차단, 비밀값 제거, plan-only 무부작용, 키 없는 live 거부를 확인했다.
이후 완료 불가 캠페인의 재실행 방지와 pending 완결 archive의 중복 실행 방지 검사를 추가했다.
최종 회귀 검사는 신규 스크립트 테스트 16개를 포함해 **298 passed, 1 skipped, 98.96s**였다.
다음 범위를 CPU/합성 증거로 점검했다. GPU timeout 검사는 명시적으로 비활성화해 제외했다.

```bash
PYTHONPATH=src PYBULLET_MODE=DIRECT RUN_ROBOT_TIMEOUT_GPU=0 .venv/bin/pytest tests/client tests/server tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot_goal_agent.py tests/test_robot_request_timing.py -q
```

실제 CLI의 plan-only와 `--help`도 정상 종료했다. 기본 16 유효 rollout/24 시도/240 로봇 호출/
8 AFS 요청 상한, 무제한 simulation을 출력하며 plan-only에서는 캠페인 파일이 생성되지 않았다.
수정한 Python 파일 3개의 Ruff check/format check와 `git diff --check`를 통과했다.
Starlette/httpx의 기존 deprecation warning 1건은 있었으며 이 작업에서 라이브러리를 변경하지 않았다.

최초 Ruff 검사에서 긴 줄 두 군데를 발견해 줄 배치를 정리했다. 기능 테스트 실패는 없었다.
유료 API/GPU 파일럿은 이 작업에서 실행하지 않았고 원본 runtime 자료도 변경하지 않았다.
