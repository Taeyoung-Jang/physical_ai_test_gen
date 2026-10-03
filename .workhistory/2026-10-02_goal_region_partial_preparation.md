# 목표 부분 점유 대조 실험 준비

2026-10-02 UTC. 사용자가 빈 목표 장면의 PASS 확인 후 다음 시험 진행을 요청했다.
`goal_region_partial.json` 한 회를 동일 Luna·목표·10회 호출 조건으로 실행할 준비를 했다.
현재 에이전트 프로세스에는 `OPENAI_API_KEY`가 없어 유료 실행은 시작하지 못했다.
확인된 것은 비교 조건과 장면 구성이지 로봇 성공 또는 실패가 아니다.

## 비교 조건 검증

기준 원본은 `/workspace/g1_failure/runtime/robot_goal_agent/20261002T141132_394018Z`다.
기존 `contrast_plan`, `environment_fingerprint`, `verify_condition`을 읽기 전용으로
사용해 archive 해시와 현재 소스·G1 자산·기록된 런타임 버전이 일치함을 확인했다.
부분 점유 preset이 단일 축 probe와 정확히 일치하는 것도 확인했다.
검사용 계획은 메모리에만 만들었으며 suite/DB를 생성하거나 추가 대조 실행을 예약하지 않았다.

- 변경 축: `box_lateral_fraction`, 1.0 → 0.5.
- 상자 중심: `(7,1.4)` → `(7,0.7)` m. X와 크기·질량·마찰은 그대로다.
- 목표: `(7,0)`, 반경 0.25m 안 연속 1초 체류.
- 로봇: gpt-6-luna, push 활성화, goal_dwell_v1, 최대 호출 10회.
- HTTP read 300초, simulation/watchdog 상한 없음. 출력 토큰 기본 상한도 바꾸지 않았다.
- 나머지 장면 설정, 정책과 제어 코드, 자산 및 평가 규칙 변경 없음.
- 부분 점유 scene revision:
  `881871bd12dba1d14b9e93b098f01f698a47462e5edc60c88df4a8238d1af4b2`.

초기 목표 관계는 PARTIAL이며 정적 footprint 지도에서는 경로가 없다.
그러나 이동 가능한 상자가 있으므로 이것을 goal FAIL이나 전체 과제 불가능성으로 쓰지 않는다.
로봇에게 접근 방향·상자 배치 목표·밀기 동작을 외부에서 지정하지 않는다.
GPU는 NVIDIA RTX PRO 4500 Blackwell로 확인됐지만 이번에는 새 모델 추론이나 주행을 실행하지 않았다.

## 실행 대기와 명령

키 존재 여부만 확인했고 값은 출력하지 않았다. 사용자 터미널의 인증을 다른 프로세스나
파일에서 탐색·추출하지 않았다. 아래 명령은 키가 설정된 사용자의 터미널에서 실행한다.
최대 로봇 API 10회인 한 회 실험이며 전체 AFS/Random 캠페인이 아니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --navigation-completion goal_dwell_v1 --scene-config config/scenes/goal_region_partial.json
```

이번 준비 작업의 API 호출 0, robot rollout 0, 새로운 goal 판정 없음이다.
원본 성공 결과·옛 캠페인·중단한 폭 실험을 변경하지 않았다. 실행 코드 수정, commit/push,
자동 재시도 또는 모의 성공으로의 대체도 하지 않았다. 확인 사실과 미실행 범위를 구분해 기록했다.

사용자 실행 후에는 기준 실행과 condition ID를 다시 비교하고, 목표 판정·행동·물체 이동·
접촉·넘어짐·API 사용량·영상·AFS 행동 근거를 검증한다. 실패하면 중간 배치 완화나 다른
축의 가설을 검토하며, 무조건 목표를 더 많이 막는 방향으로만 이어가지 않는다.
