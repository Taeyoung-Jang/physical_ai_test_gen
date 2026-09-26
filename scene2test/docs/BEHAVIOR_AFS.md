# 행동 근거 기반 AFS — 경계·다른 원인·독립 탐색

2026-09-26 v2: [Goal 달성 기준 설계](GOAL_OUTCOME_AFS_DESIGN.md)와
[구현 범위](GOAL_OUTCOME_AFS_IMPLEMENTATION.md). `goal_outcome_v1` 결과를 입력으로 사용한다.
구버전 기록은 진단 근거로 읽되 새 목표 실패나 성공/실패 경계의 표본으로 재분류하지 않는다.

`tools/run_behavior_afs.py`, `src/llm_afs/behavior.py`.
이번 경로는 **최근 VLM/밀기 로봇**의 결과를 읽는다. 기존 terrain AFS와 별개이며
다른 로봇 결과를 대신 쓰지 않는다. 로봇 전략·제어·성공 기준은 변경하지 않는다.

## 핵심 원칙

실패를 더 심하게 만드는 대신, 다음 실험에서 얻을 정보를 늘린다.
밀기 미달은 무게 때문이라는 증거가 아니다. 제어 시간, 접촉, 정렬, GPT의 목표 선택도
경쟁 설명이다. 자세 기울기는 측정하지만 안정성 여유나 넘어짐 확률로 바꾸지 않는다.

입력은 manifest 해시를 검사한 protocol/result, 실제 scene.xml의 물리 파라미터,
행동 순서, skill 결과(접촉·이동·정렬), 단계별 sampled 몸체 기울기/최저 높이,
SceneGraph, 과거 동일/다른 로봇 조건의 결과다. 기본 버전은 **수치/행동 로그**를
LLM에 보내며 동영상이나 camera PNG를 자동 입력하지 않는다. 영상 분석 VLM은 미구현.
manifest 검사는 trusted-local 무결성 검사이지 악의적인 기록자에 대한 인증이 아니다.

출력은 1–4개의 탐색 공간으로, 각 공간에 mode, axis, low/high, evidence_refs,
hypothesis, alternative, falsification이 있어야 한다. LLM은 로봇 행동을 지시하지 않는다.

| 구분 | 호스트가 생성하는 후보 | 의미 |
|---|---|---|
| 명시적 반복 | 기본 2개; 반대 결과가 있으면 양쪽 조건 반복 | 확률적 재현성 확인 |
| 성공 쪽 탐색 | 한 변수의 범위 양 끝; 현재 값보다 모두 작아도 허용 | 조건을 완화해 성공이 나타나는지 확인 |
| 경계 탐색 | 비교 가능한 PASS/FAIL이 있으면 중간점 | 잠정 전이 구간 탐색 |
| 다른 원인 탐색 | 한 변수의 범위 양 끝 | 경쟁 설명 대조 |
| 독립 탐색 | 전체 허용 범위에서 2개 | 기존 설명 밖의 조건 탐색 |

`success_probe`, `boundary_probe`, `cross_mechanism`을 사용한다. 같은 축을 다른
범위로 시험할 수 있고 현재 값을 양쪽으로 포함할 필요도 없다. 축 끝점에서도 제안 가능하다.
각 비교 후보에서 나머지 변수는 그대로 유지한다. 한 조건에서 통과/실패가 반대이고
로봇·예산·코드 조건이 같으며 오직 한 축만 다르면 두 값의 중간점을 다음 경계 후보로
사용한다. 이는 **잠정 구간**이며 단조성·인과성·확률적 경계 확정이 아니다.
GPT가 다른 전략을 선택할 수 있으므로 whole-task 경계와 고정 push skill 경계를 혼동하지 않는다.

과거 run 및 `--prior-suite`로 전달된 생성 이력과 파라미터가 같으면 중복으로 남기고
재샘플링하지 않는다. 명시적 반복은 예외다. 축 전체 쿨다운은 제거했다.
동일 로봇 조건의 실제 FAIL 3회 이상이 정규화 거리 0.05 이내에서 같은 행동 서명을
보일 때 근처 probe만 `NEIGHBORHOOD_COOLDOWN`으로 기록한다. 비교 가능한 반대 결과가
생기면 경계 검사를 허용한다. 행동 서명은 종료 사유·행동 종류 순서·이벤트 종류·기술
결과의 단순 요약이지 원인 증명이 아니다. 먼 영역·독립 탐색·반복은 유지한다.
`--repeats 1..4`(기본 2), `--exploration 1..8`(기본 2)로 비율을 조절할 수 있다.
기본 두 공간이면 8개 후보 슬롯이다. 중복이면 READY 수는 감소하며 자동 충전하지 않는다.
같은 run을 이력에 여러 번 넣어 반복 횟수를 부풀리는 입력은 거부한다.

