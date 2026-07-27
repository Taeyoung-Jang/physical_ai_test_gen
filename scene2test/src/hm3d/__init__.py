"""hm3d — Habitat-Matterport 3D(HM3D) 실제 스캔 씬을 PyBullet 시뮬레이션에 로드하는 패키지.

- dataset.py   : tar 아카이브 인덱싱 + 씬 파일 추출
- loader.py    : GLB → OBJ 변환 캐시 + PyBullet static body 로드
- semantics.py : (Phase 2) semantic annotation → 인스턴스 bbox → SceneGraph
"""
