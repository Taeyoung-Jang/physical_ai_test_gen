# 통로 폭·상자 배치 기반 AFS — 첫 기하 확장

2026-09-28 UTC. 기존 고정 장면 3축과 구분되는 opt-in `clear-path-corridor-v2`.
범위는 새 장면 → 실제 goal-agent 관측/물리 → 행동 메모리 → 다음 AFS 제안 연결이다.
미로·다중 장애물·경사·계단·점프 통합을 완료한 것은 아니다.

## 구현한 것

| 탐색 축 | 범위 | 의미 |
|---|---|---|
| box_mass_kg | 0.2–10 kg | 동적 상자 질량 |
| box_friction | 0.05–1.5 | 상자 sliding friction |
| floor_friction | 0.05–1.5 | 전체 바닥 sliding friction |
| corridor_width_m | 1.6–4.0 m | 남/북 벽 안쪽 사이 폭 |
| box_lateral_fraction | −1–1 | 허용된 좌우 배치 범위에서 상자 위치 비율 |

8m 길이의 직선 통로이며 기존 v1의 옆 배치 공간(side bay)은 없다.
상자는 0.8×1.1×0.7m로 유지하고 X=4m에 둔다. Y는 다음과 같다.

```text
box_y_m = box_lateral_fraction × (corridor_width_m / 2 − 0.55 − 0.05)
```

좌우 비율은 미터 단위가 아니다. 전체 domain에서 초기 상자–벽 간격을 최소5cm 확보한다.
비율이 0이 아닐 때 폭을 바꾸면 상자 Y도 바뀐다. 따라서 "폭 한 축"의 대조는
이 파라미터화에서의 한 축이며, 물리 좌표의 모든 다른 성분이 고정된 인과 실험은 아니다.
Random은 다섯 파라미터에서 독립 균등 표본을 뽑는다. 상자 Y와 폭은 독립이 아니다.

고정 사항:

- 로봇 시작 `[1, 0]`, 최종 목표 `[7, 0]`, 0.25m 이내에서 1초 유지.
- 로봇 모델·프롬프트·관측 범위·내부 계획기·보행/밀기 실행 기능·episode 예산.
- planner 반경/여유를 AFS가 바꿀 수 없다. 상자 크기도 이번에는 고정한다.
- 평가기는 로봇의 경로·우회 방향·밀기 여부를 지정하지 않는다.
- 목표-only 평가를 유지한다. 접촉·낙상·기술 실패는 관측이며 곧바로 목표 FAIL은 아니다.
- 정적 no_path는 로봇의 실패나 조작 포함 불가능성 증명이 아니다. 이를 이유로 표본을 버리지 않는다.

`clear_path`의 기존 SceneGraph/XML 생성 경로를 확장했다. 범용 procedural_world 번들 전체를
goal-agent에 적재하는 기능과는 다르며, 외부 서버/별도 g1-local-nav를 바꾸지 않았다.
SceneGraph의 객체 ID와 MuJoCo geom 이름 대응을 명시한다. 새 장면에는 지정된 상자 목적지
`push_goal`이 없고, 벽 접촉 주석도 diagnostic_only이다.

## 먼저 눈으로 확인하기 — API/GPU 추론 없음

`scene2test` 디렉터리에서:

```bash
uv run --no-sync python tools/preview_corridor_scenes.py --audit-robot
```

`--audit-robot`은 외부 G1 XML/mesh를 CPU로 읽어 구동기·관절 주소·보행 입력 보존만 검사한다.
CUDA 추론/로봇 행동/physics step은 실행하지 않는다. 자산 없이 정적 지도만 필요하면 옵션을 뺀다.
기본 산출물 위치는 `/workspace/g1_failure/runtime/corridor_previews/<시각>/`이다.
출력되는 `REPORT`를 열면 세 장면의 지도 PNG와 설정·SceneGraph 링크를 볼 수 있다.
GIF나 실제 행동 동영상은 생성하지 않는다. 미리보기는 움직이지 않은 환경이다.

| 개발용 장면 파일 | 조건 | 확인한 정적 지도 결과 |
|---|---|---|
| config/scenes/corridor_wide.json | 폭4m, 상자 중앙 | 우회 경로 있음 |
| config/scenes/corridor_narrow.json | 폭1.6m, 상자 중앙 | 초기 정적 경로 없음 |
| config/scenes/corridor_offset.json | 폭2.4m, 상자 한쪽 배치 | 반대쪽 우회 경로 있음 |

이 셋은 **성공/실패 라벨이 없는 개발용 조건**이다. 넓은 장면도 실제 로봇이 성공한다고
아직 검증하지 않았다. 그림의 경로를 로봇에게 정답으로 주지 않으며 정책은 자신의
`plan_path`/`navigate_to` 호출로 현재 관측에서 경로를 계산한다.

## 다음 실제 확인 — Luna 넓은 통로 1회

