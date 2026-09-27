# 행동 시간선과 Failure Memory — P1 첫 구현

2026-09-27 UTC. [측정 계획](FAILURE_CASE_MEASUREMENT_PLAN.md)의 P1 중
**시간별 행동 근거와 재사용 가능한 사례 자산**을 구현했다. 기존 기록을 읽는 오프라인 분석이며,
로봇 명령·목표 판정·프롬프트를 바꾸거나 API/GPU 실험을 실행하지 않는다.
6종 원인 detector와 자동 회귀 실행은 아직 없다.

## 실행

`scene2test` 디렉터리에서 아래 한 줄을 실행한다. API key는 필요 없다.

```bash
uv run --no-sync python tools/measure_failure_discovery.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T151327_858717Z --with-memory
```

이 특정 과거 실행은 manifest 누락으로 제외된다. `cases=0`은 기능 오류나 실패율 0%가 아니라
**사용 가능한 완결 증거가 없음**을 뜻한다. 새로 완료된 `robot-goal-agent-v5` +
`goal_outcome_v1` 실행은 `--run` 뒤 경로를 그 실행 폴더로 바꾼다.
여러 실행을 모으려면 `--run`을 반복한다. 성공 실행도 함께 입력해야 성공 대조와 경계를 보관할 수 있다.

영상까지 별도 보관하려면 아래처럼 `--bundle-video`를 추가한다.
이것은 기존 MP4 복사 옵션이지 새 영상을 렌더링하는 옵션이 아니다.

```bash
uv run --no-sync python tools/measure_failure_discovery.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T151327_858717Z --with-memory --bundle-video
```

기본 출력은 `/workspace/g1_failure/runtime/failure_measures/<UTC timestamp>/`다.
명시적인 새 폴더는 `--output-dir`로 지정한다. 원본 run 내부나 기존 출력 폴더에는 쓰지 않는다.
[P0 입력 계약](FAILURE_DISCOVERY_MEASURES.md)의 `--input`과도 조합할 수 있다.
`--with-memory`를 생략하면 기존 P0 측정 출력만 생성한다.

## 무엇을 열어 보면 되는가?

터미널의 `MEMORY=.../memory/index.html`을 연다. 실패 사례뿐 아니라 성공 대조와
반복 결과가 섞인 사례도 나온다. `행동 근거` 링크에서 목표 결과, 시간 구간, 도구 결과,
물체 이동량, 로그 파일·행 번호를 확인한다. 검증된 MP4가 있으면 해당 시간 링크도 제공한다.

```text
<measurement output>/
  report.html, metrics.json, metrics.csv, episodes.jsonl, manifest.json
  memory/
    index.html, memory.json, manifest.json
    cases/<case_id>/
      case.json, REPRODUCE.txt, scene_config.json (지원 장면만)
    evidence/<evidence_id>/
      index.html, behavior.json
      protocol.json, result.json, scene.xml, states.jsonl, decisions.jsonl
      events.jsonl, robot_audit.json, observation_*.json, tool_*.json, ... (있는 파일만)
      rollout.mp4 (--bundle-video일 때만)
```

- 기본 MP4 링크는 원본 실행 위치를 가리킨다. 보고서만 PC로 옮기거나 HTTP 제공 범위 밖이면
  재생되지 않을 수 있다. 이동 가능한 보고서가 필요하면 `--bundle-video`로 생성한 출력 폴더 전체를 옮긴다.
- MP4 시간 링크는 시뮬레이션 시각에 프레임 여유를 둔 근사 탐색이다. 프레임 단위 동기화의 증거가 아니다.
- HTML은 가독성을 위해 발–바닥 지지 접촉을 제외한 최대 200개 구간을 표시한다.
  지지 접촉을 포함한 전체 구간은 `behavior.json`에 남는다.
- GIF는 생성하거나 복사하지 않는다. 기존 GIF/MP4/로그를 지우지 않는다.
- 알려진 파일만 선택 복사하며 API 원문·요청/응답 전송 로그는 제외한다.
  알려진 비밀키 필드·키 문자열이 JSON에 있으면 내보내기를 거부한다. 임의 자유문/이미지에 대한
  완전한 개인정보 검출기는 아니므로 외부 공개 전 별도 확인이 필요하다.

## 계측 의미와 한계

| 항목 | 지금 측정하는 것 | 하지 않는 주장 |
|---|---|---|
| Phase | 상태 샘플의 동일 phase 구간, 구간 내 base XY 이동거리·목표 거리 진척 | 샘플 사이 정확한 전환 시각/전체 이동량을 복원하지 않음 |
| Contact | 기록된 시작·종료, 최대 normal force(N), normal impulse(N·s), sampled duration(s) | 의도한 밀기/지지 접촉을 자동 실패로 판정하지 않음 |
| Fall/recovery | 원 평가기가 기록한 낙상·직립 복귀 시각 | 독립적인 동역학 안정성 여유나 near-fall 검출 아님 |
| Action/tool | 관측 버전으로 decision→observation→tool/skill 결과 연결 | tool success는 원래 task goal의 PASS와 다름 |
| Box motion | 감사된 freejoint 상태 주소에서 읽은 상자 XY 순변위·샘플 이동거리(m) | 변위만으로 의도한 밀기 성공·원인을 확정하지 않음 |

