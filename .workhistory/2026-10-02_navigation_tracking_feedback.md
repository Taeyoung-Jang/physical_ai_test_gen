# 경로점 선회 수정과 실행 수치 피드백

2026-10-02 UTC. 사용자가 이전 실험 분석 후 후속 작업 진행을 요청했다.
범위는 로봇 내부 경로 추종 정체 점검, 수치 명령과 실제 이동의 피드백 개선,
그 측정치를 AFS 근거에 보존하는 것이다. 평가기가 로봇 행동을 선택하지 않으며,
목표·예산·과거 결과를 유지한다. 유료 API/GPU rollout은 이번 작업에서 실행하지 않았다.

## 근거와 재현

원본은 `/workspace/g1_failure/runtime/robot_goal_agent/20261002T033720_696599Z`다.
이전 검토에서 유효한 10-call FAIL, 목표 거리 6.2677m, 체류 0초, 낙상/바닥 외 접촉 없음,
경로가 존재한 세 navigation과 마지막 다섯 0속도 명령을 확인했다.
자세한 원본 검토는 [이전 이력](2026-10-02_goal_dwell_live_result.md)에 보존했다.

이번에 저장된 20Hz 상태를 기존 추종기에 넣어 경로점 진행을 근사 재구성했다.
각 navigation의 최초/남은 경로점 수는 152/145, 35/19, 38/35였고,
마지막 추종점과 base는 모두 가까웠다. 200Hz 내부 인덱스를 저장한 원본이 아니므로
정확한 내부 상태 복원이나 물리적 원인 입증으로 해석하지 않는다.

기존 코드는 8cm 안에 들어온 경로점만 제거하고, 나머지 가장 가까운 앞 점을 향해
전진 속도 `0.2 * max(0, cos(error))`, 횡속도 0, 최대 회전 0.4rad/s로 추종했다.
0.15m와 0.20m 횡오차의 이상적 운동학 조건에서 10초 후에도 가까운 점 부근에 머무는
현상을 재현했다. 이 재현에는 모델/API/물리 엔진이 필요하지 않는다.

## 구현

### 로봇 내부 추종

- `navigation_tools.PathFollower`: 지역 경로 진행과 최대 경로 길이 0.35m lookahead,
  거리 비례 속도, 최대 0.20m/s 평면 속도와 0.15m/s 횡속도, 0.40rad/s 회전.
- 먼 경로 가지로 건너뛰지 않도록 진행점 검색 범위를 지역 경로 구간으로 제한한다.
- 현재 base에서 선택점까지의 연속 선분과 원래 반경 0.40m 발자국을 기하 검사한다.
  바닥 경계, AABB 교차, 끝점 거리, 모서리 투영 거리를 검사한다.
- 축별 독립 clipping 대신 공통 비율로 속도를 줄여 연결 방향을 보존한다.
  뒤쪽 목표는 먼저 회전한다. 막힌 연결은 0 명령과 `blocked_connector`를 보고한다.
- 기존 BFS 경로 탐색, no_path 의미, 목표 도착 처리, 독립 GoalEvaluator는 유지한다.
  옛 `follow_command`는 오프라인 비교용으로 남기되 실제 goal runner는 새 클래스를 쓴다.
- 추론 이후 로봇 위치만 갱신하던 계획 입력을 점검해 기하도 함께 갱신했다.
  추론 중 상자가 이동했을 수 있기 때문이다. 새 `navigation_context_NNN.json`은
  계획 시작 시의 실제 위치·기하를 보존한다. 행동 실행 중의 동적 재계획은 추가하지 않았다.

### 실행 측정과 정책 입력

- 새 `execution_feedback.py`는 일반 도구의 실행 시작/끝, 순변위, 목표 거리 감소,
  시작 로봇 좌표 기준 변위, 순 회전각, 평균 명령, 회전 제한 비율과 연결 차단 수를 측정한다.
- 관측/API 추론 대기와 행동 실행 창을 구분한다. 누적 base 이동 길이는 흔들림을
  포함할 수 있다고 명시하며 순이동이나 유효 전진으로 바꾸지 않는다.
- `move`의 실제 수치, 0속도 여부, 최근 8개 기억 안의 연속 0명령 횟수를 다음 입력에
  눈에 띄게 넣는다. 현재 방향의 전방/왼쪽 단위벡터도 세계 좌표로 제공한다.
- 수치 필드 설명과 정책 지침에 설명 문장이 실행되지 않는다는 점을 명시했다.
  0 명령도 유효하며, 자동 비영속도 변환·재요청·방향 강요는 없다.
- 기존 별도 push 루프에는 새 motion 집계를 붙이지 않았다. 기존 skill 근거를 사용하며
  새 측정 누락은 null/부재로 구분한다. stop·stale rejection도 임의 계측을 만들지 않는다.
- goal/push 프롬프트를 각각 `goal-agent-v5-motion-feedback`,
  `goal-agent-push-v7-motion-feedback`로 버전 갱신했다. 모델 선택은 바꾸지 않았다.

