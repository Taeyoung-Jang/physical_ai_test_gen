# 다중 장애물 AFS — goal-agent 장면 확장 v3

2026-09-28 UTC. `clear-path-obstacles-v3`는 기존 5축 통로에 고정 장애물 2개를
추가한 **17축 장면 도메인**이다. 비교 파일럿 완료를 개발의 선행 조건으로 두지 않고
장면 → MuJoCo/로봇 관측 → 행동 메모리 → 다음 AFS 제안까지 연결했다.
실제 G1의 성공률이나 AFS 우월성은 이 구현만으로 확인되지 않는다.

후속 검증: 사용자 실행 slalom 1회가 Luna/CUDA에서 **VALID PASS**로 확인됐다.
내부 계획기로 세 물체 사이를 걸어 통과했으며 밀기/낙상/로봇–장애물 접촉 기록은 없었다.
이는 하나의 개발 장면 성공이지 일반 성공률이나 AFS 비교 결과가 아니다.
[상세 결과와 기록 보완점](../../.workhistory/2026-09-28_obstacle_slalom_live_result.md)을 참조한다.

후속 구현: 종료 후 응답 사용량/obstacles 소스 해시를 보완하고,
[3개 근거 기반 유형 규칙·회귀 실행기](BEHAVIOR_TAXONOMY_AND_REGRESSION.md)를 추가했다.
새 obstacle 캠페인은 `taxonomy_profile=goal-behavior-v1`로 자기 arm/seed의 근거만 AFS에 전달한다.
6종 전체 검증이나 실제 4/6 발견을 뜻하지 않는다. 아래의 미구현 언급은 기하 확장 당시 범위다.

## 제어 가능한 장면 요소

| 축 | 범위 | 의미 |
|---|---|---|
| `box_mass_kg` | 0.2–10 kg | 기존 동적 상자 질량 |
| `box_friction`, `floor_friction` | 각각 0.05–1.5 | 상자/전체 바닥 sliding friction |
| `corridor_width_m` | 1.6–4 m | 벽 안쪽 폭 |
| `box_lateral_fraction` | −1–1 | 기존 상자의 좌우 배치 비율 |
| `obstacle_1_x_m`, `obstacle_2_x_m` | 2.25–2.75 / 5.25–5.75 m | 고정 장애물 중심 X |
| `obstacle_N_lateral_fraction` | −1–1 | 장애물 N의 좌우 배치 비율 |
| `obstacle_N_size_x_m`, `obstacle_N_size_y_m` | 각각 0.2–0.8 m | 장애물 로컬 좌표계의 전체 가로/세로 길이 |
| `obstacle_N_height_m` | 0.1–1.2 m | 바닥부터의 높이 |
| `obstacle_N_yaw_deg` | −90–90° | 월드 +Z 축 회전 |

`N`은 1 또는 2다. 추가 장애물은 항상 2개이며 정적인 충돌 물체다. 기존 중앙 상자만
동적이며, 밀기 실행기의 대상도 기존 `clear_box_geom`으로 유지한다. 장애물의 수·이동성·
형상 종류(현재 직육면체)는 이번 도메인의 탐색 축이 아니다.

좌표계는 world/meter, 회전은 degree이다. XML에는 quaternion으로 기록해 외부 로봇
XML의 degree/radian 설정에 영향을 받지 않는다. 장애물의 좌우 위치는 아래처럼 계산한다.

```text
half_y = (abs(sin(yaw)) * size_x + abs(cos(yaw)) * size_y) / 2
y = lateral_fraction * (corridor_width / 2 - half_y - 0.05)
```

폭·가로·세로·회전 변경은 Y에도 영향을 줄 수 있다. 한 파라미터의 경계 탐색은 이
파라미터화에서의 대조이며, 모든 물리 좌표가 독립적으로 고정된 인과 실험이 아니다.
yaw의 주기성과 직육면체 대칭으로 서로 다른 파라미터가 동등한 형상을 만들 수 있으므로
파라미터 거리/사례 수를 물리적 다양성이나 실패 유형 수로 해석하지 않는다.

전체 범위에서 초기 벽 간격 5 cm를 확보하고, X 구간을 분리해 출발점·목표점·초기 상자와
겹치지 않도록 했다. Random은 **17개 파라미터의 독립 균등 표본**을 사용한다.
도달 가능 장면만 뽑는 거절 샘플링이나 숨은 보정/clipping은 없다. 물리적 Y 좌표의
분포는 독립 균등이 아니다. 정적 경로가 없는 장면도 삭제하거나 자동 FAIL로 판단하지 않는다.

## 무엇을 검증하는가

- 여러 장애물 사이의 우회, 접근 공간, 방향 전환, 막힌 경로에서의 로봇 선택을 시험할 수 있다.
- AFS는 성공 쪽 완화·다른 축 대조·관측 경계·독립 탐색·반복 슬롯을 기존과 동일하게 사용한다.
- SceneGraph의 `size`는 월드 AABB 크기다. 정확한 로컬 크기와 회전은 `extra.local_size_m`,
  `extra.rotation_matrix`, `extra.yaw_deg`에 저장한다. 객체 ID와 MuJoCo geom 이름도 연결한다.
- 로봇은 실제 MuJoCo의 최신 geometry와 카메라 이미지를 받는다. 장애물이 평가용 그림에만
  나타나는 것이 아니다. AFS가 만든 reference path나 행동 지시는 전달하지 않는다.