`observation_window`는 **관측 수집 시각부터 도구 결과 시각까지**이며 추론 대기와 실행을 함께 포함한다.
과거 기록에 정확한 실행 시작 시각이 없으므로 `execution_start_s=null`로 남긴다.
wall-clock API 지연을 simulation 시각에 더해서 행동 시작을 만들어내지 않는다.
관측 시각이 없으면 구간 시작도 미상이다.

상자 위치는 `robot_audit.json`의 joint/관측 보존·nq/nv 확장과 XML의
`clear_box_free` 구조를 확인한 경우만 읽는다. qpos의 마지막 7개가 무조건 상자라고 가정하지 않는다.
감사 정보 누락/구조 불일치 시 물체 변위는 `UNSUPPORTED`다. phase 분석은 가능한 한 유지한다.

끝나지 않은 접촉·낙상은 `censored=true`이고 종료 시각을 지어내지 않는다.
부분 로그/역행 시각 등은 해당 분석 구성 요소의 `INVALID`/`PARTIAL`과 경고로 드러낸다.
누락된 사건 파일은 사건 0건이 아니다. 모든 근거는 원본 파일 해시와 행/필드를 갖는다.
P0 유효성 검사와 분석 직전의 manifest 재검증을 통과해야 사례로 편입된다.

## 사례, 반복, 경계 후보

같은 robot/task/budget 조건과 같은 장면을 하나의 case로 모은다.
완전히 같은 증거 복사본은 제외하고, 구별 가능한 독립 실행은 반복 PASS/FAIL 횟수에 포함한다.
기존 기록에 영속 실행 UUID가 없으므로 완전히 동일한 독립 실행도 보수적으로 중복 처리될 수 있다.

- `success_control`: 현재 관측이 모두 PASS.
- `observed_failure`: 현재 관측이 모두 FAIL.
- `mixed_outcomes`: 동일 조건의 PASS와 FAIL이 함께 존재.
- `empirical_failure_rate`: 이 사례의 관측 FAIL / 관측 유효 반복 수. 확정 재현 확률이 아니다.
- `primary_family=null`, `causal_status=UNKNOWN`, `confirmation_status=observations_only`.
  접촉·낙상 횟수가 늘어도 공식 6종 coverage는 증가하지 않는다.

관측 bracket은 다음을 모두 충족해야 생긴다.

1. 같은 robot/task/관측/예산 조건이다.
2. `clear-path-fixture-v1` 설정·revision과 실제 scene XML의 일치를 확인했다.
3. XML에서 상자 질량·상자 마찰·바닥 마찰 값만 제외했을 때 나머지 기하/물리 설정이 같다.
4. 세 축 중 하나만 다르고 다른 모든 설정은 같다.
5. 해당 축에서 인접한 관측 값이 서로 반대의 순수 PASS/FAIL 결과다. 중간의 혼합 결과를 건너뛰지 않는다.

질량 단위는 kg, 마찰은 무차원 계수다. 정규화 폭은 현재 지원 domain 폭
(`mass: 0.2–10.0`, `friction: 0.05–1.5`)으로 나눈 값이다.
양 끝의 값·case ID·PASS/FAIL 반복 수·중점 probe를 저장한다. 중점 테스트를 실행하지는 않는다.
한 번씩의 반대 결과도 *관측 후보*로는 남지만 원인·단조성·최소 실패 경계의 증명은 아니다.
로봇 코드 버전이나 호출 예산이 달라진 결과끼리 AFS 경계를 만들지 않는다.

## 재현 자산의 범위

`REPRODUCE.txt`에는 기록된 모델/호출 예산/명시적 시간 예산/push/HTTP timeout에 맞춘
명령 **템플릿**을 제공한다. `{CASE_DIR}`, `{GROOT_ROOT}`를 실제 경로로 바꾸고
`case.json`의 코드·모델·자원 해시를 먼저 확인해야 한다. 시간 무제한이면 `--max-seconds`를 추가하지 않는다.
실제 재실행은 사용자가 별도로 시작하며 `--live`에는 API 비용이 발생할 수 있다.

장면 설정·XML·관측·상태·판정 근거는 선택 bundle로 복사하고 새 manifest에 해시를 남긴다.
외부 ONNX/로봇 mesh/소스 전체/원격 모델을 동봉하거나 재검증하지는 않는다.
따라서 `standalone_robot_environment=false`, `external_dependencies_not_verified`다.
원본 archive의 모든 파일을 복제한 것도 아니므로 bundle을 원본 runner archive로 다시 import하지 않는다.
원래 없는 SceneGraph/지도는 이 과정에서 새로 만든 것처럼 채워 넣지 않는다.
외부 모델은 같은 이름이라도 응답/결과의 동일성을 보장할 수 없다.

## 검증과 다음 범위

CPU 합성 fixture에서 시간 구간, 접촉 후 PASS 보존, 반복 중복/혼합 결과,
단일 축 bracket, 변경된 증거 거부, 선택 복사·MP4 경로 이동·비밀키 제외를 검증했다.
이는 새 GPU/VLM 실행이나 실제 실패 유형 발견 증거가 아니다.

다음 P2에서는 이 근거를 **LLM의 다음 후보 선택/observe**에 연결하고,
동일 유효 rollout 예산의 AFS/Random campaign·중단 재개를 구현한다.
현재 P1은 수집·분석·보관이며 `llm_afs/behavior.py`를 자동으로 갱신하지 않는다.
6종 detector, clearance/goal occupancy, 계획 추종/사람 안전 계측, 자동 회귀 실행은 후속 범위다.