OpenAI Docs 스킬로 [공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를
확인했다. 명확한 수치 필드 설명과 평가 테스트를 추가했고, schema에 맞는 값도 의미상
잘못될 수 있다는 한계를 유지했다. 모델 이관이나 API transport 변경은 하지 않았다.

### 근거 저장과 AFS

- protocol에 `navigation_follower`, `execution_feedback_version` 및 새 소스 해시를 포함한다.
- 상태 로그에 명령 직전 위치/방향, 진행 인덱스, 선택점, 회전 오차, 명령을 저장한다.
  기존 20Hz 상태 샘플이므로 전체 200Hz trace라는 주장은 하지 않는다.
- tool_result의 `motion`과 `navigation_tracking`, 호출별 `goal_context` 피드백을 보존한다.
- P1 분석은 새 측정의 버전·시간·수치·0명령 일관성을 검사하고 AFS action_timeline에
  선택 항목을 전달한다. 이전 측정 누락은 생략하고 기존 목표 결과/유형을 바꾸지 않는다.
- 새로운 인과 판정, failure family, AFS/Random 표본이나 유료 비용을 만들어 넣지 않는다.

## 오프라인 확인

관련 핵심 회귀 64개와 확장 회귀 300개 통과, 2개 건너뜀을 확인한 뒤,
기하 갱신 및 추가 경계 검사까지 포함한 최종 확장 검사에서 **405 passed, 5 skipped,
92.36초**를 확인했다. 건너뛴 검사는 실행 통과로 계산하지 않는다.
동일 조밀 경로 대조로 정리한 추종/피드백 테스트도 별도로 **24 passed, 1.46초**를 확인했다.
둘은 중복 검사이며 429개 독립 테스트로 합산하지 않는다.

최종 확장 명령은 `scene2test`에서 다음과 같다. 모두 모의/CPU 및 임시 아카이브 검사다.

```bash
MUJOCO_GL=egl .venv/bin/python -m pytest tests/test_robot_navigation_feedback.py tests/test_robot_goal_agent.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot_push_dispatch.py tests/test_robot_push_integration.py tests/test_robot_push_skill.py tests/test_robot_push_alignment.py tests/test_robot_request_timing.py tests/test_robot_simulation_budget.py tests/test_robot_vlm.py tests/test_robot_vlm_failures.py tests/test_robot_debug_log.py tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/client/test_behavior_memory.py tests/client/test_behavior_regression.py tests/client/test_research_campaign.py tests/client/test_discovery_measures.py tests/client/test_corridor_campaign.py tests/client/test_afs_search_improvements.py tests/client/test_usage_taxonomy.py tests/client/test_afs_pilot.py -q
```

수정한 Python 12개 파일에 Ruff 정적/포맷 검사와 `git diff --check`를 적용했다.
`run_robot_goal_agent.py --help`도 실행했다. 실제 `--live`는 실행하지 않았다.

정체 재현 테스트는 구·신 추종기에 같은 5cm 간격의 경로를 준다. 새 추종기는 이상적 속도
추종 조건에서 목표 반경 0.12m에 진입한다. 실제 G1 성공으로 해석하지 않는다.
독립적인 조밀 점 샘플링 검사로 새 선분 검사에서 허용한 연결의 발자국 여유도 대조한다.
CPU MuJoCo runner 테스트는 합성 정책/제어기이며 실제 CUDA 추론의 증거가 아니다.

원본 장면의 저장된 세 경로와 실행 시작 근처 상태를 새 추종기에 입력한 이상적 운동학
점검도 수행했다. 최대 10초, 목표 반경 진입 시 종료한 결과는 다음과 같다.

| 원본 관측 ID | 초기 요청 목표 거리 | 점검 종료 요청 목표 거리 | 차단 샘플 |
|---|---:|---:|---:|
| 1 | 6.0392m | 4.7795m | 0 |
| 2 | 1.2242m | 0.1195m | 0 |
| 3 | 1.6240m | 0.1195m | 0 |

이 결과는 이미 저장된 G1 궤적을 바꾼 것이 아니며, 새 실제 궤적의 예측이나 동일 조건
비교도 아니다. 보행 추종 오차·균형·접촉 물리는 포함하지 않는다.

개발 도중 malformed-number 테스트 자료를 엄격 JSON writer로 만들다가 writer에서 먼저
차단되는 실패가 있었다. 유효 JSON 안의 비수치 `"NaN"` 입력으로 수정해 분석기가 이를
거부하는지 확인했다. 존재하지 않는 테스트 파일명을 지정한 수집 오류도 올바른 목록으로
수정했다. 생산 코드의 NaN 허용이나 검사 완화로 해결하지 않았다.

## 변경 경계와 다음 실행

기존 dirty worktree의 체류 옵션/회귀 작업은 보존했다. 커밋·push는 수행하지 않았다.
원본 runtime 디렉터리에는 쓰지 않았고 테스트 산출물만 pytest 임시 디렉터리에 만들었다.
GIF 비활성, 기본 시뮬레이션 상한 없음, 출력 토큰 기본 상한 없음, 호출 예산·timeout·
추론 시간의 물리 포함·재시도 없음은 그대로다. 로봇 코드 변경으로 기존 동결 캠페인이나
suite를 새 코드로 재개할 수 없으며 과거 표본과 같은 조건 bracket을 만들지 않는다.

실행 명령과 로그 해석은 [사용 가이드](../scene2test/docs/ROBOT_NAVIGATION_FEEDBACK.md)에 저장했다.
동일 장면에서 새 단독 실행 1회, 로봇 최대 10호출/AFS 0호출부터 검증하는 것이 다음 단계다.
그 전까지 G1/Luna 성능 개선, 최종 goal hold 실물 효과, AFS Gain/coverage 개선은 미검증이다.

문서 작성 스킬에 따라 실제 관측, 코드 재현, 합성 검증과 미검증 성능을 구분해 기록했다.
