# 행동 근거를 이용하는 자동 개발 AFS 구현

## 승인된 목표와 이번 작업 범위

사용자가 이전 자동화 계획에 이어 다음 작업을 승인했다. 기존 자동 AFS/Random 파일럿을
다시 만드는 대신, 검토된 동일 조건의 외부 성공·실패로 시작하는 개발용 자동 루프를 구현했다.
한 번 시작하면 승인된 예산까지 환경 선택·실행·판정 수집·메모리 갱신을 진행한다.
사용자에게 매번 수치 변경이나 다음 실행 명령을 요구하지 않는 것이 목적이다.

이번에는 구현과 오프라인 검증만 했다. 유료 AFS 요청, 로봇 API, GPU/물리 rollout,
runtime 아래 새 실험 세션 생성은 하지 않았다. 기존 원본, 동결 suite, goal 판정과
폭 실험 중단은 유지했다. 커밋·push도 하지 않았다.

## 구현과 재사용

- `failure_client/methods/autonomous_feedback.py`: 엄격한 SearchBudget, 축별 소진 및
  직전 축 제외, 반복 한도, 가설/국소 검사 교대, 후보의 실제 단일 축 anchor 검증.
- `failure_client/experiments/afs_autonomous.py`: 새 개발 세션의 조건 고정, 기존 ResearchStore
  SQLite/OS 잠금, API·rollout 실행 전 intent, 원본 hash 검사와 재개, 비용·보고서 연결.
- `llm_afs/behavior_request.py`: 새 개발 선택 정책의 설명과 일시 선택 가능 축 enum만 추가.
  전체 환경 도메인은 그대로 두고 스키마 및 host 양쪽에서 선택 제한을 검증한다.
- `tools/run_afs_autonomous.py`: 무료 plan/init, 한 번에 남은 예산을 실행하는 run,
  동일 session 재개, status/report. 실행 중 단계별 이벤트를 출력한다.
- `config/afs_autonomous_luna.json`: AFS Luna, 새 시도 6회, AFS 요청 6회, 축별 변경 2회,
  혼합 결과 반복 1회, 상세 근거 episode 최대 4개. 입력 로봇은 10회 호출의 Luna로 총 60회 이하.

기존 goal archive reader, P1 memory, 행동 요약·가설 endpoint 순위·유사 실패 cooldown,
관측 bracket 및 repeat 후보, LocalGoalRunner, 조건 fingerprint, operational taxonomy,
search diagnostics와 regression memory export를 재사용했다. 로봇 실행 코드·프롬프트·
계획기·밀기 기술·평가기와 기존 benchmark 검색 정책은 변경하지 않았다.

새 세션은 기존 regression/benchmark DB와 구분되는 protocol을 먼저 확인한다.
이전 suite 경로를 잘못 넘겨도 해당 DB를 열거나 테이블을 만드는 데까지 진행하지 않는다.

## 선택 규칙과 제한

첫 선택은 관측 bracket이 있어도 LLM 가설이다. 이후 한 번의 국소 검사 슬롯에서 혼합
결과 반복 또는 시험하지 않은 bracket 중간값을 고려하되, 그다음에는 가설 슬롯으로 돌아온다.
국소 후보가 없으면 LLM을 요청한다. 축 quota와 직전 변경 축 제외는 국소 검사와 LLM 모두에
적용하고, 이미 소진된 좁은 bracket이 다른 bracket 후보를 가리지 않도록 먼저 필터한다.
같은 장면 반복이 직전 축 제외를 초기화하지 않는다. 기본 반복은 혼합 결과가 있을 때만 한다.

LLM은 최신 anchor에서 한 축만 다른 범위를 제안하며 끝점 하나만 실행한다. 기존 전체 행동
요약, SceneGraph, 로봇 조건, PASS/FAIL, 근거 ID와 반증 조건이 요청에 들어간다. AFS는
로봇의 행동을 지정하지 않는다. 정적 no_path로 scene을 제외하거나 goal FAIL을 부여하지 않는다.
같은 축을 계속 세게 만드는 것을 막는 휴리스틱이지 실패 유형 다양성의 보장이나 원인 규명은 아니다.

총 시도 예산은 VALID 수가 아니라 intent 수다. 제외도 예산을 소비한다. 입력 이력 비용은
별도이고, 입력 robot archive에 없는 과거 AFS 비용과 누락된 사용량은 unknown으로 남긴다.
토큰 수, 달러, 시뮬레이션 시간의 새로운 상한을 추가하지 않았다. 회당 로봇 조건은 그대로다.

## 중단 재개와 보존

요청 전 상태를 먼저 저장한다. 프로세스가 중단되면 저장 응답이나 완료 archive만 수집하며,
불명확한 API·로봇 요청을 다시 보내지 않는다. API 오류·손상 근거·로봇 조건 변화·제외 결과는
NEEDS_ATTENTION으로 중단한다. VALID/FAIL은 정상 탐색 자료이므로 다음 실험으로 이어진다.
명시적인 제외 이후 진행 옵션은 남은 새 시도를 허용할 뿐, 제외를 재시도하거나 예산을 늘리지 않는다.

