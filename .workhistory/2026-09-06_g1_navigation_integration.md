# G1 생성 환경 연결 · 내비게이션 · 5단계 실제 GPU 검증

날짜: 2026-09-06 UTC. 사용자 요청: 생성 환경 서버 연결, 기본 내비게이션, 단계별 실제 주행 검증을 바로 수행.

## 구현

- `simulation_server/worlds.py`: 신뢰된 로컬 world bundle ingest, hash/size 검증, SceneGraph/NavigationMap 재계산 비교, immutable registry 등록, G1 XML 합성. 원 robot tree/joint/actuator 순서와 nq/nv/nu 유지 검사. 모든 생성 collision geom의 위치/크기 비교. 실제 robot XML/ONNX 요청 revision 검사 및 YAML/mesh digest 기록.
- `navigation.py`: GT pose/map 기반 waypoint 추종. BFS 기준 경로의 시야선 단순화, 회전 제어와 근거리 정적 clearance guard. 최종 navigator `gt-waypoint-v2`.
- `navigation_worker.py`: 전용 `navigation@1.0` 실행, spawn/goal 고정, CUDA ONNX 보행 재사용, 목표/접촉/넘어짐/정체/timeout/수치불안정 구분, 실제 경로 PNG와 MP4/GIF 포함 evidence.
- API/worker/jobs/bootstrap: 별도 navigation task 등록·검증·dispatch, 신규 artifact 다운로드. 기존 stand/locomotion 실행 경로 유지.
- `procedural_world/navigation_stages.py`: straight/corner/obstacle 고정 회귀 fixture 및 seed=7 rooms/maze.
- `tools/run_navigation_validation.py`: 로컬 등록 + HTTP submit/poll, 순차 실행, 모든 시도 기록.
- `tools/report_navigation_validation.py`: 저장 결과 보고 및 HTTP artifact SHA-256/size 검증.

## 환경 및 범위

별도 `127.0.0.1:8001` 검증 서버를 실행했다. data root는 `/workspace/g1_failure/runtime/navigation_server`, max episode 600s, worker grace 180s. 기존 8000 서비스는 재시작하지 않았고 두 endpoint health를 확인했다. 8001은 localhost 전용이며 외부 공개로 변경하지 않았다.

GROOT root `/workspace/g1_failure/src/GR00T-WholeBodyControl`, MuJoCo 3.12.0, 모든 실제 navigation 결과에 `CUDAExecutionProvider` 기록. 새 정책을 학습하거나 GPT/LLM API를 호출하지 않았다.

Stage footprint radius 0.4m + margin 0.1m, cell 1.8m. 이는 명시적 기준선 설정이며 이전 1.2m 기본 미로 또는 모든 G1 자세의 통과 가능성까지 검증한 것이 아니다. 직선/모퉁이/장애물은 고정 fixture, rooms/maze는 seed 하나씩이다. 전체 random-world 성공률을 주장하지 않는다.

## 초기 실패와 수정

v1의 straight/corner/rooms/maze는 성공했지만 obstacle은 107.20s에서 MAX_DURATION, 목표까지 4.899m를 남겼다. 충돌/넘어짐은 없었다. 로그상 (7.30,9.18) 부근에서 실제 box footprint에는 여유가 있는데 padded raster cell에 들어가 전진을 차단했다. 먼 경유점만 바라보는 제어는 작은 횡방향 편차를 충분히 빠르게 복구하지 못했다.

v2는 0.65m lookahead로 근거리 경로를 추종하고, local guard에는 실제 box 거리와 footprint/margin을 사용했다. 샘플 간 여유 0.01m를 추가했다. 해당 안전 위치의 false block과 경로 쪽 복귀 yaw를 회귀 테스트로 추가했다. 실패 영상을 삭제하거나 성공 결과로 덮어쓰지 않았다.

## 실제 검증 결과

