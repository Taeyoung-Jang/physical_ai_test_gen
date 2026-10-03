# AFS 첫 기하 확장: 통로 폭·상자 배치, 지도 정합성, 경계 메모리

날짜: 2026-09-28 UTC.

## 요청과 실행 범위

사용자가 개선 방향으로 다음 구현을 진행하도록 요청했다. 상자 질량/마찰만 바꾸던
실험에 성공 대조·우회·좁은 통로 조건을 넣을 수 있도록 장면 기하 확장을 우선했다.
처음부터 전체 미로/지형/점프를 합치는 대신 통로 폭·상자 좌우 배치 두 축을 추가한다고
사용자에게 알렸다. 점프/새 보행 정책 개발, 비용 집계/로봇 history 요약은 이번 범위가 아니다.

작업 시작 시 worktree는 clean이었다. 기존 결과를 수정하지 않았고 commit/push하지 않았다.
일반 sandbox shell은 bwrap namespace 권한 오류로 실패했다. 승인된 실행 경로로
파일을 조회/검증했고 파일 편집은 apply_patch로 수행했다. 호스트 보안 설정은 바꾸지 않았다.

## 설계와 변경

### 새 versioned scene contract

`CorridorFixture` / `clear-path-corridor-v2`는 기존 v1과 별도다.
길이8m 직선 통로에 동적 상자 하나를 둔다. v1의 side bay와 상자 목적지 표식은 없다.

- 통로 폭: 1.6–4.0m.
- 상자 배치 비율: −1..1.
- 기존 질량0.2–10kg, 상자/바닥 마찰0.05–1.5는 유지한다.
- 상자 크기0.8×1.1×0.7m, X=4m, 로봇 시작 `[1,0]`, 목표 `[7,0]`는 고정한다.
- `box_y = fraction * (width/2 - 0.55 - 0.05)`로 벽과 최소5cm 초기 간격을 둔다.
  fraction은 미터가 아니며, fraction이 0이 아니면 width 변경도 box Y에 영향을 준다.
  단일 파라미터 bracket을 다른 물리 성분까지 고정된 인과 증명으로 부르지 않는다.
- planner 반경/여유, task/goal, robot command를 장면 파일로 바꿀 수 없도록 기존 검증을 유지한다.

`clear_path/scene_space.py`가 3축/5축 bounds와 정확한 candidate 키 집합을 관리한다.
`fixture.py`의 동일 config에서 벽·상자 초기 좌표, SceneGraph, 정적 지도, MuJoCo XML을 만든다.
새 SceneGraph에 `mujoco_geom_name` 대응과 diagnostic-only 접촉 주석을 기록한다.
지도/그래프에 같은 scene revision을 보존한다. v1 기본값과 기하/identity 의미는 유지한다.

### 실제 실행기와 AFS 연결

- `robot_vlm/scene_config.py`: 명시적 v2 schema를 파싱한다. schema 없는 새 축 입력은 거부한다.
- `goal_runner.py`: 해당 장면의 벽 목록을 사용해 관측/접촉을 수집한다.
  초기 SceneGraph/지도도 결과와 manifest에 저장하되 정답 경로로 정책에 전달하지 않는다.
- `research_protocol.py`: `scene_schema`로 domain을 동결한다. 기본은 v1.
- `local_goal_adapter.py`, `research_campaign.py`: schema별 config 작성, scene revision 검사,
  full-domain Random/paired cold/exploration/반복에 같은 domain을 적용한다.
- `behavior_feedback.py`: 5축 거리/novelty/cooldown/관측 bracket을 지원하며 다른 schema의
  사례를 동일 feedback에 섞지 않는다. 로봇 행동 선택은 그대로 정책의 몫이다.
- `behavior.py`, `behavior_request.py`: AFS 제안의 허용 axis enum을 domain별로 제한한다.
  범위/근거 ID/context hash는 로컬에서 다시 검사한다. 임의 XML/로봇 행동 출력은 허용하지 않는다.
  기존 standalone suite 도구는 v1 전용이며 v2는 campaign을 사용한다.
- `regression_cases.py`: config/XML의 일치를 먼저 확인한 후 장면 소유 노드만
  정규화해 비교용 geometry hash를 만든다. 로봇·물리 옵션·예상 외 XML 변경은 hash에 남는다.
  v2 캠페인의 XML/config 불일치는 유효 goal FAIL로 세지 않고 INVALID로 중단한다.

OpenAI Docs 스킬과 model-migration 참고 문서를 읽었다. 로컬 전달 경로를 확인하고
https://developers.openai.com/api/docs/guides/structured-outputs 를 검색/열어
엄격한 schema 및 enum 제약을 확인했다. API endpoint/추론 수준/로봇 프롬프트는
바꾸지 않고 AFS의 환경 축 설명과 출력 enum을 확장했다. 키 제공 전용 도구는 없었다.
이번 작업에서 API 키 조회/전송이나 유료 API 요청은 하지 않았다.

### 개발용 장면·미리보기·Luna 캠페인

`config/scenes/`에 wide(폭4, 중앙), narrow(폭1.6, 중앙), offset(폭2.4, 비율1)을 추가했다.
정적 지도상 경로는 각각 있음/없음/있음이다. 모두 아직 실제 목표 outcome은 NOT_EXECUTED다.

`tools/preview_corridor_scenes.py`는 API/로봇 실행 없이 PNG/HTML/config/graph/map/XML/manifest를
생성한다. `--audit-robot`은 실제 G1 자산을 CPU MuJoCo로 합성·검사한다.
GIF/MP4를 정적 행동 결과처럼 만들지 않는다. 실제 goal runner는 기존대로 MP4만 기록한다.

