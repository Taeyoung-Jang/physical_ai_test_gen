# 랜덤 환경·SceneGraph·이동 지도 첫 구현

날짜: 2026-09-06 UTC. 요청: 랜덤 환경, SceneGraph, 이동 지도 작업 시작.

## 범위 및 변경

`scene2test/src/procedural_world/`를 추가했다. Config/SceneSpec/Box/Region, local seeded generation, 원형 footprint 기반 보수적 raster/BFS, 기존 SceneGraph adapter, standalone MuJoCo XML exporter, PNG 지도와 optional 실제 3D 렌더링, manifest/hash/no-overwrite CLI를 구현했다.

두 모드: randomized DFS maze와 분리된 rectangular rooms + L corridors. default 15x15 coarse cells, 1.2m cell, 4 rooms(rooms only), 6 static editable obstacles. 작은 전체 prototype을 먼저 완성했고 계단/복층/동적 장애물/LLM 편집은 포함하지 않았다.

로봇 없는 정적 XML이므로 기존 G1 정책이나 서비스 상태를 변경하지 않는다. 서버 registry 자동 등록이나 G1 rollout도 하지 않았다. 기존 SceneGraph 형식을 재사용하되 navigation/world-frame 메타데이터를 명시하고 legacy Panda AFS 직접 호환을 주장하지 않는다.

## 검증

1. 새 테스트: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_procedural_world.py -q` → 21 passed, 16.24s.
2. 회귀: `PYTHONPATH=src .venv/bin/python -m pytest tests/client tests/server tests/test_procedural_world.py -q` → 76 passed, 1 warning, 58.92s. 경고는 기존 Starlette/httpx deprecation.
3. Ruff check → All checks passed. git diff --check → 통과.
4. 기본 설정으로 rooms/maze 각각 seed 0–9 총 20개 생성·이동 지도 검사 → 모두 start-goal 및 해당 방 중심 연결 통과. 이 추가 sweep은 메모리상 생성 검증이며 20개 실행 영상을 저장한 것이 아니다.
5. 두 mode의 seed 0은 아래 CLI로 실제 bundle을 저장하고 MuJoCo EGL 렌더링했다. 렌더링 이미지와 평면 지도를 직접 확인했다.

```bash
PYTHONPATH=src MUJOCO_GL=egl .venv/bin/python -m procedural_world --mode rooms --seed 0 --render-3d
PYTHONPATH=src MUJOCO_GL=egl .venv/bin/python -m procedural_world --mode maze --seed 0 --render-3d
```

출력:
- `/workspace/g1_failure/runtime/worlds/rooms_0_8adb1369e88b/`
- `/workspace/g1_failure/runtime/worlds/maze_0_9d71f89fa4e8/`

각 bundle: scene_spec.json, scene_graph.json, navigation_map.json, scene.xml, preview.png, scene_3d.png, manifest.json. PNG는 환경 렌더링이며 보행 영상이 아니다. GPU 정책 실행은 이번에 하지 않았다.

## 설계상 주의

- 기본 0.3m robot radius/0.05m margin은 실험용 가정이다. G1 전신 및 발 궤적의 안전 증명은 아니다.
- 장애물 거부 샘플링은 시작/목표와 방 중심 연결을 유지한다. 미로 모든 가지의 접근성을 보장하지 않으며 경로 밖 가지는 장애물로 차단될 수 있다.
- SceneGraph의 movable은 episode 사이 편집 가능성이다. 물리 실행 중에는 static geom이다.
- SceneGraph와 geometry는 같은 ID/좌표/크기로 생성하며 XML half extents 변환을 테스트한다. 연결 관계는 topology이고 실제 footprint 접근성은 별도로 검사한다.
- artifact는 덮어쓰지 않는다. 미완료 export는 manifest가 없으므로 정상 bundle로 취급하지 않는다.

## 환경 문제 및 대응

이 환경의 apply_patch update/view_image 읽기 helper가 bwrap namespace 오류를 냈다. 파일은 승인된 shell read로 읽은 후 apply_patch Add File 방식으로 전체 내용을 보존하여 수정했다. 자동 포맷은 Ruff를 사용했다. 이미지 확인은 승인된 읽기에서 base64로 전달했다. 사용자 기존 변경은 보존했다.

## 다음 연결

생성 scene의 revision을 서버가 실제로 로드하도록 연결하고 G1 asset과 안전하게 합성한 뒤, GT pose/map 기반 waypoint follower를 연결한다. 이번 작업을 미로 자율주행 또는 AFS 연결 완료로 해석하지 않는다.

사용법: [PROCEDURAL_WORLDS.md](../scene2test/docs/PROCEDURAL_WORLDS.md).
