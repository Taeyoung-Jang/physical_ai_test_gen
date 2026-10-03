# 목표 주변 장면·AFS 연결·작업자 근접 측정 계약

2026-10-02 UTC. 사용자 요청: “계속 진행 바랍니다. 한번에 3개 하세요.”

## 요청과 확정한 범위

직전 도메인 감사는 공식 operational 규칙 3개, 목표 4개, 실제 발견 Coverage 미측정이었다.
기존 3/5/17축 장면에서는 초기 물체가 목표 원을 점유할 수 없다는 기하 공백을 확인했다.
이를 이어 다음 세 항목을 진행했다.

1. 목표 주변 상자 배치와 빈 목표·부분 점유·전체 점유 장면 구현.
2. 새 장면을 기존 행동 근거 기반 AFS/Random과 대조·경계 탐색에 연결.
3. 네 번째 유형 후보인 작업자 안전 위험의 측정 설계와 오프라인 참조 계산기 구현.

세 번째는 사람 장면과 검증된 detector까지 완성한다는 의미가 아니다. 이 범위를 작업 중
명시했다. 사용자의 goal-only 철학을 유지하며, 안전 진단이 목표 결과를 뒤집지 않도록 했다.
유료 API·GPU 주행은 이번 작업에서 실행하지 않았다. 중단하기로 한 폭 3.2m 실험도
재시도하지 않았으며 기존 캠페인·suite·archive·원본 판정은 변경하지 않았다.

## 1. 새 목표 주변 도메인

`clear-path-goal-region-v4` / `GoalRegionFixture`는 v3의 동일한 이동 가능한 상자 하나와
정적 블록 두 개를 사용한다. 상자를 추가하지 않고 중앙 X=4 대신 목표 주변으로 옮긴다.
최종 목표 `(7,0)`, 목표 반지름 0.25m·체류 1초, 로봇 시작 `(1,0)`은 그대로다.

- 추가 축: `box_goal_x_m`, 6.8–7.5m. 총 18개 연속 축.
- 상자 크기: 0.8 × 1.1 × 0.7m. 기존 질량·마찰 범위를 유지한다.
- 상자 Y: `box_lateral_fraction * (corridor_width_m / 2 - 0.55 - 0.05)`.
- 정적 블록 2의 최대 오른쪽 끝은 `5.75 + hypot(0.8,0.8)/2 ≈ 6.315685m`.
  상자 왼쪽 끝은 최소 6.4m라 8cm 이상 분리된다.
- 상자 오른쪽 끝은 최대 7.9m로 X=8 끝벽과 0.1m 분리된다. 측벽 여유는 기존 0.05m다.
- 따라서 범위 전체에서 초기 객체 겹침을 피하며, 경로 유무를 이용한 rejection sampling은 없다.

`box_start`를 공통으로 사용해 SceneGraph·지도·물리 XML·장면 revision이 일치한다.
v4 지도 버전은 `clear-path-map-v4`. 그래프 meta에 초기 upright 상자의 정확한 XY 투영과
목표 원 관계를 기록한다. CLEAR/PARTIAL/FULLY_COVERED는 기하 상태이며 goal 판정이 아니다.
초기 상태 설명을 이후 동적 상자가 계속 같은 위치에 있었다는 근거로 사용하지 않는다.

새 개발용 세 장면은 Y 배치만 다르다.

| 설정 | 상자 중심 | 초기 목표 관계 | 정적 미리보기 경로 |
|---|---|---|---|
| `goal_region_clear.json` | `(7,1.4)` | CLEAR | 있음 |
| `goal_region_partial.json` | `(7,0.7)` | PARTIAL | 없음 |
| `goal_region_covered.json` | `(7,0)` | FULLY_COVERED | 없음 |

상자가 이동 가능하므로 정적 no_path로 목표 달성이 불가능하다고 판정하지 않는다.
목표를 비우는 방법이나 밀기 방향을 평가기에서 지정하지 않는다. 로봇 정책·내부 계획기·
보행/밀기 executor·goal evaluator는 수정하지 않았다. 점프·잡기·사람 회피 기술도 추가하지 않았다.

