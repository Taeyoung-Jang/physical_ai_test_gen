# 2026-09-28 — 다중 장애물 slalom live 결과 검토

## 요청과 결론

사용자가 Luna로 실행한 obstacles-v3 장면의 정상 작동 여부와 다음 작업을 요청했다.
원본 실행: `/workspace/g1_failure/runtime/robot_goal_agent/20260928T151133_926563Z`

독립 importer에서 **VALID / PASS / GOAL_REACHED**로 확인했다. GPT가 내부 계획기를
사용하고 상자를 밀지 않은 채 고정 장애물 2개와 상자 사이를 걸어 통과했다.
새 환경의 실제 GPU/VLM 연결을 확인한 한 사례다. AFS가 고른 장면이 아니라 개발용
fixture를 사용자가 실행한 결과이므로 AFS/Random 성능이나 일반 성공률로 집계하지 않는다.

이번 검토는 API/GPU 실행 0회. 원본 실행/소스는 수정하지 않고 이력과 상태 문서만 갱신했다.
기존 미커밋 소스 변경은 보존했으며 commit/push하지 않았다.

## 무결성·목표·환경 검사

- `read_goal_run(RunInput(...))`: VALID, 제외 사유 없음, 반환 모델 `gpt-6-luna`.
- manifest 41개 artifact의 해시, 필수 파일, 계약/예산/결과 일관성 검증 통과.
- `_scene_parameters`: scene_config로 재구성한 XML과 일치, warning 없음.
- scene revision, SceneGraph, navigation_map도 현재 생성기로 재구성한 자료와 일치.
- 실제 VLM 관측: floor, 4개 벽, obstacle_1, obstacle_2, clear_box_geom 모두 포함.
- protocol execution_provider=`CUDAExecutionProvider`: GR00T 보행은 GPU 실행.
  Luna는 외부 API이며 로컬 GPU에 Luna를 올렸다는 의미가 아니다.
- RGB + 전체 geometry + GT pose. evaluator reference path 제공 여부는 false.
- 시작 `[1,0]`, goal `[7,0]`, 반경0.25m/dwell1s, max_calls10, simulation 상한 없음.
- 최종 base `[6.9073707681, 0.0155746832, 0.7449030821]`m, goal 거리 **0.0939294702m**.
- 종료 simulation time **82.925s**(추론 대기 포함), state sample1,659개.
- 마지막 샘플82.905s의 dwell은0.98s. 목표 판정은 full-rate evaluator가 더 늦은
  terminal 시점에 기록했다. sampled trace만으로 전체 dwell을 독립 재현한 것은 아니다.
- evidence_id=`4ffbd1e99f406f31184f1abd760d222ad98e50d41a0cad34c5e6e35a27c90b10`.
- scene revision=`4710739f899e93f095d7255c729c0266b90e49c1470c33760ba6714cea25fbb3`.

## 행동 시간선

| 시점 | simulation time | base XY (m) | 행동/결과 |
|---|---:|---|---|
| 첫 관측 | 2.005 | 0.952, −0.007 | GPT가 plan_path([7,0]) 선택 |
| 도구0 | 8.235 | 0.957, −0.017 | path_found |
| 도구1 | 23.850 | 2.532, −0.146 | navigate_to, 첫 고정 물체 남쪽 통과 |
| 도구2 | 43.595 | 3.533, 0.200 | navigate_to, 중앙 상자 북쪽 우회 |
| 도구3 | 59.210 | 4.941, −0.177 | navigate_to, 두 번째 고정 물체 남쪽 접근 |
| 도구4 | 73.985 | 6.297, 0.006 | navigate_to, 두 번째 물체 통과 |
| 도구5 | 82.675 | 6.881, 0.007 | navigate_to, target_reached |
| evaluator 종료 | 82.925 | 6.907, 0.016 | GOAL_REACHED |

수락된 행동은 plan_path1회 + navigate_to5회. navigate_to의 target은 모두 최종 goal이며
로봇 내부 계획기가 현재 geometry/pose로 경로를 계산했다. AFS/evaluator가 중간 경유점이나
밀기 방향을 지정하지 않았다. execution_slice_ended4회는 실행 구간 종료이며 오류가 아니다.
push_object0회, 상자 XY 순변위 약6.0e-9m로 의미 있는 상자 이동이 없다.