## 현재 실행 가능한 환경 축

- box_mass_kg: 0.2–10 kg
- box_friction: 0.05–1.5
- floor_friction: 0.05–1.5

MuJoCo 접촉 마찰 조합 때문에 한 geom의 수치 감소가 접촉의 마찰 감소와 같다고
단정할 수 없다. 바닥 변화는 발 접촉과 상자 접촉 모두에 영향을 줄 수 있다.
suite에 동일 우선순위 geom의 max 결합 규칙에 따른 상자–바닥 명목 마찰과
원본 대비 변경 여부를 기록한다. 실제 접촉의 friction은 robot `contacts.jsonl`에서 확인한다.
변수 간 상호작용은 별도의 factorial 실험이 필요하며 한 변수 검사로 분리되었다고
주장하지 않는다. 회전/장애물 배치/국소 마찰/급한 동작을 유도하는 구조 변경은 이
고정 장면 backend에서 아직 지원하지 않는다. 로봇 속도나 명령을 외부에서 바꾸는
대체 구현을 하지 않았다. 기존 terrain 생성기의 기하 기능과도 자동 연결되지 않는다.

## 사용

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test

# 요청과 검증된 행동 요약만 준비: API/GPU 없음
uv run python tools/run_behavior_afs.py --run /absolute/robot-run

# OFFLINE fixture로 기본 8개 후보 슬롯 생성: LLM 결과/실패 증거 아님
uv run python tools/run_behavior_afs.py --run /absolute/robot-run --offline-demo

# LLM 1회 호출로 탐색 공간 제안, 로봇은 실행하지 않음
uv run python tools/run_behavior_afs.py --run /absolute/robot-run --live --model gpt-6-astra

# suite의 READY config를 선택해 동일 로봇 조건으로 실행
uv run python tools/run_robot_goal_agent.py --live --model gpt-6-astra \
  --max-calls 10 --enable-push --response-timeout 300 \
  --scene-config /absolute/behavior-afs-run/candidate_002.json

# 실행 결과를 다음 제안에 반영; 추가 이력 옵션은 반복 지정 가능
uv run python tools/run_behavior_afs.py --run /absolute/new-robot-run \
  --history-run /absolute/prior-robot-run \
  --prior-suite /absolute/behavior-afs-run/suite.json --live
```

출력 기본 경로: `/workspace/g1_failure/runtime/behavior_afs/<UTC>/`.
context/request/proposal/response(실제 호출 시)/suite/후보 JSON/status 또는 error 보존.
후보 JSON은 `--scene-config`로 실제 robot runner에 연결된다. geometry/task/planner는
고정되며 footprint/clearance를 바꾸는 입력은 거부한다. 후보는 로봇 자체를 바꾸지
않는다. 각 실제 로봇 실행이 기존 report/MP4/GIF/manifest를 별도로 남긴다.
suite의 원본 candidate_000부터 동일한 CLI/코드 조건으로 실행해 비교 기준을 만든다.
CLI의 모델/예산을 바꾸지 말 것: 달라지면 feedback signature가 달라 경계 결합 대상이 아니다.
이번 scene adapter 추가로 runner source hash가 바뀌므로 과거 실험은 가설 근거로만
쓰고, 새 기준선과 소스가 다른 과거 결과로 경계를 만들지 않는다.

## 완료 및 남은 범위

구현: 목표 결과·행동 이벤트·도구 실행 결과 요약, 구조화된 LLM 제안,
한쪽/양쪽 one-axis 후보, 잠정 bracket 중간점, 반복 슬롯과 PASS/FAIL 횟수,
중복/근방 쿨다운, 독립 탐색, 실제 scene config 입력 어댑터.
미완료: 자동 다중 rollout campaign/재개, 공정한 valid-rollout 예산 비교,
영상 입력 분석, 기하 기반 다른 실패 가족, 반복 실행 확률적 경계 추정.
구버전/INCONCLUSIVE/invalid 실행은 anchor로 거부하며 유료 제안 호출 전에 검사한다.
BUDGET_EXHAUSTED는 해당 호출 예산에서의 task noncompletion이며 넘어짐이 아니다.

OpenAI Docs의 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
지침에 따라 기존 Responses JSON schema 경로를 재사용하고, 스키마 통과 이후에도
근거 ID·범위·다양성 조건을 호스트가 검증한다. 오류 시 자동 대체 제안/호출은 없다.
