# Blueprint 대비 구현 갭 분석 및 작업 백로그

- 작성일: 2026-06-29
- 기준 문서: `.blueprint/00_blueprint.md` (기본 파이프라인), `.blueprint/01_blueprint.md` (LAM-Guided 확장)
- 목적: 미구현/축소 구현 항목을 문서화하여 추후 작업의 기준으로 삼는다.

---

## 1. 전체 요약

| 영역 | 완성도 | 비고 |
|------|--------|------|
| Blueprint 00 — 기본 파이프라인 (P1~P9) | 높음 | Scene Graph 스키마, Mutation, Oracle, Active Search, 비교실험, 대시보드 완성 |
| Blueprint 00 — 3D Vision (Track B) | **낮음** | §4 참조. 인식(detection) 없음, GT 복사 수준, 파이프라인 미연결 |
| Blueprint 01 — LAM-Guided 루프 | 중간~높음 | 4-family 루프/경계탐색/리포트 동작. 단 기존 Active Search와 미병합 |
| Blueprint 01 — VLA 통합 | 중간 | LAM→VLA 순차 실행 구현. OpenVLA 실물 미검증, 렌더링 분포 격차 미해결 |
| 확장 효과의 정량 입증 (§19 비교실험) | **없음** | LAM-Guided Gain 측정 실험 부재 |

---

## 2. Blueprint 00 갭

### 2.1 Track B: 실제 인식 기반 Scene Graph (§12.2–12.3) — 미구현

- 현재: `src/vision/rgbd_to_graph.py`는 존재하나 실제 인식이 없다 (§4 상세).
- 요구: RGB-D → detection/segmentation → 3D 위치/크기 추정 → SceneGraph.
- 작업 항목:
  - [ ] 객체 분리: PyBullet segmentation buffer(시뮬레이션) 또는 SAM/YOLO(실사) 기반 mask 생성
  - [ ] `extract_object_pointclouds`의 픽셀→포인트 인덱스 매핑 버그 수정 (§4.2)
  - [ ] role 자동 추론 (현재 `role_map` 수동 입력 필수)
  - [ ] 색/형상 등 semantic 속성을 픽셀에서 추출 (현재 role에서 역산)
  - [ ] `rgbd_to_scene_graph`를 실제 파이프라인(app.py / lam_guided_loop)에 연결 (현재 호출처 없음)

### 2.2 기타

- WARN 판정, robustness score, surrogate+acquisition, P9 비교실험: 구현 완료. 추가 갭 없음.

---

## 3. Blueprint 01 갭

### 3.1 구조적 갭 (블루프린트 의도와 다른 구현)

**G-1. Active Failure Search 병합 미구현 (§5.2, Task 7)**
- 블루프린트: guided candidates를 기존 active search candidate pool에 병합, `acquisition.py`에 `behavior_vulnerability_match` 항 추가.
- 현재: `lam_guided_loop.py`가 완전 독립 루프. `active_failure_search.py`에 guided 관련 코드 없음.
- 작업 항목:
  - [ ] `FailureCaseCandidate` → 기존 mutation candidate 포맷 어댑터
  - [ ] `acquisition.py`에 behavior_vulnerability_match 가중 항 추가
  - [ ] merge된 pool에서 top-K 선택 시 source(`lam_guided`/`mutation`) 필드 유지

**G-2. Guided acquisition에 surrogate 미사용 (§10.2)**
- 블루프린트: `failure_probability`(surrogate 예측) + `model_uncertainty` 포함.
- 현재: surrogate-free (`family_prior + novelty + coverage − redundancy`).
- 작업 항목:
  - [ ] 기존 P6 surrogate를 guided candidate feature에 적용해 failure_probability 추정
  - [ ] ensemble variance 기반 uncertainty 항 추가

### 3.2 미구현 모듈

**G-3. Family 5: destination_confusion / destination_occupied (§8.3)**
- [ ] tray 유사 destination distractor 삽입 generator
- [ ] tray 내부 점유물 삽입 generator
- [ ] PolicyOracle에 `wrong_destination` 판정 추가

**G-4. Family 6: grasp_difficult_object (§8.3)**
- [ ] 얇은/불규칙/낮은 객체 asset 추가 (asset bank)
- [ ] graspability_score 기반 boundary parameter

**G-5. ActionAdapter (§7.2) — subgoal 실행 계층 없음**
- 현재: ActionPlan.subgoals는 생성되지만 실행에 미사용. rollout이 선택 객체 위치로 IK 1회 실행. **place/release 단계가 검증되지 않음.**
- 작업 항목:
  - [ ] subgoal(reach/grasp/place/release) → PyBullet primitive 순차 실행기
  - [ ] place_success 판정 (destination 도달 + release)

