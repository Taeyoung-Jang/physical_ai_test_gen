# Clear-path P0/P1 첫 구현 및 시각 보고서

날짜: 2026-09-15 UTC. 사용자 요청: GPT-6 장애물 제거 시나리오 작업 착수.
이번 범위: 앞서 제안한 0–1단계의 환경/계약/호환성 기반. 물리적 로봇 밀기와
GPT 로봇 제어를 구현 완료한 것으로 표시하지 않는다.

## 변경 파일과 목적

- `src/clear_path/contracts.py`: fixture 설정, typed 행동 계약, 오래된 state/없는
  객체/실행기 미지원 거부, 측정된 boolean facts를 사용하는 elementary evaluator.
- `src/clear_path/fixture.py`: 고정 통로/옆 공간/동적 상자, 공유 기하의 MuJoCo XML,
  기존 SceneGraph 직렬화, 초기/가정 배치의 2D 지도와 경로 검사.
- `src/clear_path/audit.py`: 이름 기반 관절/actuator/qpos/dof/limit 매핑 비교,
  기존 보행 관측 일치 검사, 손바닥 충돌 형상/팔 Jacobian, 자원 해시.
- `src/clear_path/report.py`: 지도 그림, MuJoCo 3D/로봇 시점, 정지 장면의 카메라
  orbit MP4/GIF, 사람이 읽는 HTML 보고서. 영상은 NOT rollout로 명시.
- `tools/setup_clear_path.py`: 독립 생성/점검 명령, 초기 상태/camera 정보,
  protocol/status/artifact manifest, 덮어쓰지 않는 런타임 폴더.
- `tests/test_clear_path.py`, `docs/CLEAR_PATH_PROTOTYPE.md`.

기존 G1 controller, terrain/nav worker, scene registration, AFS v1/v2 및 Panda,
g1-local-nav 파일은 수정하지 않았다. 시작 시 존재한 미추적 계획/이력 파일 보존.
새 파일 작성/수정은 apply_patch Add File과 정상 Ruff formatting으로 수행.
기존 파일 read sandbox 오류를 우회하는 전체 교체는 하지 않았다.

## 환경과 제어 점검 결과

통로 길이 8m/폭 1.6m, 옆 공간 x=3.3..4.7/y=.8..2.5m.
G1 시작 (1,0), 목표 (7,0). 상자는 (4,0), 크기 .8×1.1×.7m, 질량2kg,
sliding friction=.5, floor friction=.8. 옮길 목표 중심은 (4,1.65).
수치는 최초 fixture 가정이며 실제 밀기 가능성/강건성의 검증값이 아니다.

- 원 모델 actuator29개와 순서/관절 주소/limit 보존.
- 원 (nq,nv)=(36,35) → 상자 추가 (43,41). 상자 freejoint는 로봇 뒤에 추가.
- 기존 초기 보행 observation86개가 동일함. GPU 정책을 실행한 검사는 아님.
- ONNX는 CPU 세션의 메타데이터만 조회: input [batch_size,516], output [batch_size,15].
  추론/로봇 제어는 실행하지 않음.
- 팔당 관절7개, 손바닥 충돌 geom 각1개(최종 모델 ID65/95), 초기 위치 Jacobian rank3.
- 활성 손가락 관절 없음. palm site의 좌우 offset은 실제 source mesh offset에서 가져옴.
- 기존 controller는 나머지 상체14개 관절을 0 자세 PD 유지. 독립 상체 target/IK
  adapter를 P2 후보로 선정하지만 접촉·힘·균형·도달 가능성은 아직 검증하지 않음.
- 초기 지도 경로 없음; 가정한 옆 배치 지도에는 경로 있음. 실제 상태를 옮긴 결과가 아님.

## 검증

`python -m pytest tests/test_clear_path.py tests/server/test_terrain_guards.py
tests/test_terrain_courses.py tests/test_procedural_world.py -q`

최종 코드에서 56 passed in 31.23s. G1 자산 검사는 이번 환경에서 skip되지 않음.
Ruff check 통과. object-only MuJoCo 테스트에서 상자 질량/마찰, 바닥 지지,
초기 속도에 따른 이동 확인. 인위적 초기 속도 테스트는 로봇 밀기 증거가 아님.
행동 계약은 실행기 기본 목록이 비어 있어 움직임을 실행할 수 없음.

첫 렌더링 실패: 960×540 요청이 기본 offscreen640×480보다 커 ValueError 발생.
생성 XML에 offwidth/offheight 명시하여 수정. 첫 실패 결과는 보존:
`/workspace/g1_failure/runtime/clear_path/20260915T150515_281082Z`.

첫 렌더링 성공/시각 확인 결과:
`/workspace/g1_failure/runtime/clear_path/20260915T150758_204255Z`.
overview, robot_view, initial map을 실제 이미지로 열어 확인.

최종 source/palm site 정정 후 결과:
`/workspace/g1_failure/runtime/clear_path/20260915T151210_027886Z/report.html`.
status FIXTURE_READY, rendering OK, robot_rollouts0, api_calls0.
17개 산출물 해시 및 최종 source hash 대조 통과. MP4/GIF 각각36프레임,
MP4 12fps/3초, GIF 프레임 간격80ms. 이는 GPU EGL 렌더링을 사용한 정지 장면
미리보기이며 GPU 보행 정책 추론/시간 진행은 없음.

## 남은 작업과 주장 범위

초기 snapshot/지도/그래프만 구현했으며 연속 상태 갱신은 future action runner 작업.
행동 schema/기본 verdict만 있으며 실제 접촉 pair/phase 분류와 시간/힘 제한이 필요.
P0의 정적 호환성은 확보했지만 안정된 상체 제어 경로의 물리 검증 관문은 남아 있음.
P1의 시각 환경은 준비됐고, 다음 P2는 접근/팔 목표/실제 손 접촉/밀기/분리/통과를
실행하고 별도의 실제 rollout 영상으로 증명하는 것이다.
현재 옆 공간으로 실제로 밀 수 있는지조차 아직 검증하지 않았으므로 known-feasible
robot task로 주장하지 않는다. 이미지/GIF만으로 이 관문을 통과했다고 하지 않는다.

MuJoCo 공식 Python 문서의 named state access 및 rendering API를 참고:
https://mujoco.readthedocs.io/en/stable/python.html.
유료 API 요청, 모델 다운로드, 실물 로봇 작업, git commit/push는 하지 않음.
