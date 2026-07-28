"""scene3d — 임의의 3D scene 데이터를 SceneGraph로 만들고 로봇 시뮬레이션을 돌리는 패키지.

2단계 아키텍처:
  1. Scene Graph 생성  : sources.generate_scene_graph() — 입력 형식(HM3D 데이터셋
     scene id / 임의 mesh 파일 / 이미 만들어진 SceneGraph JSON)을 판별해 적절한
     백엔드로 위임하고 표준 SceneGraph(scene_graph.py)를 만든다.
  2. 로봇 시뮬레이션    : robot_workspace.setup_workspace() — 표준 SceneGraph +
     로드된 3D mesh만 있으면 되고, 그 SceneGraph를 누가/어떻게 만들었는지는 알 필요
     없다. perception.py(RGB-D 인식)와 failure_search.py(Active Failure Search)도
     이 위에서 동작한다.

모듈 구성:
  - sources.py         : 입력 판별 + 디스패치 (SceneSource, resolve_source,
                         generate_scene_graph)
  - hm3d_dataset.py    : HM3D 데이터셋 백엔드 — tar 아카이브 인덱싱 + 추출
  - hm3d_semantics.py  : HM3D 데이터셋 백엔드 — semantic annotation → SceneGraph
  - mesh_loader.py     : GLB → OBJ 변환 캐시 + PyBullet static body 로드 (범용)
  - robot_workspace.py : 지지면 위 작업공간 구성 + oracle 연결 (범용, Stage 2)
  - perception.py      : RGB-D 인식 → SceneGraph + GT 비교 (범용)
  - failure_search.py  : Active Failure Search 세션 (범용)

"hm3d_" 접두사가 붙은 두 모듈만 HM3D 데이터셋 형식에 실제로 결합되어 있고,
나머지는 어떤 3D scene 소스로 만든 SceneGraph든 그대로 받아들인다.
"""
