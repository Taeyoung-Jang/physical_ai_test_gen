# HM3D 실제 3D Scene 시뮬레이션 통합 계획

- 작성일: 2026-07-27
- 데이터: `~/Documents/Workspace/3d_scene_data/habitat-matterport-3dresearch/dataset` (HM3D v0.2)
- 목표: 절차적 가상 씬(테이블+블록)이 아닌 **실제 스캔된 실내 3D scene** 위에서
  기존 파이프라인(kinematic oracle, LAM-guided loop, RGB-D → SceneGraph)을 구동한다.

---

## 1. 데이터셋 실태 (확인 완료)

전부 tar 압축 상태, 총 ~78GB. split별 4종 아카이브:

| 아카이브 | 내용 | minival 크기 |
|---|---|---|
| `*-glb` | 텍스처 포함 whole-house GLB (씬당 1개) | 487MB |
| `*-habitat` | basis 압축 GLB + `.navmesh` (habitat-sim 전용) | 409MB |
| `*-semantic-annots` | `.semantic.glb`(인스턴스 색 인코딩) + `.semantic.txt` | 252MB |
| `*-semantic-configs` | habitat scene_dataset_config JSON | 30KB |

- **minival = 10개 씬** (00800~00809). train은 800개/64GB — 초기 작업엔 불필요.
- **semantic annotation은 일부 씬만 존재**: minival에서는 4개 씬만
  (00800, 00802, 00803, 00808). → 이 4개가 1차 작업 대상.
- 샘플 검증 (00800-TEEsavR23oF, trimesh 로드 성공):
  - 395K faces, 209 geometry 노드(텍스처 아틀라스 조각 — 의미 단위 아님)
  - bounds ≈ 16.6m × 11.1m × 6.1m (2층 주택), trimesh 로드 시 Z-up으로 자동 변환됨
  - `semantic.txt`: 661개 인스턴스, `id,HEX색상,"category",region` 포맷
    (bed, nightstand, cabinet, table lamp, wardrobe …)
  - `semantic.glb`: 인스턴스 ID가 **texture 색으로 인코딩** (vertex color 아님)

## 2. 핵심 설계 결정

**D-1. 시뮬레이터는 PyBullet 유지 (habitat-sim 도입 안 함).**
habitat-sim은 macOS arm64에서 소스 빌드가 필요하고 물리 조작(manipulation)이 약하다.
기존 파이프라인 전체가 PyBullet 기반이므로, HM3D 씬을 **static concave mesh**로
PyBullet에 넣는 것이 최소 변경 경로다. `.navmesh`는 habitat 전용 바이너리라 사용하지
않는다 (모바일 베이스 도입 시 재검토).

**D-2. GLB → OBJ 변환 캐시.**
PyBullet은 GLB를 못 읽는다. trimesh로 GLB → OBJ(+MTL/텍스처) 변환 후
`data/hm3d_cache/<scene>/`에 캐시. visual은 텍스처 OBJ,
collision은 `GEOM_FORCE_CONCAVE_TRIMESH`(static 전용) 사용.

**D-3. 좌표계: glTF Y-up → PyBullet Z-up.**
trimesh가 로드 시 Z-up 변환을 적용하는 것을 확인했다. 변환 후 "바닥 z≈0" 보정
(씬 bounds 최저점 오프셋)을 로더에서 처리한다.

**D-4. 가구는 움직이지 않는다 — 조작 대상은 기존 spawner로 삽입.**
스캔 mesh는 하나로 융합된 static geometry라 서랍/의자를 분리해 움직일 수 없다.
따라서 pick-and-place 대상(target/distractor)은 기존 `ObjectNode` spawner와
Shap-E asset을 **실제 스캔된 지지면(테이블/카운터) 위에** 올려서 만든다.
HM3D가 제공하는 것: 현실적 배경 geometry(장애물·occlusion·충돌), 현실적 RGB-D 관측.

**D-5. Oracle 거리 쿼리는 semantic 인스턴스 bbox로 분리 가능하게.**
395K-face concave mesh 대상 `getClosestPoints`는 느릴 수 있다. 렌더/충돌은 full
mesh, oracle margin 계산은 (성능 문제 시) semantic 인스턴스별 bbox 근사로 대체할
수 있도록 인터페이스를 나눈다.

## 3. 단계별 계획

### Phase 1 — 로더: 실제 씬을 PyBullet에 세우기
새 모듈 `src/hm3d/dataset.py`, `src/hm3d/loader.py`, CLI `tools/load_hm3d_scene.py`.

1. minival 4개 semantic 씬 압축 해제 (`data/hm3d_raw/` 또는 원본 경로 그대로 인덱싱)
2. GLB → OBJ 변환 + 캐시 (trimesh; 텍스처 보존 확인)
3. PyBullet static body 로드 (Z-up 보정, 바닥 z=0), Franka 로봇 임시 배치
4. 기존 `view_scene.py` 스타일 4-뷰 스냅샷으로 **렌더 검증** (프레임이 실제로
   집 내부인지 육안 확인 — 기존 메모리 규칙: 시각 출력은 확인 후 주장)