**G-6. §19 비교실험 (A/B/C) — 확장 효과 입증 실험 부재**
- A: 기존 Active Search만 / B: generated object 랜덤 삽입 / C: LAM-Guided.
- 측정: Failure Discovery Rate@K, LAM-Guided Gain, Behavior-Conditioned Gain, Generated Object Utility.
- 작업 항목:
  - [ ] 3개 방법 동일 예산 실행 스크립트 (`tools/compare_lam_guided.py`)
  - [ ] Generated Object Utility 리포트 섹션 추가 (reporter.py)

### 3.3 축소 구현 (동작하나 블루프린트보다 얕음)

| ID | 항목 | 블루프린트 | 현재 | 작업 항목 |
|----|------|-----------|------|----------|
| G-7 | RolloutTrace (§6.2) | picked_object_id, place_success, collision, recovery_attempted, subgoal_trace, final_result 포함 | 해당 필드 없음, step logger 없이 post-hoc 생성 | G-5와 함께 step-level RolloutLogger 도입 |
| G-8 | PolicyOracle (§7.4) | wrong_subgoal_sequence, wrong_destination 판정 | 미구현 (recovery는 행동 부재로 자동 부여) | subgoal 실행 도입 후 시퀀스 검증 추가 |
| G-9 | BehaviorFeatures (§6.3) | 18개 feature | 8개 | grounding_confidence, trajectory_smoothness, max_distractor_similarity 등 추가 |
| G-10 | VulnerabilityProfile (§6.4) | 9축 | 7축 (semantic_confusion, destination_confusion 없음) | Family 5 구현과 함께 축 추가 |
| G-11 | BoundaryRefiner (Task 9) | semantic_distractor + **occluder(occlusion_ratio)** | semantic_distractor + path_blocker | occlusion_ratio 경계 탐색 추가 |

### 3.4 VLA 통합 잔여 갭

| ID | 항목 | 상태 | 작업 항목 |
|----|------|------|----------|
| G-12 | OpenVLA-7B 실물 검증 | wrapper/MPS(fp32) 설정 완료, 실제 모델 미실행 | 15GB 다운로드 → `--vla openvla`로 E2E 실행, step latency 측정 |
| G-13 | 렌더링 분포 격차 | TinyRenderer 합성 이미지 ≠ BridgeData 실사 분포 | 텍스처/조명/카메라 개선 또는 sim 데이터 LoRA fine-tuning |
| G-14 | lam_vla 모드의 BoundaryRefiner | 여전히 LAM+IK로만 경계 탐색 | refiner에 vla_policy 주입 옵션 (비용 주의: 30 samples/eval) |
| G-15 | Embodiment gap 보정 | frame_transform/pos_scale 기본값(항등) | Franka↔WidowX 좌표계 캘리브레이션 |

---

## 4. Scene Graph 생성 실태 (심층 검증)

> 핵심 질문: "3D Scene이 주어졌을 때 Scene Graph 생성이 정말 동작하는가?"
> **답: 인식 기반 생성은 동작하지 않는다. 두 경로 모두 '인식'이 아니라 '저작(authoring)'이다.**

### 4.1 Track A (procedural) — 저작이지 인식이 아님

- `scene_generator.py`가 객체 위치/크기/role을 **직접 작성**해 JSON으로 저장.
- Scene Graph는 세계의 관측 결과가 아니라 세계의 정의 그 자체 (oracle-perfect).
- 이 자체는 설계 의도(§12.1 "1단계: 시뮬레이션 Ground Truth 기반")에 부합하나, 여기서 멈춰 있음.

### 4.2 Track B (RGB-D) — 코드 수준 증거

`src/vision/rgbd_to_graph.py` 검증 결과:

1. **객체 인식 없음**: `rgbd_to_scene_graph(...)`는 `role_map`(객체 ID→역할)을 **필수 입력**으로 받는다. 어떤 객체가 있는지, 무엇이 target인지 호출자가 이미 알아야 한다. detection/segmentation 모델은 코드·의존성 어디에도 없다.
2. **테스트는 GT 모드만**: `tests/test_p10_rgbd.py`는 `body_map_gt`(PyBullet GT 위치/크기)만 사용. 이 모드는 GT를 SceneGraph 스키마로 **복사**하는 것으로, 포인트클라우드는 계산되지만 객체 추출에 사실상 미사용.
3. **Mode A(mask 기반)는 버그**: `extract_object_pointclouds()`가 전체 이미지 픽셀 인덱스로 valid-depth-only 포인트 배열을 색인한다 (코드 주석 스스로 "간단한 근사"라고 인정). 결과 bbox는 실제 객체 형상과 무관한 임의 포인트 집합이다. **mask를 제공해도 올바른 bbox가 나오지 않는다.**
4. **파이프라인 미연결**: `rgbd_to_scene_graph`의 호출처는 테스트 파일뿐. app.py, lam_guided_loop, active search 어디서도 사용하지 않는다.
5. **Semantic 속성은 role에서 역산**: `asset_bank.annotate_scene_semantics()`가 색상을 `_ROLE_COLOR_NAME[obj.role]`로 주입 — "target이니까 red"라는 **순환 논리**. `visual_similarity_to_target`도 색상명 매칭 + 형상 태그로 계산되며 시각 정보와 무관.

