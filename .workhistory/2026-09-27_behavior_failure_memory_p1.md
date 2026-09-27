# P1 행동 시간선·Failure Memory·관측 경계 자산화

2026-09-27 UTC.

## 요청과 확정 범위

사용자의 “이어서 작업 시작” 요청에 따라 P0 다음 단계인 P1의 첫 구현을 진행했다.
기준은 `.blueprint/Failure_Case_Goal.md`, `scene2test/docs/FAILURE_CASE_MEASUREMENT_PLAN.md`,
root `AGENTS.md`다. 작업 시작 시 git working tree는 clean이었다.

목적은 직전 rollout의 행동을 시간별로 확인하고, 성공·실패·혼합 반복과 경계 후보를
AFS 및 향후 회귀 검증에 재사용할 수 있게 보관하는 것이다. 이번 범위는 오프라인 계측과
증거 자산화이며 유료 API/GPU 실행, 로봇 기술 개발, 자동 campaign, 6종 원인 판정은 아니다.

목표-only 철학을 유지한다. 밀기/접촉/낙상 사건으로 goal verdict를 다시 정하지 않는다.
기존 GIF/MP4/로그는 보존하고 GIF 생성·복사는 추가하지 않았다. 기본 120초 제한도 복원하지 않았다.

## 코드 변경

### 1. 시간 구간 기반 행동 계측

추가: `scene2test/src/failure_client/evaluation/behavior_measures.py`.

- strict `BehaviorEvidence`, `BehaviorInterval`, `EvidenceRef` 레코드.
- P0에서 검증한 source manifest를 분석 전에 다시 확인해 그 사이 변경된 증거를 거부.
- 상태 샘플에서 동일 phase 구간, XY 이동거리, 목표 진척, 최대 샘플 간격을 추출.
- contact start/end를 geometry 쌍과 시작 phase로 연결. 최대 normal force/impulse/샘플 지속시간은
  원 기록의 집계값을 사용하고 재합산해 중복 확대하지 않음.
- fall/recovery, skill failure/interruption의 시각·근거 연결.
- 열린 구간, 시작/종료 누락, 강제 종료는 censoring으로 표시. 종료 시각을 임의 생성하지 않음.
- decision→observation version→tool/skill 결과를 연결. 과거 기록에는 정확한 행동 시작 시각이
  없으므로 관측부터 결과까지의 `observation_window`로 명시하고 실행 시작은 null로 보존.
- API wall latency를 simulation 시간에 더하지 않음. 테스트의 가짜 wall latency 999초가
  실제 action window를 바꾸지 않는지 검증.
- `robot_audit.json`의 보존된 robot nq/nv와 appended clear_box freejoint/XML 구조가 확인될 때만
  상자 상태 주소를 해석. 누락/불일치면 물체 변위는 unsupported이며 phase 분석은 유지.
- 계측 오류는 해당 component INVALID/PARTIAL로 분리. 이를 로봇 goal FAIL로 승격하지 않음.

### 2. Failure memory 및 회귀 근거 자산

추가: `scene2test/src/failure_client/archive/regression_cases.py`.

- robot/task/budget condition + 실제 scene identity별 case를 만들고 독립 관측 반복을 연결.
- 원본 복사본은 P0와 같은 중복 판정 함수를 재사용해 제외.
- 성공 대조, 순수 실패 관측, PASS/FAIL 혼합 반복 및 경험적 실패율 보관.
- primary family는 null, causal status는 UNKNOWN. 사건 수로 taxonomy나 원인을 결정하지 않음.
- 현재 지원되는 세 축의 설정/revision/실제 XML을 확인한 뒤, 한 축만 다른 인접 관측이
  반대의 순수 PASS/FAIL일 때만 observed bracket을 생성. 나머지 geometry/물리 XML과 로봇 조건은 동일해야 함.
- 반복 결과가 혼합된 중간 지점을 건너뛰어 경계를 만들지 않음. 양 끝 반복 수·정규화 폭·중점 probe 보관.
- 관측 bracket은 인과관계, 단조성, 최소 perturbation 또는 확정 재현성의 증명이 아님.
- protocol/result/XML/상태/의사결정/사건/관측/도구/카메라 등 allowlist의 파일만 선택 복사.
- API 전송 원문 및 GIF 제외. JSON의 알려진 credential 필드/키 문자열은 내보내기 전 거부.
  자유문·이미지의 완전한 개인정보 감지는 아니므로 외부 공유 전 별도 검토 필요.
- 선택 파일은 복사 전후 해시 검증. 임시 파일로 스트리밍 복사 후 검증된 내용만 목적 파일로 확정.
  실패 시 이번 복사의 임시 파일만 정리하고 원본을 건드리지 않음.
- 지원 장면에는 scene_config.json, 재실행 조건/코드·자원 해시, REPRODUCE.txt 명령 템플릿 제공.
  외부 모델/ONNX/mesh/소스 전체를 동봉하거나 실행 환경을 검증하지 않아 standalone 환경은 아님.

### 3. HTML·MP4 증거 탐색과 CLI 연결