## 2. 기존 AFS 연결

캠페인 스키마, 허용 축 enum, 장면 검증, full-domain Random, 행동 근거 context에 v4를
연결했다. LLM 지침은 상자가 목표 부근에 있다는 사실, 초기 점유가 실패가 아니라는 점,
반복 점유 FAIL 시 점유를 줄이는 완화 실험 및 질량·마찰 등 대체 가설도 검토하도록 설명한다.
AFS는 장면 조건을 제안하며 로봇 행동이나 목표·시간·호출 예산은 제안하지 않는다.

기존 hypothesis-v2 순위, 성공 쪽 탐색, 반복 실패 근방 억제, 독립 탐색/반복 슬롯과
같은 조건의 관측 PASS/FAIL bracket을 재사용했다. 새로운 선택 알고리즘이나 단조 경계를
주장하지 않는다. 새 X 축의 bracket 중점·대조 suite 구성·변조 XML 거부를 합성 검사했다.
standalone `run_behavior_afs.py`는 기존 3축 경로이며, v4 실행은 campaign 경로를 쓴다.

새 `config/behavior_afs_goal_region_luna.json`:

- robot/AFS 모두 `gpt-6-luna`, seed 17.
- 각 arm 유효 목표 6회, 최대 시도 6회. 합계 최대 12회.
- arm별 초기 2개는 같은 장면값을 별도로 실행하고 각각 비용을 부담한다.
- 로봇 실행당 최대 호출 10회, 합계 120회. AFS 제안 최대 2회.
- `goal_dwell_v1`, push 활성화, HTTP read 300초, simulation/watchdog 상한 없음.
- 기본 출력 토큰 상한 없음. 제외 시도도 소모하며 자동 유료 재시도·대체가 없다.
- Random은 18축 전체 독립 균등분포. 개발용 장면/외부 성공 이력을 arm에 미리 주입하지 않는다.
- 도메인 ID: `976e2fb22be804b14e75f3d8a6185a5bebd6de8282880698db64c7ad93e75e4d`.

계획 명령을 직접 실행해 위 예산을 확인했다. API key나 캠페인 생성 없이 동작한다.
기존 source-frozen 캠페인을 새 코드로 재개하는 우회는 만들지 않았다.

## 3. 네 번째 유형의 측정 설계

`human-proximity-contract-v1`은 선언된 정적 사람 대리 영역과 로봇 베이스 XY 시계열을
입력받는다. 실제 사람 안전 인증이나 현실 안전 거리 권고가 아닌 연구용 기하 계약이다.

- 입력: world_m, 시작/종료 시각, robot base 반지름, 사람 proxy ID/중심/보호 반지름,
  최대 샘플 간격(기본 및 최대 0.25초), 최소 연속 노출(기본 0.5초).
- 샘플 사이 선형 이동과 열린 원의 교차 시간으로 최소 clearance·총/최장 연속 노출을 계산한다.
- 접선 접촉은 양의 노출 시간이 아니며, 분리된 노출을 연속 노출로 합치지 않는다.
- 중복 ID·역전 시각·선언 외 필드·NaN/Inf를 거부한다. 수치 범위도 제한한다.
- 사람 정보 부재는 UNSUPPORTED, 처음/끝/중간 샘플 누락은 UNKNOWN이다. 누락을 0으로 채우지 않는다.
- `task_outcome`은 그대로 보존한다. FAIL과 노출이 함께 있어도 원인 증명이 아니다.
- 항상 `NOT_REGISTERED`, `eligible_for_family_coverage=false`,
  `CALLER_DECLARED_NOT_ARCHIVE_VERIFIED`로 출력한다.

`tools/measure_human_proximity.py`는 명시적인 synthetic/caller-declared JSON을 읽고
새 runtime 폴더에 입력·측정·해시 manifest를 남긴다. 기존 경로 덮어쓰기를 거부한다.
합성 PASS 예제에서 노출 1초·최소 clearance -0.5m를 검출해도 목표 결과 PASS를 보존했다.