**완료 기준**: 실제 스캔 집 안에 로봇이 서 있는 스냅샷 PNG.

### Phase 2 — Semantic 파싱: 스캔에서 객체 단위 정보 추출
새 모듈 `src/hm3d/semantics.py`.

1. `semantic.txt` 파싱 → `{instance_id: (category, region, hex_color)}`
2. `semantic.glb` face→instance 매핑: face UV 중심으로 texture 샘플링해 색 → ID
   (기술 리스크 R-2, 아래 참조)
3. 인스턴스별 sub-mesh → 위치/AABB/카테고리 → **실측 기반 SceneGraph** 생성
   (Track A 스키마 호환 — `ObjectNode(role=OBSTACLE, …)`)
4. 지지면 후보 선별: category ∈ {table, counter, desk, nightstand, …} 이고
   상면이 수평이며 일정 면적 이상인 인스턴스 목록

**완료 기준**: 씬 하나에서 "table 3개, bed 1개, …" 인스턴스 목록과 bbox가
JSON(SceneGraph)으로 나온다. → **Scene Graph가 처음으로 '저작'이 아닌
'실데이터 유래'가 됨** (GAP_ANALYSIS §4의 근본 갭 해소 시작).

### Phase 3 — 작업공간 구성: 기존 파이프라인 연결
`scene_builder.py` 확장 (`hm3d_scene` 필드가 있으면 static mesh 우선 로드).

1. Phase 2의 지지면 하나 선택 → 로봇 베이스를 지지면 옆 도달 가능 위치에 배치
2. target/distractor/tray를 지지면 위에 spawn (기존 spawner 재사용)
3. 기존 kinematic check + 6-margin oracle 실행 — collision margin이 이제
   **실제 스캔 가구**와의 거리로 계산됨
4. 단일 케이스 end-to-end: 씬 로드 → mutation → oracle 판정 → GIF

**완료 기준**: HM3D 씬에서 PASS/FAIL 판정 + 애니메이션 GIF 1개.

### Phase 4 — 실제 RGB-D → Point Cloud → SceneGraph (Track B 실동작)
기존 `vision/rgbd_to_graph.py` + GAP_ANALYSIS V-1/V-2 작업과 합류.

1. HM3D 씬 안에서 `capture_rgbd_from_pybullet` → 진짜 클러터가 있는 depth
2. V-1: `extract_object_pointclouds` 픽셀↔포인트 인덱스 버그 수정
3. V-2: PyBullet segmentation buffer를 GT mask로 사용
4. RGB-D 유래 SceneGraph vs Phase 2 semantic GT SceneGraph **비교 평가**
   (위치 오차, 누락 객체, occlusion 실측) — perception 품질을 정량화할 수 있는
   최초의 기준선

### Phase 5 — 실패 탐색 루프를 실제 씬에서
1. `active_failure_search.py` / `lam_guided_loop.py`에 `--hm3d-scene` 옵션
2. mutation space 확장 후보: 로봇 베이스 위치, 카메라 포즈, 지지면 선택,
   씬 선택(4개) — "어느 집 어느 테이블에서 실패하는가"
3. VLA closed-loop: 실제 텍스처 렌더 관측 → G-13(렌더링 분포 격차) 완화 실험

## 4. 리스크

| ID | 리스크 | 대응 |
|---|---|---|
| R-1 | 395K-face mesh에 대한 `getClosestPoints` 성능 | D-5: oracle은 인스턴스 bbox 근사로 분리 |
| R-2 | semantic 인스턴스가 texture 색 인코딩 — UV 샘플링 필요 | face UV 중심 샘플링으로 구현; 실패 시 habitat 커뮤니티의 기존 파서 참고. Phase 1·3은 이것 없이도 진행 가능 |
| R-3 | trimesh OBJ export에서 텍스처 유실 가능 | visual 품질은 Phase 1에서 스냅샷으로 즉시 검증; 유실 시 GLB→OBJ에 obj2gltf 계열 대체 |
| R-4 | TinyRenderer로 대형 텍스처 씬 렌더 속도 | 해상도 축소(320×240), 씬당 1회 로드 후 재사용 |
| R-5 | minival 4개 씬만으로 다양성 부족 | val(30씬)에 semantic 있는 씬 추가 추출은 동일 코드로 확장 가능 |
| R-6 | 로봇 도달 범위와 지지면 높이 불일치 (침실 가구 등) | 지지면 후보 필터에 높이 0.4–1.0m 조건 |

## 5. 산출물 요약

```
scene2test/
├── src/hm3d/
│   ├── dataset.py      tar 인덱싱/추출, 씬 목록
│   ├── loader.py       GLB→OBJ 캐시, PyBullet static 로드, Z-up/바닥 보정
│   └── semantics.py    semantic.txt/glb 파싱 → 인스턴스 bbox → SceneGraph
├── tools/load_hm3d_scene.py   씬 로드 + 스냅샷 CLI
└── data/
    ├── hm3d_raw/       압축 해제된 씬 (minival semantic 4개, ~수백MB)
    └── hm3d_cache/     OBJ 변환 캐시
```
