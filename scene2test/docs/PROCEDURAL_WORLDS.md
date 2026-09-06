# 랜덤 실내 환경 · SceneGraph · 이동 지도

2026-09-06. 첫 구현은 **단층 정적 환경 생성**이다. G1 내비게이션, LLM 편집, 서버 scene registry 등록은 아직 포함하지 않는다.

## 실행

`scene2test` 디렉터리에서:

```bash
PYTHONPATH=src .venv/bin/python -m procedural_world --mode rooms --seed 0
PYTHONPATH=src .venv/bin/python -m procedural_world --mode maze --seed 0
```

선택적으로 실제 MuJoCo 카메라 이미지를 생성한다. MuJoCo 및 headless EGL 드라이버가 필요하다.

```bash
PYTHONPATH=src MUJOCO_GL=egl .venv/bin/python -m procedural_world --mode rooms --seed 7 --render-3d
```

기본 출력: `/workspace/g1_failure/runtime/worlds/<mode>_<seed>_<revision-prefix>/`.
같은 출력 디렉터리가 있으면 **덮어쓰지 않고 실패**한다. 재검증은 다른 `--output-root`를 사용한다.

## 생성 계약

`Config → SceneSpec → MuJoCo XML / SceneGraph / NavigationMap`.

- `maze`: randomized DFS로 한 칸 폭의 연결 미로를 생성한다.
- `rooms`: 서로 겹치지 않는 직사각형 방을 난수 배치하고 L자 복도로 연결한다.
- 셀 단위 solid 영역은 3D box 벽이며, 자유 셀 안에 별도 box 장애물을 넣는다.
- 장애물 추가 후 시작→목표 및 모든 방 중심의 연결을 다시 검사한다. 미로의 모든 가지 접근성을 보장하지는 않는다.
- 요청한 방/장애물 수를 수용하지 못하면 조용히 줄이지 않고 명시적으로 실패한다. 다른 seed, 더 큰 지도 또는 적은 개수로 재설정한다.
- 재현 식별자는 seed만이 아니라 전체 config, 생성기 버전, 최종 geometry를 포함한 SHA-256이다. Python 난수 구현 변경에 대비해 최종 SceneSpec도 저장한다.
- 모든 position/size는 **world frame, meter, full extents**이다. XML geom size만 MuJoCo 규약에 맞춰 half extents로 변환한다.

## 설정

| 설정 | 기본값 | 의미 |
|---|---|---|
| mode | rooms | rooms 또는 maze |
| seed | 0 | 로컬 난수 상태; global RNG를 변경하지 않음 |
| width / height | 15 / 15 | 홀수 셀 수, 각 9–51 |
| cell-size-m | 1.2 | coarse layout 한 셀의 길이 |
| room-count | 4 | rooms에서만 사용, 정확한 개수 요구 |
| obstacle-count | 6 | 배치 변경 가능한 정적 장애물 수 |
| robot-radius-m | 0.3 | 원형 footprint 근사, G1 실측 인증값 아님 |
| safety-margin-m | 0.05 | 추가 여유 공간 |

Python `Config`에서는 `wall_height_m`(2.4), `subdivisions`(6)도 설정할 수 있다.
기본 이동 지도 해상도는 1.2/6=0.2 m이다. 좁은 통로와 큰 footprint/거친 raster 조합은 거부한다.

## 산출물

| 파일 | 내용 |
|---|---|
| scene_spec.json | authoritative config·geometry·regions·연결 topology·spawn/goal |
| scene.xml | 로봇 없는 standalone 정적 MuJoCo 장면 |
| scene_graph.json | 기존 SceneGraph 스키마로 변환한 객체·관계 |
| navigation_map.json | occupancy, footprint-expanded blocked map, 4-connected 기준 경로 |
| preview.png | 위에서 본 지도, 장애물·clearance·경로·시작/목표 표시 |
| scene_3d.png | `--render-3d` 지정 시 실제 MuJoCo 카메라 렌더링 |
| manifest.json | revision, artifact SHA-256/크기, 검증 범위 |

manifest는 마지막에 기록한다. 렌더링/IO 오류로 생성이 중단되어 manifest가 없으면 미완료 bundle이다. PNG는 정적 환경 증거이며 로봇 주행 영상이 아니다.

## SceneGraph와 이동 지도

SceneGraph에 floor, wall/obstacle, spawn, goal, 방 영역을 기록한다. `on`, `inside`, `connected_via_corridor` 관계를 사용한다. 방 연결은 생성기의 의도된 topology이며 실제 통과 여부는 이동 지도에서 별도로 검사한다. maze는 객체 중심 그래프이고 교차로별 topology graph는 아직 생성하지 않는다.

기존 Panda 코드와 JSON 형식은 공유하지만 navigation의 world frame/역할은 다르다. `meta.legacy_panda_afs_compatible=false`이며 기존 pick/place feature extractor에 바로 넣으면 안 된다. `movable=true`는 에피소드 간 편집 가능성이다. XML에서는 해당 물체도 worldbody의 정적 geom이다.

NavigationMap은 행이 +Y, 열이 +X이며 원점은 (0,0)이다. `occupied`는 원 형상의 셀 중심 점유, `blocked`는 실제 경로 계획용 보수적 지도다. box와 셀 중심의 정확한 XY 거리로 판정하며 robot radius + margin + half-cell-diagonal을 적용한다. 따라서 free cell 전체가 정적 원형 footprint에 대해 안전하도록 보수적으로 계산한다. 기준 경로는 BFS의 4-neighbor 경로이고 실제 spawn/goal까지 연결된다.

이 검증은 로봇의 회전 자세·팔·발 궤적·균형·마찰·동적 장애물까지 보장하지 않는다. 정확한 pose/map을 사용하는 GT 기준이며 센서 기반 인식 또는 SLAM 검증도 아니다.

## 검증과 다음 단계

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_procedural_world.py -q`
- 기존 Client/Server 포함: `PYTHONPATH=src .venv/bin/python -m pytest tests/client tests/server tests/test_procedural_world.py -q`
- seed 재현성, 다른 seed, 잘못된 설정, 무효 경로, artifact hash/overwrite 거부, SceneGraph roundtrip, XML/graph geometry 일치, MuJoCo compile 테스트를 포함한다.
- MuJoCo가 없는 환경에서는 compile 테스트만 skip된다.

다음 연결은 (1) robot 모델의 joint/actuator 순서를 유지하며 생성 geometry를 합성하고 요청한 scene revision을 worker가 실제로 로드하도록 연결, (2) pose/map 기반 경로 추종, (3) base scene mutation 및 AFS이다. 현재 서버를 자동 재시작하거나 기존 controller를 변경하지 않았다.
