# 2026-09-15 — 접촉 피드백 밀기 및 손 회수

## 요청 / 작업 범위

사용자: 다음 작업 진행. 이전 P2 단위 시험(상자 3.16cm 이동, 기준 미달)에 이어
실제 접촉을 유지하는 목표 제어 및 손 회수 절차를 구현/검증했다.
전체 접근·옆 공간 배치·통로 통과, GPT/VLM 연결, AFS 실행은 이번 범위가 아니다.
GPT/API 호출 0회. 원래 보행/서버/지형/AFS/GR00T 원본은 수정하지 않았다.

시작 시 git status는 clean. 기존 파일 Update File은 bwrap namespace 오류로
여전히 실패했다. 기존 파일을 덮어쓰지 않고 추가 모듈/실행기로 진행했다.
셸 읽기·검증·runtime 실행은 승인된 escalated 경로를 이용했다.

## 추가한 파일

- `scene2test/src/clear_path/contact_control.py`: GT 상자/로봇 위치 기반 제한된
  손 목표 및 settle/reach/push/retract/released_hold 상태 제어.
  직전 step의 접촉별 최대 법선력에 따른 전진 감속, 시간/변위 종료, 접촉 해제 측정.
- `scene2test/src/clear_path/contact_probe.py`: 이전 ArmGaitController 재사용,
  새로운 제어 조건의 독립 rollout/접촉/영상 기록 및 성공 판정.
  기존 probe 실행 루프 기반의 별도 구현이므로 공통 버그 수정 시 동기화가 필요하다.
- `scene2test/tools/run_clear_path_contact.py`: CUDA 강제, 18초 기본,
  초기 y [-0.03,+0.03]m 입력, 기존 동일 fixture/audit/source hashes/manifests.
- `scene2test/tools/report_clear_path_contacts.py`: 명시적으로 주어진 run들의
  원본 manifest SHA256/파일 크기를 모두 검증하고 별도 summary JSON/HTML 생성.
- `scene2test/tests/test_clear_path_contact.py`: 상태 전이/손 목표 범위/힘 감속/
  시간·변위 종료/접촉 재발 시 회수 완료 취소/비정상 관측 거부, 5개 테스트.
- `scene2test/docs/CLEAR_PATH_CONTACT_CONTROL.md`: 사용법과 해석 경계.

## 제어 조건 contact_feedback_retract_v1

원래 2kg 상자와 마찰/형상 유지. 로봇 근접 초기 x=3.2m, y만 조건별 변경.
관절은 실제 CUDA Walk.onnx + 기존 팔 scratch IK/PD로 구동한다.
live qpos 조작은 시작 초기화뿐이며 실행 중 물체 teleport/부착/외력 주입은 없다.

0~2초 정착, 2~5초 reach, 5~13초 push. 상자 면 기반 손 x 목표를
base+[0.24,0.30]m 범위로 제한; 전진 명령 상한 0.22m/s.
접촉별 최대 법선력 40N 초과 시 감속, 80N 이상 시 전진 명령 0,
기존 120N hard stop 유지. 힘 목표를 추종하는 임피던스/힘 제어는 아니다.
상자 x 12cm 이동 또는 t=13초에 retract 진입; 2초 손 회수/몸 후진 후 hold.
마지막에 0.5초 연속 손/상자 접촉이 없어야 released=true.

성공은 최종 상자 x >8cm + 실제 손 접촉 + released + 유효 실행 +
넘어짐/금지 robot-world 접촉 없음 + 정상 시간 종료. 이전 8cm 기준 유지.
12cm는 종료 목표이지 합격 문턱이 아니다. clear_path_success는 항상 null.
자기충돌 분류는 미구현이며 로봇 전체 안전성 보증으로 해석하지 않는다.

## GPU 실제 실행 3건

공통 경로: `/workspace/g1_failure/runtime/clear_path_probes/`

| run | 초기 y(m) | 최종 상자 dx(m) | dy(m) | 최대 접촉별 법선력(N) | 결과 |
|---|---:|---:|---:|---:|---|
| 20260915T154857_958826Z | 0 | 0.0829990 | 0.0171319 | 23.8325 | PASS |
| 20260915T155005_495524Z | +0.02 | 0.0899735 | 0.0076717 | 31.3539 | PASS |
| 20260915T155140_752155Z | -0.02 | 0.0902448 | 0.0113974 | 16.9638 | PASS |

세 실행 모두 CUDAExecutionProvider, 18초, DURATION_REACHED, valid=true,
fallen=false, forbidden_contact=false, released=true. t=13초 시간 제한으로
회수에 진입했으며 12cm 종료 목표에는 도달하지 않았다. 마지막 무접촉 3초.
push 중 손 접촉 누적 시간은 각각 7.225 / 7.150 / 7.060초(최대 8초 구간).
연속 완전 접촉을 보장하지 않으며 양손이 동시에 접촉한 시간도 아니다.
40N 감속 분기는 실제 3건에서는 발동 조건에 도달하지 않았고 단위 테스트로 검증했다.

첫 실행 final_frame.png를 직접 시각 검토: 상부 시점에서 로봇/상자가 보이고
손이 상자와 떨어진 회수 자세다. 실제 MP4/GIF는 각 run/report.html에 연결된다.
이전 실패 run들은 모두 그대로 남아 있다. 새 기록에도 JSON/XML/MP4/GIF/PNG,
state_trajectory.jsonl/contacts.jsonl, audit/protocol/result/manifest가 보존된다.

## 검증 / 한계

명령: `.venv/bin/python -m pytest tests/test_clear_path_contact.py
tests/test_clear_path_probe.py tests/test_clear_path.py tests/server/test_terrain_guards.py -q`
결과: 24 passed, 23.58s. 추가 Python 파일 Ruff 검사 통과.

이번 3조건은 작은 초기 위치 민감도 점검이다. 독립 random seed 반복이나
일반 장애물 조작 성공률이 아니다. 이전 v4의 밀기 구간 4초가 이번에는 최대
8초이며 손 목표/속도도 달라졌다. 따라서 개선을 피드백 단일 요인의 효과로
주장하지 않는다. 기준 8cm 대비 여유도 작고, 전체 clear-path 작업은 아직 미완료다.

다음 단계: 옆 공간 배치를 위한 접근/밀기 방향·목표 자세 설계 및 물리 검증,
그 뒤 실제 상자 pose로 지도 갱신/통과 검증. 일반적인 push_object를 GPT에
제공하기 전에는 지원 방향·접근 조건·실패 반환을 제한한 실행 계약이 필요하다.
이번 근접 전방 밀기 성공만으로 범용 조작 skill을 활성화하지 않는다.