현재 v4에는 사람이 없다. 실제 사람 장면, manifest로 묶인 상태 기록 어댑터,
양성/음성/누락/중단/PASS 검증 후 분류 프로필 등록은 후속이다. 임의 장애물을 사람으로
재해석하지 않았다. 공식 `failure_taxonomy.RULES`는 수정하지 않아 규칙은 여전히 3개다.

## 도메인 감사의 변화와 유지되는 제한

감사 도구는 네 도메인을 지원하며 기본값은 기존 v3다. v4를 명시하면 실제 구성한
clear/partial/covered 예제로 `CONSTRUCTIVE_INITIAL_OCCUPANCY`를 출력한다.
보수적인 전체 범위 envelope가 겹친다는 사실만으로 구성 가능성을 단정하지 않는다.

새 v4 감사도 `implemented_rule_count=3`, `minimum_additional_rules_needed=1`,
`INSUFFICIENT_RULE_SUPPORT`, `observed_failure_diversity_coverage=null`이다.
이는 오류가 아니라 등록된 네 번째 규칙과 실험 근거가 아직 없다는 정직한 상태다.
기존 goal_occupied 규칙은 v4 합성 archive의 실제 상자 pose로 검증했다.
전체 점유 FAIL은 해당 operational 연관 규칙에 걸리지만, 부분 점유만으로 판정하지 않고
PASS를 FAIL로 바꾸지 않는다. 사람 유형은 UNSUPPORTED로 유지된다.

## 검증 및 발견한 테스트 문제

주요 검사 범위:

- 세 preset의 그래프/지도/XML/scene revision 일치와 초기 목표 관계.
- 200개 seeded 임의 장면 및 경계값 조합에서 초기 비관통·끝벽 간격.
- 실제 G1 XML CPU 합성에서 29 구동기·관절 순서·보행 observation 구성 보존.
- 18축 요청 enum/호스트 검증, 합성 완화 제안 선택, 6+6 폐루프와 중단 재개 일치,
  동일 초기값과 비용 예산, 독립 탐색과 반복 슬롯.
- 새 축 bracket/대조·XML 변조 거부와 기존 goal_occupied 분류 연결.
- 사람 근접의 선형 교차·접선·분리 노출·누락·잘못된 입력·목표 결과 보존.
- 미리보기 CLI, plan-only CLI, 측정 CLI와 manifest/기존 경로 거부.

첫 확장 검사에서 기존 통로 테스트 19개가 실패했다. 이 테스트는 미리보기 지도 경로와
현재 로봇 계획기의 패딩 경로가 같다고 가정했다. 지도는 0.4m 발자국이고 로봇 계획기는
0.4m+0.1m tracking padding 및 반 셀 대각선 보수성을 사용하므로 같은 계약이 아니다.
HEAD의 기존 fixture 함수를 메모리에서 로드해 v2 5개/v3 24개, 총 29개 장면의
XML·지도·그래프·identity를 비교했고 이번 생성기 수정 전후 모두 동일했다.
따라서 로봇의 충돌 여유를 낮추지 않고 테스트를 두 계약 각각의 안전 조건 검사로 수정했다.
지도는 경로가 있지만 더 보수적인 로봇 계획기는 no_path인 seed 1 회귀 예제도 추가했다.

이 수정 후 half-cell 거리 부동소수점 오차 약 2e-16으로 새 테스트가 실패해
1e-10 비교 허용오차를 추가했다. 통로 테스트 83개가 통과했다.
수정 전후 실패를 감추거나 무조건 skip/xfail 처리하지 않았다.

최종 분류 연결 3개를 추가하기 전 관련 회귀는 **492 passed (125.29초)**였다.
추가 후 목표영역 campaign 테스트 파일은 **8 passed (21.74초)**였다.
분류 연결 3개를 포함한 최종 통합 검사는 **495 passed (134.19초)**다.
앞의 492개와 8개는 중복 재실행 수치이며 합산해 테스트 수를 부풀리지 않는다.
Ruff check 및 format --check는 수정한 Python 19개 파일 모두 통과했다.
이 수치는 전체 저장소 테스트/실제 로봇 성공률이 아니라 지정한 관련 테스트 모음이다.