추가: `scene2test/src/failure_client/reporting/behavior_report.py`.
수정: `reporting/discovery_metrics.py`, `reporting/discovery_report.py`, `tools/measure_failure_discovery.py`.

- 중복 판정 함수 이름을 `deduplicate_records`로 공개해 P0/P1 동일 의미 재사용.
- `--with-memory`: 기존 측정 보고서에 case/행동 시간선/근거 파일·행 번호를 추가.
- MP4는 기본 원본 참조. `--bundle-video`를 함께 쓰면 기존 MP4를 스트리밍 복사.
- 영상 구간 링크는 simulation 시각에 프레임 여유를 둔 근사 탐색이며 정확한 물리-영상 동기화로 주장하지 않음.
- HTML은 지지 접촉 제외 최대 200개 구간 표시. 모든 구간은 behavior.json에 보존.
- 외부 script/network 없는 static HTML이며 동적 문자열은 escaping.
- 출력 폴더의 하위 memory manifest까지 최상위 해시에 포함. MP4 해시 계산도 전체 RAM 적재 없이 스트리밍.
- 옵션을 생략하면 P0 기본 출력과 계산 의미는 유지.

## 검증

추가 테스트: `scene2test/tests/client/test_behavior_memory.py` — parameterized case 포함 34개.
CPU/합성 archive fixture이며 저장한 MP4/GIF 테스트 바이트는 실제 시뮬레이션 영상이 아니다.

첫 집중 실행:

```bash
PYTHONPATH=src .venv/bin/pytest tests/client/test_behavior_memory.py tests/client/test_discovery_measures.py -q
```

당시 P1 30개 + P0 49개 = **79 passed in 15.98s**.
이후 상자 상태 길이 불일치의 부분 보존, 이동한 video bundle, truncated contact,
해시 불일치 복사 실패의 정리 검증 4개를 추가했다.

전체 관련 회귀 실행:

```bash
PYTHONPATH=src .venv/bin/pytest tests/client tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py -q
```

**170 passed in 52.65s**. 기존 P0/client/goal-only/behavior-AFS 테스트를 포함한다.
접촉·낙상·밀기 실패가 있어도 원래 goal PASS가 유지되는지, 반복/중복이 올바르게 구분되는지 확인했다.
API 키가 포함된 선택 파일 거부, XSS escaping, 원본 변경 탐지, legacy/불완전 기록 제외,
여러 축·다른 로봇 조건·혼합 반복의 bracket 금지도 검증했다.

Ruff 최초 검사에서 import 정렬/긴 줄을 정리했다. 최종 변경 Python 7개 파일의 `ruff check`와
`ruff format --check` 통과. `git diff --check` 및 문서의 로컬 링크 26개 존재 확인도 통과했다.

## 기존 보관 자료를 이용한 오프라인 smoke

실행 명령 (`scene2test`에서):

```bash
uv run --no-sync python tools/measure_failure_discovery.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T151327_858717Z --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T130019_070486Z --with-memory
```

실제 생성 경로:

`/workspace/g1_failure/runtime/failure_measures/20260927T150236_092882Z/`

- `report.html`: P0 측정 및 memory 링크.
- `memory/index.html`: 사례/경계/제외 근거.
- `valid=0; excluded=2; cases=0; brackets=0`.
- `20260926T151327_858717Z`: INCOMPLETE / missing_manifest.
- `20260926T130019_070486Z`: UNSUPPORTED / legacy_or_unsupported_profile.
- 비교는 missing_comparison_design. coverage와 FDR을 새로 달성했다고 보고하지 않음.
- 상위/하위 manifest의 **9개 checksum entry** 재검증 및 **5개 HTML local link** 존재 확인 통과.

불완전/과거 guard 실행을 목표-only FAIL로 복구하지 않았으며 원본 파일을 수정하지 않았다.
이 smoke의 0 cases는 새 기능의 실패율 0%가 아니라 **입력 두 건에 유효 표본이 없음**을 뜻한다.
실제 완결된 새 v5 goal-outcome 기록을 확보해야 내용이 있는 실제 행동 memory를 만들 수 있다.
이번에는 로봇/GPU/유료 API를 실행하지 않았다.

## 문서와 남은 범위

- 사용법·출력·해석: `scene2test/docs/BEHAVIOR_FAILURE_MEMORY.md` 추가.
- 측정 계획/기존 측정 문서/프로젝트 로드맵/root AGENTS와 작업 이력 목록 갱신.
- 다음 P2: 이 행동 근거와 반복/경계 정보를 LLM observe/propose에 연결하고,
  같은 domain·robot·seed·유효 rollout 예산의 AFS/Random campaign/resume 구현.
- 이번 작업은 자동 proposal 반영, GPU 반복 검증, 확정 원인 detector,
  clearance/goal occupancy/전신 안전 계측, 자동 회귀 실행을 구현한 것이 아님.
- `llm_afs/behavior.py`, 로봇 runner·goal 계약·프롬프트·기술 권한은 변경하지 않았다.
- git commit/push는 수행하지 않았다.
