# AFS 프롬프트와 실제 후보 선택 방식 정합성 수정

날짜: 2026-09-27 UTC.

## 요청과 발견한 원인

행동 근거·성공/실패 반복을 다음 LLM 장면 제안에 연결하는 P2 설명 과정에서,
공통 프롬프트의 `Host runs each endpoint` 문장이 실제 P2 선택기와 다름을 확인했다.
사용자가 수정을 요청했다. 작업 시작 시 git worktree는 깨끗했다.

- 단독 `run_behavior_afs.py`의 `compile_suite()`는 기본 low/high 장면을 모두 생성한다.
  관측 bracket이 있는 boundary_probe는 해당 bracket 중점으로 대체하며,
  반복·독립 탐색 및 중복/cooldown 필터가 별도로 존재한다. 로봇 실행 도구는 아니다.
- P2 `choose_probe()`는 1–4개 공간의 모든 low/high 후보 중 중복/cooldown을 제외하고,
  기존 관측까지의 최소 정규화 거리가 가장 큰 후보 하나를 반환한다.
  공통 프롬프트를 단순히 “하나 선택”으로 바꾸면 단독 도구 설명이 틀리게 된다.

## 변경 내용

1. `scene2test/src/llm_afs/behavior.py`에서 경로별로 다른 실행 약속 문장을 제거했다.
   성공 측 탐색·대안 가설·반증 측정·목표-only 판정 등 공통 연구 원칙은 유지했다.
2. `behavior_request.py`에 명시적 선택 정책을 추가했다.
   - `standalone_suite` / `standalone-suite-v1`: 후보 파일 생성, 양 끝점 및 관측 중점 예외,
     반복/독립 탐색, 제외 가능성, 생성과 실제 실행의 차이를 설명한다.
   - `campaign_single_endpoint` / `campaign-single-endpoint-v1`: 제안당 최대 한 endpoint,
     max-min 정규화 거리·동점 순서, 별도 host slot과 LLM boundary_probe의 차이를 설명한다.
   - 알려지지 않은 정책, 정책/context schema 불일치는 요청 생성 전에 ValueError로 거부한다.
3. P2 `proposal_request()`가 campaign 정책을 명시적으로 선택하게 연결했다.
4. 단독/캠페인 프롬프트 분리, 실제 후보 생성/선택, 잘못된 연결 거부를 회귀 테스트로 추가했다.
   합성 캠페인이 저장한 실제 요청에도 P2 정책만 들어가는지 검사한다.
5. `BEHAVIOR_AFS_CAMPAIGN.md`에 두 경로 차이·거리 기준·프로토콜 재초기화 원칙을 기록했다.

정책 식별자는 API의 표준 `instructions` 문자열에 기록되며 비표준 API 필드를 추가하지 않았다.
기존 context hash와 Proposal JSON Schema, 모델 이름, API 설정, 레거시 context 복구는 유지했다.
후보 선택 알고리즘, 예산·Random 비교 방식, 로봇 프롬프트/기술, 목표 평가기는 변경하지 않았다.

OpenAI Docs 스킬을 사용해
[공식 Prompt engineering 문서](https://developers.openai.com/api/docs/guides/prompt-engineering)의
명확한 지침·테스트 원칙을 확인했고, 이를 실제 host 선택 계약의 명시와 오프라인 회귀 검사에 적용했다.
모델 교체나 SDK/인증 변경은 하지 않았다.

## 검증

실행 위치: `scene2test`. 유료 API 호출이나 GPU 로봇 rollout은 실행하지 않았다.
AFS/캠페인 검사는 합성 archive/고정 응답을, 목표 평가 관련 검사는 기존 CPU 테스트를 사용한다.

관련 검사:

```bash
PYTHONPATH=src .venv/bin/pytest tests/test_behavior_request.py tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/client/test_research_campaign.py -q
```

결과: **70 passed, 46.84s**.

확대 회귀 검사:

```bash
PYTHONPATH=src .venv/bin/pytest tests/client tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot_goal_agent.py tests/test_robot_request_timing.py -q
```

결과: **238 passed, 1 skipped, 85.52s**. 제외 1개는 `RUN_ROBOT_TIMEOUT_GPU=1`을
명시해야 실행하는 32초 GPU 지연 검사다. 전체 저장소 테스트나 실제 LLM 응답 품질 검증은 아니다.
새 테스트 7개와 기존 합성 캠페인 요청 검사를 통해 정책별 설명·구현 일치를 확인했다.

변경 Python 5개 파일의 Ruff check 및 format check와 `git diff --check`가 통과했다.
최초 정적 검사에서 import 구역 정렬, 이후 format 검사에서 테스트 한 구문의 줄 배치가
검출되어 Ruff의 해당 파일 정리 후 재검사했다. 기능 테스트 실패는 없었다.

## 실험 이력과 재실행 주의

이번 수정은 캠페인이 고정한 source hash를 변경한다. 이전 코드로 초기화한 캠페인을
새 프롬프트와 섞어 재개하지 않는다. 아래 명령으로 새 폴더를 초기화한 뒤 그 경로를 사용해야 한다.

```bash
uv run --no-sync python tools/run_afs_benchmark.py init --config config/behavior_afs_benchmark.json
```

명령은 `scene2test`에서 실행한다. 이번 수정 작업에서는 새 캠페인 초기화나 live 실행을 하지 않았다.
기존 runtime 산출물·프로토콜·과거 응답은 변경하거나 삭제하지 않는다.
프롬프트와 선택 구현의 정합성 수정이지 AFS 성능 향상이나 목표 FDR/Gain 달성의 증거는 아니다.