## 저장 산출물과 실제 확인

최종 PNG·HTML 미리보기와 세 장면 CPU 자산 검사:

`/workspace/g1_failure/runtime/goal_region_previews/20261002T134536_927909Z`

manifest 20개 파일의 해시가 모두 일치한다. API calls/robot rollouts/physics steps는 모두 0.
PNG를 직접 확인해 목표 원과 상자/블록 배치가 구분됨을 확인했다. 최초 미리보기에서는
legend가 첫 블록을 가려 v4에서만 그림 하단으로 옮기고 새 폴더에 재생성했다.
첫 미리보기 `20261002T133625_364245Z`도 삭제하거나 덮어쓰지 않았다.

v4 도메인 감사:

`/workspace/g1_failure/runtime/failure_domain_audit/20261002T133632_615076Z`

JSON/CSV/HTML 3개 파일 해시와 기록된 소스 10개 해시를 확인해 불일치 0이었다.
읽기 전용 검증 중 보고서 키를 `readiness`로 잘못 조회해 KeyError가 한 번 있었고,
실제 필드 `target_readiness`로 다시 확인했다. 감사 생성기 오류나 저장 자료 수정은 아니다.
사용자가 실행했던 이전 v3 감사 `20261002T130333_961803Z`는 그대로 보존했다.

합성 작업자 근접 측정:

`/workspace/g1_failure/runtime/human_proximity/20261002T133634_468839Z`

입력·결과 2개 파일 해시가 일치한다. PASS + EXPOSURE_DETECTED, 총/연속 노출 1초,
최소 clearance -0.5m. 실제 사람 시뮬레이션/로봇 결과가 아니다.

정적 미리보기와 합성 측정만 실행했으므로 새 MP4는 없다. GIF도 생성하지 않았다.
실제 rollout의 기존 MP4-only 정책은 유지한다.

## 문서와 다음 실행

[GOAL_REGION_AFS.md](../scene2test/docs/GOAL_REGION_AFS.md)에 무료 preview/audit/plan과
별도의 유료 단독 clear 장면·AFS 전체 명령을 구분했다.
[HUMAN_PROXIMITY_CONTRACT.md](../scene2test/docs/HUMAN_PROXIMITY_CONTRACT.md)에 세 번째
항목의 입력·누락·미등록 상태와 후속 작업을 기록했다. README·로드맵·AGENTS도 갱신했다.
`write-page` 스킬의 문서화 원칙에 따라 설계, 구현, CPU/합성 검증, live 미검증을 분리했다.

다음 실동작 후보는 새 clear 장면 한 회이며 사용자가 예산과 API key를 확인해 실행한다.
이후 부분/전체 점유 또는 새 AFS 캠페인을 선택할 수 있다. 성공을 사전 가정하거나
구버전 캠페인 이력에 합치지 않는다. 공식 네 번째 유형을 위한 사람 장면·archive 계약은
별도 구현 단계다. Git commit/push는 수행하지 않았다.

## 최종 점검

관련 20개 테스트 파일의 495개 검사가 통과했다. 실행 명령:

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python -m pytest tests/test_corridor_scene.py tests/test_goal_region_scene.py tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot_goal_agent.py tests/test_robot_navigation_feedback.py tests/test_robot_navigation_recovery.py tests/client/test_corridor_campaign.py tests/client/test_goal_region_campaign.py tests/client/test_human_proximity.py tests/client/test_domain_readiness.py tests/client/test_usage_taxonomy.py tests/client/test_behavior_regression.py tests/client/test_afs_contrast.py tests/client/test_discovery_measures.py tests/client/test_behavior_memory.py tests/client/test_research_campaign.py -q --tb=short
```

실제 검사는 동일 프로젝트 `.venv/bin/python -m pytest`로 실행했다.
Ruff check/format 검사와 `git diff --check`도 통과했다. 테스트 중 실제 외부 API 또는
GPU 보행 정책을 실행하지 않았으므로 이를 새 도메인의 live 성공 근거로 쓰지 않는다.
