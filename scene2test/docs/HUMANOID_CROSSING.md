# 직선으로 횡단하는 사람 대리물

2026-10-23 후속 연결: [동적 사람 측정과 공통 탐색](HUMANOID_DYNAMIC_SEARCH.md)에
별도 안전 검출기·21축·새 paired 개발 설정을 정리했다. 아래 초기 구현 설명의
"탐색 미등록/검출기 후속 작업" 상태는 이 후속 연결 이전 기록이다.

## 관람용으로 물체 구분하기

원래 청록색 직육면체는 사람 충돌 proxy다. `tools/render_labeled_humanoid.py`는
manifest 검증 후 저장된 robot state와 사람 궤적만으로 새 관람용 MP4를 만든다.
사람은 머리·몸통·팔·다리로 표시하고 HUMAN, OBSTACLE 1/2, PUSHABLE BOX,
GOAL, G1 ROBOT 이름표를 붙인다. 사람 청록색, 장애물 보라/분홍색, 상자 주황색이다.
벽은 반투명하게 표시한다. 물리 step·정책·API를 실행하지 않는다.
관람용 실루엣과 이름표는 원래 로봇 카메라 입력에 추가되지 않는다.

```bash
uv run --no-sync python tools/render_labeled_humanoid.py \
  --run /workspace/g1_failure/runtime/humanoid_crossing_openrouter/20261023T005929_285349Z \
  --output-dir development/humanoid_labeled_20261023_v1
```

새 폴더에 `labeled.mp4`, 미리보기 PNG, 원본 artifact 해시를 담은 provenance를
저장한다. 20Hz robot state에서 가장 가까운 표본을 선택해 12fps로 표시하므로
원본 프레임과 완전히 같은 영상은 아니다. 충돌·거리·PASS 판정은 원본 로그를
따르며 관람용 사람 모양으로 다시 판정하지 않는다.

새 opt-in 장면 `clear-path-crossing-human-v6`는 사람 대리물 한 명이 로봇에
가까워지면 통로 반대편으로 한 번 이동하게 한다. 기존 v5 정적 사람과 20축
AFS/Random 영역은 유지한다. v6는 아직 AFS/Random 비교 프로토콜에 등록하지
않은 개발 장면이다. 기존 frozen 캠페인을 새 소스로 재개하지 않는다.

## 동작

- 사람 X 위치는 기존 3.65–4.35m 안에서 고정한다.
- 좌우 시작점은 `human_lateral_fraction` −1 또는 +1이다. 통로 벽에서 사람
  표면까지 5cm를 남긴다. 종료점은 반대편의 대칭 위치다.
- `human_speed_mps`: 0.1–1.5m/s, 기본 0.5m/s.
- `human_trigger_distance_m`: 로봇 base와 사람 중심의 수평 거리, 0.5–5m,
  기본 2m. 임계거리 이하이면 한 번 출발하며 이후 멀어져도 계속 이동한다.
- 초기 2초 안정화 동안은 출발하지 않는다. 이후 추론 대기·이동·관찰 중에도
  물리 step마다 시뮬레이션 시계로 이동하며, 도착하면 정지한다.

사람은 기존 0.4×0.4×1.6m 직육면체 충돌 proxy다. MuJoCo mocap body로
지정 궤적을 따르므로 보행 자세·자율 회피·충돌에 밀리는 사람의 반응은 없다.
이 로봇의 실제 회피 능력이나 사람 안전성을 검증한 상태는 아니다.

## 관측과 기록

RGB와 geometry에는 현재 실제 사람 위치가 반영된다. 정책의
`behavior_feedback.human_motion`에는 현재 위치·지정 속도·이동 상태·출발
시각·거리·접촉 기록이 들어간다. 미래 경로나 회피 정답을 주지 않는다.
v6의 navigate_to follower는 매 step 현재 geometry로 connector를 검사한다.
기존 재계획·회복 상한을 유지하며, 미래 궤적 예측이나 회피 성공은 보장하지 않는다.

- `human_proxies.json`: 장면·속도·트리거 계약.
- `human_motion.jsonl`: 매 물리 step의 실제 위치·시각·거리·로봇 접촉.
- `human_motion_summary.json`: 출발 시각, 최소 표본 거리, 접촉 step 수.
- `contacts.jsonl`: 기존 링크 접촉·힘 기록.

이 파일들은 실행 manifest에 해시로 포함된다. 안전거리 진단은 기존 base 반경
0.4m와 보호 반경 0.6m의 합으로 계산하며 실제 신체 표면 거리나 안전 표준이
아니다. 기존 정적 사람 detector는 v6를 명시적으로 UNSUPPORTED로 처리한다.
PASS/FAIL·종료 조건·기존 failure-family credit은 바꾸지 않는다. 동적 궤적에
맞는 archive-bound detector는 별도 후속 작업이다.

## 무료 확인

```bash
uv run --no-sync python tools/preview_human_crossing.py \
  --scene-config config/humanoid_crossing_development.json \
  --output-dir development/humanoid_crossing_20261023_v1
```

출력 폴더는 새 경로여야 한다. XML을 CPU로 컴파일하고, 가상의 base가 2초 후
직선으로 0.2m/s 이동하는 예시 궤적을 생성한다. GPU·G1 정책·API 실행은 없다.
이번 출력은 701표본, 출발 10.7초, 35초 시점 횡단 완료다. 실제 G1 rollout이나
물리적 회피 결과로 해석하지 않는다.

## 향후 실제 실행

기존 `tools/run_robot_goal_agent.py --scene-config
config/humanoid_crossing_development.json`이 v6를 읽는다. 실제 정책은 명시적
`--live`가 필요하며 CUDA와 모델 자원이 필요하다. 이 구현 작업에서는 실행하지
않았다. 예시 장면은 폭 3.6m·마찰 0.8·상자 가장자리 조건으로 사람 이동만
점검하기 위한 것으로, 전체 환경 범위를 다시 축소한 비교 설계가 아니다.

새 개발 실행 결과를 확인한 뒤에만 사람 속도·출발 거리의 공통 탐색 영역과
독립 평가 seed·예산을 별도로 고정한다. timeout 등 인프라 오류는 여전히
INCONCLUSIVE이며, 기존 요청 재전송·제외 대체·예산 초기화는 하지 않는다.