- 내부 계획기는 기존 그대로 회전 장애물의 **보수적인 AABB 투영**을 피한다. 낮은 장애물도
  차단 영역이다. 높이 변경은 렌더링·물리 접촉을 바꾸지만, 넘기/점프 기술을 부여하지 않는다.
- 목표 `[7, 0]`과 출발 `[1, 0]`, 로봇 정책·기술·반경·episode 예산은 AFS가 수정하지 않는다.
- 접촉·넘어짐은 행동 근거다. 목표를 달성하면 PASS, 유효 실행의 목표 미달은 FAIL,
  실행 오류는 INCONCLUSIVE라는 `goal_outcome_v1` 의미를 유지한다.
- 캠페인은 결과 집계 전에 scene-config/XML 일치를 검사한다. 고정 장애물의 위치·크기·회전·
  마찰 불일치는 제외한다. 검증된 장면 노드만 정규화하여 단일 축 관측 경계를 만들며,
  로봇/solver 등 나머지 XML 차이를 지우지 않는다.

임의 미로·여러 방·경사/계단 번들을 이 goal-agent에 적재하는 기능은 **아직 별도 작업**이다.
기존 procedural-world/terrain 생성기의 지원 범위와 혼동하지 않는다. 점프·새 물체 집기,
실패 유형 detector, 자동 회귀 실행도 이번 변경으로 구현되었다고 주장하지 않는다.

## 실행 방법

모든 명령은 아래 디렉터리에서 실행한다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

### 1. 먼저 환경 확인 — 무료, API/GPU 추론 없음

```bash
uv run --no-sync python tools/preview_corridor_scenes.py --preset obstacles --audit-robot --output-root /workspace/g1_failure/runtime/obstacle_previews
```

4개 개발용 장면(우회 배치, 회전 장애물, 낮은 블록, 좁은 차단 배치)을 생성한다.
`REPORT`의 HTML과 `scene_*/map.png`, scene-config/SceneGraph/map/XML을 확인한다.
`--audit-robot`은 실제 외부 G1 자산을 CPU로 조립하고 29개 구동기·관절 주소·보행 입력 보존을
검사할 뿐, 정책 추론이나 physics step을 실행하지 않는다. 자산이 없으면 이 옵션을 뺀다.
이 그림은 **정적 지도와 참고 경로**이며 실제 로봇 궤적이 아니다. GIF/MP4는 만들지 않는다.

### 2. 새 17축 캠페인 예산만 확인 — 유료 실행 없음

```bash
uv run --no-sync python tools/run_afs_pilot.py --config config/behavior_afs_obstacles_luna.json
```

Luna/Luna, AFS와 Random 각 6회 유효 실행/최대 6회 시도, 총 12회,
로봇 API 최대 120회 + AFS 최대 2회. 초기 2회씩과 반복도 예산에 포함한다.
오류가 나면 예산 내 유효 횟수를 채우지 못할 수 있다. 이는 **연결 확인용 소규모 설정**이지
17차원 공간을 충분히 탐색하거나 통계적 우월성을 입증하는 규모가 아니다.
기본 120초 시뮬레이션 제한을 다시 도입하지 않았다. 호출 상한은 금액 상한이 아니다.

### 3. 사용자가 비용을 확인한 후 선택적으로 실행

README의 `OPENAI_API_KEY` 설정 후, 한 장면의 로봇 동작만 보려면:

```bash
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --scene-config config/scenes/obstacles_slalom.json
```

AFS 전체 새 캠페인 실행은:

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --config config/behavior_afs_obstacles_luna.json
```

실제 실행은 MP4를 기록하며 GIF는 만들지 않는다. 각각 runtime/robot_goal_agent,
runtime/afs_benchmark 아래 새 폴더를 만든다. API/실행 오류는 원인을 기록하고 중단한다.

**기존 v1/v2 캠페인에 이 config를 덮어쓰거나 코드 해시 검사를 우회하지 않는다.**
v3는 새 domain ID다. v1/v2 장면 생성 규칙은 유지했지만 코드 fingerprint는 변경되므로
기존 campaign 재개에는 원래 고정된 코드 환경이 필요하다. 과거 recovery 캠페인도 동일하다.
이전 PASS/FAIL 및 비용 기록을 새 실험에 몰래 합치지 않는다.

## 검증과 남은 작업

CPU MuJoCo로 여러 seed와 경계값의 정합성을 검사하고, 실제 runner의 제어기/API를 대역으로
바꿔 장애물이 관측·접촉 기록에 들어오는지 검사한다. 합성 archive 기반 캠페인 테스트는
17축 제안/단일 축 경계/재개/같은 예산/결과 내보내기를 검증한다. 합성 결과는 G1 성능 근거가 아니다.
실행 당시 테스트 수와 산출물은 [.workhistory](../../.workhistory/2026-09-28_obstacle_geometry_afs.md)에 기록한다.

다음 개발은 (1) 근거 기반 실패 유형 측정, (2) 저장된 사례를 재실행하는 회귀 runner,
(3) 범용 방/미로·terrain 번들 연결이다. 연구 대상 로봇의 점프/조작 기술 개발은 독립 과제다.

API 출력은 기존 strict schema 및 현재 domain의 axis/evidence-ID enum을 유지한다.
새 17축도 이 제한으로 연결했으며, 의미·범위 검증은 호스트에서 다시 수행한다.
[OpenAI 공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를 참고했다.