후보 검증 완료 직후 Ctrl+C처럼 pending이 없고 후보만 저장된 경우도 재검증 후 이어간다.
실행 중인 자식 프로세스가 있으면 수집·재실행하지 않는다. 예외는 비밀정보 제거 후 종류,
메시지, 호출 위치를 `errors/`와 전이 기록에 보존한다. 재개 시 소스/자산/환경이 바뀌면 거부한다.
후보·응답 원본 수정이나 old campaign 검사를 우회하는 복구는 제공하지 않는다.

## 산출물과 회귀 자산

새 live 세션의 기본 저장 위치는 `/workspace/g1_failure/runtime/afs_autonomous/<시각>/`이다.
가설·축 선택 이유·실제 장면·goal 결과·행동 수치·로봇 HTML/MP4 링크를 새 보고서에서 연결한다.
GIF는 생성하지 않는다. `search_diagnostics.json`은 새 실행만의 패턴 반복·관측 bracket과
외부 이력을 포함한 진단을 분리한다. `hypothesis_reviews.json`은 가설과 실제 결과를 연결하되
원인을 자동 확정하지 않는다. `behavior/memory.json`은 기존 회귀 도구에서 다시 사용할 수 있다.
회귀 suite나 추가 유료 실행을 자동 생성하지 않는다.

## 실제 기록을 이용한 무료 검증

다음 두 archive를 원본 읽기만으로 검증했다.

- `/workspace/g1_failure/runtime/robot_goal_agent/20261003T150653_133405Z`
- `/workspace/g1_failure/runtime/robot_goal_agent/20261003T154614_537450Z`

동일 condition은 `eb42efe331685d6e51813b38195d27a88f50b1da77b25bd15cd9c296b42b95aa`였다.
현재 소스·외부 로봇 자산·기록된 runtime과 비교한 실제 CLI plan이 통과했다. 출력 조건은
v4, Luna, 밀기 활성, goal_dwell_v1, 회당 10회, HTTP 300초, sim cap 없음이었다.

메모리상의 첫 LLM 요청도 구성했다. 검증 episode 2개와 관측 bracket 1개가 있으나 첫 선택은
중간값이 아닌 LLM hypothesis였다. 선택 가능한 축은 18개, 요청 JSON은 UTF-8 81,474바이트,
`max_output_tokens`는 없었다. 두 실제 evidence ID, case_memory, observed_brackets가 포함됐다.
이 검사는 요청 생성/근거 연결을 확인한 것이며, 실제 LLM 응답이나 로봇 성능 검증이 아니다.

## 테스트 경과와 문서화

첫 전용 합성 검사에서 13개가 통과하고 테스트 도우미의 부모 폴더 생성 누락 1개가 실패했다.
테스트 도우미를 수정했다. 이후 관련 회귀 135개, 공유 LLM 요청 검사까지 확대해 174개가
통과했다. 마지막으로 Ctrl+C 선택 직후 재개와 old suite 사전 거부를 보강한 최종 관련
회귀 검사는 **176 passed, 95.10초**였다. 그중 새 자동 탐색 전용 검사는 19개다.
Ruff check와 format check, `git diff --check`도 통과했다.

최종 테스트 명령은 `scene2test` 디렉터리에서 다음과 같다.

```bash
.venv/bin/python -m pytest -q tests/client/test_afs_autonomous.py tests/client/test_afs_contrast.py tests/client/test_behavior_regression.py tests/client/test_afs_paired_contrast.py tests/client/test_afs_search_improvements.py tests/client/test_goal_region_campaign.py tests/client/test_research_campaign.py tests/test_behavior_request.py tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_expanded_afs_feedback.py
```

테스트 범위는 고정 총예산, 여러 축 선택, 한도와 cooldown, 반복 제한, 실제 근거의 다음 요청
반영, 저장 응답 복구, archive 완료 후 중단 복구, 불명확한 요청 재전송 금지, usage unknown,
조건 변화 제외, 원본·응답·protocol tamper, 잠금, 비밀정보 제거, 보고서와 memory다.
합성 테스트의 PASS/FAIL은 G1 물리 성능이나 새 실패 발견을 의미하지 않는다.

write-page 지침에 따라 README와 별도 실행 가이드에서 현재 구현, 예산, 유료 실행과 무료
검사, 검증되지 않은 live 성과를 구분했다. 문서 경로는
`scene2test/docs/AFS_AUTONOMOUS_DEVELOPMENT.md`다.

## 남은 검증과 다음 단계

이 새 루프의 live 응답 준수와 실제 장면 탐색 성과는 아직 검증하지 않았다. 사용자가 키를
설정한 한 프로세스에서 명령을 한 번 시작하면 승인된 전체 예산을 진행한다. 실제 오류에서는
추가 비용을 숨겨가며 재시도하지 않고 근거를 확인한다. 다음 연구 단계는 자동 개발 탐색의
관측을 검토한 뒤, 네 번째 실패 유형의 실제 scene/trace/rule 지원과 독립된 다중 seed
AFS/Random 평가다. 개발 이력을 정식 평가 arm의 무료 초기 자료로 섞지 않는다.