제대로 구현된 부분 (재사용 가능):
- `depth_to_pointcloud` (핀홀 역투영), `estimate_support_plane` (RANSAC), `capture_rgbd_from_pybullet` (비선형 depth 선형화 포함) — 기하 유틸리티는 정상.

### 4.3 Active Failure Search 체인에 미치는 영향

```
[현재 체인]
정의된 SceneGraph(기호) → mutation/insertion(기호) → PyBullet 실행(기하) → oracle 판정(기호+기하)
```

- **Failure scene 생성 자체는 진짜다**: mutation space와 4-family generator는 SceneGraph 위에서 기하학적으로 올바르게 동작하고, constraint filter로 물리 유효성도 걸러진다.
- **그러나 perception 계열 failure는 기호 수준 시뮬레이션이다**: occluder family는 픽셀을 가리는 게 아니라 `occlusion_ratio` 숫자와 `unknown_region`을 세팅하고, 정책이 그 숫자를 읽는다. "가림에 의한 인식 실패"가 아니라 "가림 파라미터에 대한 반응"을 테스트하는 것.
- **결론**: 발견되는 failure boundary(예: distractor 14cm)는 기호 세계의 경계다. 인식 오류·센서 노이즈가 개입하는 실제 경계와 다를 수 있다. 유일한 픽셀 접점은 VLA closed-loop(RGB 입력)인데, 이는 G-13(렌더링 격차)에 막혀 있다.

### 4.4 Scene Graph 관련 작업 항목 (우선순위 포함)

- [x] **V-1 (선행)**: `extract_object_pointclouds` 인덱스 매핑 수정 — `depth_to_pointcloud(return_valid_mask=True)` + 픽셀→포인트 역매핑 테이블. 합성 데이터 검증 포함 (tests/test_p16). **완료 2026-07-28**
- [x] **V-2**: 시뮬레이션 segmentation buffer 활용 — `hm3d/perception.py`의 `capture_rgbd_seg` + `masks_from_segmentation`으로 Mode A 경로 실동작. HM3D 4개 씬에서 spawn 객체 3/3 인식, 위치오차 0.6~4.7cm (tools/run_hm3d_perception.py). **완료 2026-07-28**
  - 주의: PyBullet view matrix는 OpenGL 관례라 핀홀 역투영(CV 관례)과 조합 시 GL→CV 플립 diag(1,-1,-1) 필요. 기존 `capture_rgbd_from_pybullet`의 extrinsic에는 이 플립이 없음 (test_p10은 Mode B GT라 통과) — 신규 코드는 `hm3d/perception.py`의 `capture_rgbd_seg` 사용 권장.
  - HM3D 가구는 mesh chunk가 semantic 인스턴스와 1:1이 아니라 seg buffer로 분리 불가 → 지지면 위 클러터는 DBSCAN 클러스터링(class-agnostic)으로 인식하고 semantic GT와 비교 (`compare_with_gt`).
- [ ] **V-3**: role 추론 규칙 — instruction 키워드 ↔ 추출된 색/형상 매칭으로 target 지정 (현재는 role_map 수동)
- [ ] **V-4**: 색상 추출 — mask 영역 RGB 히스토그램에서 색상명 추정, `annotate_scene_semantics`의 role 역산 대체
- [ ] **V-5**: 실사 확장 — SAM/YOLO 기반 segmentation (Blueprint 00 §12.3)
- [ ] **V-6**: Track B SceneGraph를 lam_guided_loop 입력으로 연결하는 E2E 테스트

---

## 5. 우선순위 로드맵

### P0 — 프로젝트 주장의 신뢰성에 직결
1. **G-6 비교실험**: "LAM-Guided가 기존 대비 낫다"는 핵심 주장의 입증 실험. 구현 비용 낮음(기존 모듈 조합).
2. **V-1~V-2 Scene Graph 인식 경로 최소 구동**: "3D Vision 기반"이라는 과제명 대비 현재 vision이 장식임. seg buffer 기반이면 detection 모델 없이도 "픽셀→그래프" 경로가 진짜가 됨.
3. **G-12 OpenVLA 실물 검증**: VLA 통합의 완결.

### P1 — 커버리지 확대
4. G-3/G-4 Family 5·6 추가 (generator pluggable, 비용 낮음)
5. G-5/G-7/G-8 subgoal 실행 + place 검증 (pick만이 아닌 pick-and-place 전체 검증)
6. G-11 occlusion_ratio boundary
7. G-13 렌더링 개선 (VLA 실효성의 전제)

### P2 — 구조 정합성
8. G-1/G-2 Active Search 병합 + surrogate 재사용
9. G-9/G-10 feature/축 확장
10. V-3~V-5 인식 고도화, G-14/G-15 VLA 세부
