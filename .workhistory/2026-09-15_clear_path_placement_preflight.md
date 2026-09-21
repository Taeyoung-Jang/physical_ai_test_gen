# 2026-09-15 — 옆 공간 배치 접근 검사 및 측정 상태 갱신

## 요청과 판단

사용자는 다음 작업 범위를 확정하고 진행하도록 요청했다. 옆 공간 배치의 접근
가능성을 먼저 검사하고, 가능할 경우 물리 실행/지도 갱신을 하기로 안내했다.
원래 fixture의 기하 검사에서 남쪽 정면 접근이 현재 계획 모델에 맞지 않음을
확인했다. 접근 거부를 무시하거나 벽/로봇 크기를 조용히 바꾸지 않았다.
대신 기존 실제 결과로 지도/SceneGraph 갱신과 보고를 완료했다.

시작 git status clean. 추가 파일만 생성; 기존 코드/fixture/증거 변경 없음.
API/GPT 호출 0, 신규 GPU 정책 실행 0, 신규 물리 적분 step 0.
기존 XML과 저장 qpos에 대한 mj_forward는 파생 기하 계산이며 새 rollout이 아니다.

## 근거

- fixture.py: BOX_SIZE=(0.8,1.1,0.7), BOX_START=(4,0), 남쪽 벽 안쪽 y=-0.8.
- 남쪽 면 y=-0.55 → 틈 0.25m.
- Fixture 기본 footprint 0.35m+clearance 0.05m → 직경 0.80m.
- 전방 palm offset 0.28m를 north push에 적용하면 base=(4,-0.83), 통로 밖.
- 기존 executor는 world +X 전방 근접 밀기만 구현했으며 +Y 회전 제어 미검증.
- 이는 남쪽 정면 접근의 보수적 거부이며 모든 조작 경로의 불가능 증명은 아니다.

## 구현

- placement_preflight.py: 정면 밀기 접근 검사, 회전된 실제 상자 world AABB,
  독립 5cm circular-footprint 지도/BFS, SceneGraph 상태 갱신.
  원래 fixture 벽/상자 기하 mismatch 및 비정상 pose/state_version 거부.
- check_clear_path_placement.py: 원본 manifest/hash/fixture revision/valid_execution
  검사, 실제 초기/최종 상태 복원, 각 graph/map SVG/JSON, HTML, 출처 및 manifest.
- test_clear_path_placement.py: 10개 새 사례(접근 거부, unrotated legacy 지도 일치,
  회전 AABB/공유 버전/입력 불변, 상태 digest 변화, 기하 drift 및 비정상 입력 거부).
- docs/CLEAR_PATH_PLACEMENT_SCOPE.md: 이번 구현과 미구현/후속 선택을 구분.

## 실행 증거

입력은 직전 GPU 실행:
`/workspace/g1_failure/runtime/clear_path_probes/20260915T155140_752155Z`

명령:
`uv run python tools/check_clear_path_placement.py <위 run 경로>`
실제 환경에서는 기존 `.venv/bin/python` 사용.

출력:
`/workspace/g1_failure/runtime/clear_path_placement_checks/20260915T160522_661535Z/report.html`

검사 결과: REJECT_UNDER_CURRENT_APPROACH_MODEL, final path_open=False.
직전 단위 밀기의 +9.02cm 이동/손 회수 성공은 통로 개방 성공이 아니다.
graph/map은 동일 원본 결과/scene XML hashes, scene_revision과 state_digest를 공유한다.
초기/최종 state_version은 0/1. 기존 결과/manifest는 수정하지 않았다.

## 후속 결정

권장하는 범위는 남쪽 접근 공간이 있는 새 fixture revision 추가, 접근 및 북향
제어 검증, 단계적 배치→회수→지도 갱신이다. 원래 fixture는 회귀/어려운 사례로 보존.
다른 선택은 원래 공간에서 코너 밀기/회전/당기기 기술을 개발하는 것으로 범위가 크다.
이번에는 어느 쪽도 임의 구현하지 않았다. 환경 변경 방향을 사용자에게 요청한다.
전체 통로 통과와 GPT 등록은 계속 미완료이며, 기존 계획대로 후속 단계로 남긴다.

## 검증 결과

`pytest tests/test_clear_path_placement.py tests/test_clear_path_contact.py
 tests/test_clear_path_probe.py tests/test_clear_path.py tests/server/test_terrain_guards.py -q`:
34 passed, 23.49s. 추가 Python 파일 Ruff 검사에서 import 정렬을 수정한 뒤 통과.
전체 저장소/실제 북향 조작 테스트 통과를 의미하지 않는다.