README대로 API 키를 설정한 같은 터미널에서 실행한다. 아래는 유료 API/GPU 실행이다.
최대 로봇10회 호출이며 시뮬레이션 시간 기본 상한은 두지 않는다.

```bash
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --scene-config config/scenes/corridor_wide.json
```

목표 PASS/FAIL, 목표 거리 변화, 실제 선택 행동, 재계획, 호출/토큰/지연을 확인한다.
밀기는 사용 가능할 뿐 강요되지 않는다. 결과는 기존
`/workspace/g1_failure/runtime/robot_goal_agent/<시각>/`에 MP4와 함께 저장된다.
goal runner는 초기 `scene_graph.json`과 `navigation_map.json`도 manifest에 보존한다.
이 초기 지도는 상자가 움직인 이후의 동적 지도나 정답 궤적이 아니다.

다른 개발 조건은 `--scene-config`만 위 표의 파일로 바꾼다. 모델/예산/프롬프트를
함께 바꿔 결과 차이를 환경 효과로 해석하지 않는다. 필요한 반복도 모두 비용을 기록한다.
이 개발 자료는 아래 새 캠페인의 무료 warm history로 삽입하지 않는다.

## 새 5축 AFS/Random 캠페인

2026-09-28: [AFS 가설 중심 선택 v2](AFS_SEARCH_V2.md)를 사용한다. 성공 대조 탐색도
AFS의 역할이며 로봇 코드 개선을 실행 선행 조건으로 요구하지 않는다. 예산을 검토하고
새 캠페인으로 시작한다. 먼저 계획만 확인:

```bash
uv run --no-sync python tools/run_afs_pilot.py --config config/behavior_afs_corridor_luna.json
```

유료 전체 실행:

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --config config/behavior_afs_corridor_luna.json
```

설정은 양쪽 Luna, seed17, AFS·Random 각6회 유효 목표/최대6회 시도다.
방법별 초기2회 이후 AFS의 llm → boundary → exploration → repeat 슬롯을 한 번 실행한다.
관측 PASS/FAIL bracket이 없으면 boundary 슬롯은 추가 가설 요청이지 경계 발견으로 세지 않는다.
총 **로봇 최대120회 + AFS 최대2회**이며 금액 상한은 아니다. 자동 재시도/Random fallback은 없다.
인프라 오류가 생기면 pilot이 중단하고 유효 목표 미달이 될 수 있다.
기존 Luna 3+3 연결 점검보다 큰 예산이므로 이번 구현 검증에서는 live 실행하지 않았다.

AFS 출력 schema는 해당 캠페인의 5개 axis enum만 허용한다. 범위·근거 참조·context hash는
호스트에서 다시 검사한다. 3축 캠페인은 여전히 3개 축만 허용한다.
OpenAI Docs의 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
지침을 참고해 endpoint/모델/추론 설정은 유지하고 허용 축 schema만 확장했다.

메모리는 실제 scene_config와 XML을 대조한 뒤 장면 소유 노드만 정규화한다.
로봇·물리 옵션·비선언 변경은 비교에서 유지/구분하며 같은 조건의 단일 파라미터
PASS/FAIL만 관측 bracket으로 만든다. 반복 결과가 섞이면 확정 경계로 만들지 않는다.
새 캠페인은 XML/설정 불일치를 유효 goal FAIL로 세지 않고 중단한다.

## 기존 결과·검증 범위

v1 장면/원본 결과/평가를 덮어쓰지 않는다. v2는 별도 domain_id로 보고한다.
이번에는 실행 코드가 바뀌므로 **이전 코드로 동결된 Astra/Luna 캠페인은 그대로 재개할 수 없다**.
기존 drift 검사를 끄거나 lock을 수정하지 않는다. 기존 코드 환경에서 재개하거나 새 캠페인을 만든다.
단일 장면 파일은 기존에도 지원하던 `--scene-config`로 실행한다.
옛 standalone `run_behavior_afs.py`의 suite 생성은 계속 v1 전용이며 v2 탐색은 campaign 경로를 쓴다.

확인 범위: 실제 CPU MuJoCo의 기하/초기 접촉, SceneGraph/XML/지도 일치, G1 자산 구성,
정책 관측 전달, 합성 기록의 전체 탐색 슬롯/재개/예산/경계/거부 테스트.
관련 회귀 테스트 최종336개 통과. [상세 작업·검증 이력](../../.workhistory/2026-09-28_corridor_geometry_afs.md).
테스트의 scripted 로봇 상태나 합성 PASS/FAIL은 실제 Luna/G1 결과가 아니다.
로봇 실제 목표 도달, AFS 우월성, 유형 coverage, 점프/계단 주행은 아직 입증하지 않았다.

남은 개선: 실제 성공 대조 탐색, 다중 장애물/미로 adapter, 구간별 마찰/지형,
미응답/불완전 기록의 비용 가시성, 로봇 feedback 입력 비용, 유형 detector 및 회귀 실행.
유효 manifest가 있는 INCONCLUSIVE의 기록된 token usage는 AFS v2에서 보존한다.