7번째 호출은 target_reached 도구 결과 뒤, goal dwell 완료 전에 시작됐다.
0.25 simulation 초 후 evaluator가 성공 종료했고 응답은 이후 도착했다.
pending_call.json에는 completed_after_termination, executed=false, observe1.5s 제안이 남았다.
이는 API/timeout 실패가 아니다. 종료 후 명령을 추가 실행하지 않았다.

## 물리·행동·영상

- behavior evidence=AVAILABLE, states/events/actions/object_motion 모두 AVAILABLE, warning 없음.
- fall interval0, recovery event0. 최소 base height0.740233m, 최대 tilt8.77635도.
  이 값은 진단용이며 stability margin/near-fall 측정은 아니다.
- contacts.jsonl73,494개는 모두 clear_floor와 좌/우 ankle_roll의 접촉이다.
  비지지 물체/벽/상자 접촉0, not_legacy_allowed0.
- contact_start1156/contact_end1156는 발–바닥 지지 접촉이며 충돌 실패가 아니다.
  peak normal force245.425N도 지지 접촉 값이다.
- self-collision classification은 not_implemented. robot/world 범위를 넘어
  모든 종류의 충돌을 검증했다고 주장하지 않는다.
- sampled base path length11.9578m는 보행/정지 진동을 누적한 원시 base 궤적이다.
  순수 우회 경로 길이나 비효율의 확정 지표로 해석하지 않는다.
- rollout.mp4: H.264, 960×540, 12fps, 996frames, 83.0s, 2,940,351bytes. GIF 없음.
  ffprobe와 대표/최종 프레임을 확인했다. 블록 사이를 걸어 목표에 접근하는 모습이
  기록과 부합한다. 대표 프레임 점검이 모든 프레임의 충돌 검사를 대신하지는 않는다.
  원본은 보존하고 임시 검토용 JPEG만 `/tmp`에 추출했다.

## 발견한 보완 사항 — 코드 수정은 후속 작업

1. **종료 후 응답 비용 집계**: importer의 decision-only 합계는6호출 input126,023 /
   output2,650 tokens. pending_call의7번째 완료 응답은 input37,977/output321이다.
   합치면 제공자 관측 사용량은 **input164,000/output2,971 tokens**다.
   데이터는 보존되어 있지만 기본 합계에서 빠지고 경고만 표시된다. 호출 ID로 중복 없이
   합칠 필요가 있다. 이 합계는 청구 금액 검증이 아니다.
   api_call_000..006은 모두 api_completed/policy_completed로 종료, 재시도 없음.
   journal elapsed는 약4.52–10.20초이며 timeout이 없다.
2. **단독 runner 소스 provenance**: source_hashes에 fixture.py/contracts.py 등은 있지만
   새 obstacles.py의 직접 hash 항목이 없다. runner.py의 현재 hash는 저장값과 같다.
   XML/scene revision/관측/manifest가 보존·검증되어 이번 PASS를 무효화하는 상황은 아니다.
   다만 helper 변경도 소스 수준 재현 기록에 포함해야 한다. campaign의 recursive
   clear_path fingerprint는 이 파일을 포함하므로 단독 runner 기록과 구분한다.

## 다음 작업

새 환경 연결을 확인했으므로 반복 비교를 늘리는 대신 개발을 진행할 근거가 생겼다.

1. 위 두 기록 정합성 문제를 작은 유지보수로 보완. 과거 원본/목표 판정은 보존한다.
2. 본작업은 근거 기반 실패 유형 measure/detector: 접촉, 장애물별 정체·재계획,
   목표 영역 점유를 먼저 다룬다. goal outcome과 진단을 분리하고 UNKNOWN/UNSUPPORTED를
   보존한다. 실제 goal FAIL + 검증된 규칙 + 증거가 있는 경우만 family coverage로 센다.
   이번 성공 사례는 발 접촉을 실패로 오분류하지 않는 음성 대조 자료가 된다.
3. 저장 사례를 재실행하는 회귀 runner: PASS→FAIL/FAIL→PASS/유지/INCONCLUSIVE 및 반복
   혼합 결과를 구분한다. 이번 단일 성공이 반복 신뢰도를 입증하는 것은 아니다.

이 standalone 성공을 frozen AFS arm history/cold-start 비용에 조용히 넣지 않는다.
실패 유형4/6, AFS Gain 달성은 여전히 미검증이다.