| 단계 | v1 | v2 시간(s) | v2 목표 오차(m) | v2 충돌/넘어짐 |
|---|---|---:|---:|---|
| straight | GOAL_REACHED | 44.08 | 0.196 | 없음/없음 |
| corner | GOAL_REACHED | 88.58 | 0.199 | 없음/없음 |
| obstacle | MAX_DURATION | 50.80 | 0.195 | 없음/없음 |
| rooms | GOAL_REACHED | 81.70 | 0.200 | 없음/없음 |
| maze | GOAL_REACHED | 163.90 | 0.195 | 없음/없음 |

v2는 모두 GOAL_REACHED: goal tolerance 기본 0.25m 안에서 1초 유지하고 접촉/넘어짐이 없어야 성공이다. CPU GT navigation + CUDA gait 조합이며 sensor/LLM navigation이 아니다.

최종 job IDs:
- straight: `job_99fc2eeb8c2a48eda95e7b3c796889bd`
- corner: `job_39d854533ce74a4293f23447cd86bf1f`
- obstacle: `job_d7f28fd3db914140a0abb1f6c7a4cd58`
- rooms: `job_e4c13b8134d842319e8448457a2050ad`
- maze: `job_eea34c73a03d48839a6329d787519fa2`

각 job 폴더: `/workspace/g1_failure/runtime/navigation_server/outputs/jobs/<job_id>/`.
MP4, GIF, thumbnail, actual/reference trajectory PNG, 20Hz state/action JSONL, obstacle contacts, spec/graph/nav/path, composed XML, reproduction이 있다. 모퉁이 및 장애물 우회 MP4에서 프레임을 추출해 실제 G1과 주변 형상을 시각 확인했다.

실험 입력/응답:
- v1 straight: `/workspace/g1_failure/runtime/navigation_validation/20260906T184615_625800Z`
- v1 나머지: `/workspace/g1_failure/runtime/navigation_validation/20260906T184722_201352Z`
- v2 전체: `/workspace/g1_failure/runtime/navigation_validation/20260906T185113_990264Z`

전체 10회 결과 보고서: `/workspace/g1_failure/runtime/reports/navigation_validation_20260906.md` 및 `.json`.

## 자동 검증

- navigation 신규 테스트 처음 8 passed, guard 수정 포함 10 passed.
- 최종 `PYTHONPATH=src .venv/bin/python -m pytest tests/client tests/server tests/test_procedural_world.py -q`: **86 passed, 1 warning, 63.32s**. 기존 Starlette/httpx deprecation 경고.
- Ruff 및 git diff --check 통과.
- HTTP로 10회 실행의 **130개 artifact**를 다시 받아 sha/size 검증 통과. 초기 report 도구가 계약의 `sha256:` prefix를 정규화하지 않아 mismatch로 보고했으나, 로컬/원격 파일 bytes/hash는 일치했다. prefix 정규화 후 전체 재검증했다. 데이터 손상은 아니었다.

## 남은 제한

- GT map/pose, static obstacle navigation 기준선이다. 동적 장애물, perception/SLAM, 전신 swept-volume 검증, 일반적인 복구/재계획은 미완성이다.
- GT SceneGraph/실제 geometry 일치와 고정된 5개 장면 주행을 검증했다. AFS adaptive search와 LAM 연결은 다음 연구 과제다.
- 여러 클라이언트의 전역 GPU admission/queue를 이번에 구현한 것은 아니다. 검증기는 순차 실행한다.
- root assets는 hash로 참조하며 job마다 mesh/정책 전체 복제는 하지 않는다. 실행 중 코드/asset를 변경하지 않고 완료 후 새 버전으로 실험하는 것이 필요하다.
- 보고 도구는 서버 로컬 경로의 링크를 생성한다. 외부 사용자는 인증된 artifact endpoint 또는 별도 공유 경로를 이용해야 한다.

재실행·서버 시작·계약 상세: [G1_NAVIGATION.md](../scene2test/docs/G1_NAVIGATION.md).

추가 지표 범위 확인: 기존 slip 측정 함수는 plane contact만 측정한다. 합성 장면의 box 지면에서는 foot_contact_sample_count=0이며 slip 0은 미측정 placeholder다. 이번 목표/충돌/넘어짐 판정에는 사용하지 않았으며 slip 연구에는 측정기 확장이 필요하다.
