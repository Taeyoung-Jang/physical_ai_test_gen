# 옆 공간 배치 단계: 범위와 사전 검사

2026-09-15. contact_feedback_retract_v1 근접 전방 밀기 검증의 후속 작업.

## 이번에 확정하고 수행한 범위

1. 원래 fixture에서 옆 공간으로 정면 밀기 위한 접근 위치를 검사.
2. 기존 실제 rollout의 초기/최종 물체 pose로 SceneGraph와 지도를 재생성.
3. 단위 밀기 성공과 통로 개방을 별도 판정하고 보고.

이번 단계는 읽기/파생 산출물 생성이며 로봇을 새로 실행하지 않는다.
접근 검사가 거부되었기 때문에 북쪽 밀기를 강행하지 않았다. 원래 fixture,
기존 실행기, 보행 정책, AFS, 서버, GPT 연결은 변경하지 않는다.

## 접근 검사 결과

상자 초기 중심 y=0, 남쪽 면 y=-0.55m. 남쪽 벽 안쪽 y=-0.80m.
따라서 틈은 0.25m이며, 현재 계획 반경 0.35+여유 0.05=0.40m의
직경 0.80m보다 작다. 0.80m는 로봇 실측 폭이 아니라 보수적 계획 가정이다.

현재 검증된 손 전방 거리 약 0.28m를 북향 정면 밀기에 적용하면 base y=-0.83m,
즉 base 중심 자체가 통로의 남쪽 벽 경계를 벗어난다. 이 계산은 필요한 접근
형상을 점검하는 것이며 북향 로봇 제어가 이미 구현됐다는 뜻은 아니다.
현재 contact_control은 world +X에 고정되어 있어 heading/local-frame 확장도 필요하다.

판정은 `REJECT_UNDER_CURRENT_APPROACH_MODEL`. 모든 조작 전략의 불가능 판정은
아니다. 옆면/코너 접촉, 회전, 당기기 등은 검증하지 않았다.

## 측정 상태 갱신

```bash
cd scene2test
uv run python tools/check_clear_path_placement.py /absolute/path/to/contact/run
```

원본 manifest hash 및 fixture revision을 확인한 뒤 저장된 scene.xml과
result의 initial_qpos/final_qpos를 사용한다. `mj_forward`로 기하를 계산할 뿐
물리 적분/정책 추론을 수행하지 않는다. 모든 물체 순간이동 실행 주장은 금지한다.

회전 행렬의 절댓값과 로컬 half-size로 world AABB를 계산하여 yaw/roll/pitch를
포함한다. 따라서 중심 xy만 옮기고 원래 크기를 유지하던 지도와 구분된다.
SceneGraph의 size는 world AABB이며 실제 로컬 크기와 회전 행렬은 extra에 저장한다.
그래프/지도는 객체 ID, frame, scene_revision, state_version, state_digest 및
출처 hash를 공유한다. 시점 version은 해당 결과 쌍의 0/1이며 전역 서비스 카운터가 아니다.

초기 지도와 최종 지도는 저장된 실제 자세다. 목표 위치의 가상 지도를 최종 결과로
대체하지 않는다. 별도 runtime 폴더에 JSON/SVG/HTML/manifest를 저장하며 원본은 보존한다.
SVG는 지도 시각화이지 로봇 실행 영상이 아니다. 원본 실제 MP4/GIF 링크를 제공한다.
이것은 offline 상태 갱신 도구이며 서버의 실시간 동적 지도 API를 추가한 것은 아니다.

## 다음 물리 시험에 필요한 결정

권장: 기존 장면은 보존하고, 남쪽 접근 공간이 있는 새 revision의 fixture를 추가한다.
필요한 공간을 수치로 설계하고 spawn→접근 경로와 북향 자세, 팔 reach/균형부터
검증한다. 그 뒤 단계적 북향 밀기→옆 공간 배치→손 회수→실측 지도 갱신으로 진행한다.
새 장면에서도 크기/질량/마찰/힘 제한을 조용히 완화해서는 안 된다.

대안: 원래 장면을 고정하고 코너 밀기/물체 회전/당기기 skill을 새로 연구한다.
이는 현재 전방 밀기보다 큰 조작 개발 범위이며 성공을 보장할 수 없다.

현재는 새 장면이나 새 skill을 아직 구현하지 않았다. 장면 수정 방향을 정한 후
후속 물리 실행을 진행한다. 실제 통로 보행과 GPT action 연결은 배치 단계 이후다.