`config/behavior_afs_corridor_luna.json`: 양쪽 gpt-6-luna, seed17,
각 방법 유효6/최대 시도6, cold2, AFS 제안 최대2. 총 로봇 최대120 + AFS2 호출.
기존 3+3 Luna 연결 점검보다 큰 예산이며 **설정/plan만 검증했고 live 실행하지 않았다**.
여섯 유효 AFS 실행이 끝나면 cold 이후 llm/boundary/exploration/repeat 슬롯을 한 번씩 지난다.
관측 bracket이 없으면 boundary 슬롯은 추가 LLM 가설 요청이며 경계 발견으로 표시하지 않는다.
새 domain_id는 `450535f386008aff2d45f3b1db25fc751233e9ef7c07c663c7197cc28b2ae16a`이다.

## 검증 중 발견한 문제와 수정

초기 새 지도 테스트에서 `pytest.approx`에 nested list를 전달한 테스트 작성 오류를 수정했다.
그 뒤 실제로 정적 지도/로봇 내부 계획기의 시작 셀이5cm 어긋나는 것을 발견했다.
원인은 바닥 최소 X를 literal −0.2로 쓴 값과 MuJoCo geometry의 `4.0 - 4.2` 계산값이
달라 grid boundary에서 셀 index가23/24로 갈리는 것이었다.
새 지도에서 실제 floor center/half-size와 동일한 계산을 사용하고 반경0.40 표현도 맞췄다.
로봇의 계획기/행동 전략을 바꾸지 않고 초기 지도와 실제 관측 기반 경로의 전체 좌표를 비교한다.

초기 미리보기 `20260928T082620_472498Z`와 중간 미리보기 `20260928T082911_396216Z`는
삭제/덮어쓰기하지 않았다. 현재 코드에 맞는 최종 확인 결과는 아래 경로다.

## 실행 명령과 확인 결과

`scene2test`에서 관련 회귀 테스트:

```bash
uv run --no-sync pytest tests/client tests/test_clear_path.py tests/test_corridor_scene.py tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_robot_goal_agent.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot_vlm.py tests/test_robot_push_dispatch.py tests/test_robot_push_alignment.py -q
```

중간 전체 검증: **335 passed in 90.12s**.
최종 메타데이터/미리보기 CLI 테스트 추가 후 핵심 재검증:

```bash
uv run --no-sync pytest tests/test_corridor_scene.py tests/client/test_corridor_campaign.py tests/client/test_luna_pilot.py tests/client/test_afs_pilot.py tests/test_goal_outcome_runner.py -q
```

**68 passed in 50.81s**. 수정 파일 Ruff check와 git diff --check 통과.
마지막 변경까지 포함해 위 전체 회귀 명령을 다시 실행한 결과는
**336 passed in 107.20s**다. 이전335개에 offline preview CLI 검증1개가 추가되었다.
CPU geometry/접촉/자산 검사, mock HTTP, synthetic campaign, scripted controller 테스트이며
실제 Luna/VLM 또는 CUDA 보행 능력의 성공률 증거가 아니다.
합성 캠페인은 두 방법 각6회 실행과 중단 재개 후보 일치, 5축 모델 전달, geometry bracket,
mixed 반복/다축·중력 변경의 bracket 제외, XML 불일치 중단을 확인했다.

```bash
uv run --no-sync python tools/preview_corridor_scenes.py --audit-robot
```

최종 산출물:
`/workspace/g1_failure/runtime/corridor_previews/20260928T083313_637798Z/report.html`

세 장면 모두 G1 구동기29개/관절 주소/보행 관측 벡터 일치. GPU 추론·physics step·API 호출0회.
scene_002의 지도 PNG를 직접 확인했다. 명확히 정적 지도/실제 궤적 아님으로 표시되어 있다.
정적 경로 존재 여부 true/false/true를 실제 로봇의 PASS/FAIL로 기록하지 않았다.

```bash
uv run --no-sync python tools/run_afs_pilot.py --config config/behavior_afs_corridor_luna.json
```

PLAN_ONLY exit0. 두 모델 Luna, scene schema v2, 5축 bounds, 12회 최대 시도와120+2 호출 상한 확인.
캠페인 생성·API·로봇 실행은 없었다.

## 문서·다음 단계·제약

`docs/CORRIDOR_AFS.md`, README, roadmap/measurement plan, AGENTS에 실행법과 범위를 반영했다.
다음은 `corridor_wide.json`에서 Luna 로봇10회 호출로 실제 성공 대조를 확인하는 것이다.
그 이후 예산 검토를 거쳐 새 5축 campaign을 실행한다. 개발 자료를 무료 warm history로 넣지 않는다.

- 실행 코드가 바뀌므로 과거 코드로 동결된 캠페인을 현 코드로 재개하면 drift 검사가 막는다.
  검사를 끄거나 lock을 바꾸지 말고 기존 코드 환경에서 재개하거나 새 캠페인을 만든다.
- 최초 goal-only 평가, 시간 기본 상한 없음, 로봇의 자율 행동 선택을 유지했다.
- no_path는 조작까지 포함한 불가능성 증명이 아니다. 초기 경로 없음 필터를 추가하지 않았다.
- 좁은 통로/넓은 통로는 새 실패 유형 라벨이 아니며 taxonomy coverage는 여전히 미측정이다.
- 실제 성공 대조·다중 장애물/미로·지형·점프·유형 detector·회귀 실행은 이번에 완료되지 않았다.
- INCONCLUSIVE 비용 누락과 history token 절감도 후속 작업으로 남는다.
