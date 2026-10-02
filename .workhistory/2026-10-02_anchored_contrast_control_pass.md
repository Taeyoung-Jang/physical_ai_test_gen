# AFS 폭 대조의 기준 장면 PASS와 응답 비용 특이사항

2026-10-02 UTC. 사용자가 실행한 `navigation_v3_width_20261002` 첫 시도를 검토했다.
결론은 기준 장면의 유효한 반복 성공이다. 기존 두 성공과 같은 조건에서 세 번째 PASS를
얻었지만, 3.6m와 3.2m 대조는 아직 미실행이다. 따라서 실패 경계나 AFS 우위를 발견한
결과는 아니다. 이번 검토는 원본 읽기와 문서 기록만 수행했으며 유료 실행은 하지 않았다.

## 원본과 무결성

- Suite: `/workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002`
- Rollout: 위 경로의 `attempts/attempt_00000/rollout`
- Report: 위 경로의 `reports/20261002T090644_942043Z/report.html`
- 이전 성공: `/workspace/g1_failure/runtime/robot_goal_agent/20261002T060144_446312Z`,
  `/workspace/g1_failure/runtime/robot_goal_agent/20261002T080932_214891Z`
- 기존 `read_goal_run(RunInput(...))`으로 62개 manifest 산출물과 계약을 검증했다.
  결과는 VALID / PASS / GOAL_REACHED, error_diagnostic null이다.
- 직전 성공과 protocol JSON 전체 및 scene.xml 바이트가 같다. 조건 ID는
  `0bc31e3cffc7eecf39ec5051402400f0589381e164403533968b9714113ef6d2`이다.
- 이번 evidence ID는
  `846b6f791c638f9343aa61ebf456599e139e1e700ef1f4877e758271d89e6b69`이다.
- 요청/반환 모델 Luna, 로컬 제어 CUDAExecutionProvider. 수락 행동/API 호출은 모두 7개,
  HTTP 200이며 자동 재시도는 없다. 호출 예산 10회, 시뮬레이션 상한과 기본 출력 토큰
  상한 없음, goal_dwell_v1 등 동결 조건을 유지했다.

## 행동과 목표 달성

GPT는 `[7, 0]`에 대한 plan_path 조회 1회 후 같은 좌표로 navigate_to 6회를 선택했다.
처음 이동 요청만 0.2초였고 이후 다섯 이동은 각 10초 요청이었다. 모든 최초 경로 계산은
성공했으며, raw move·push·request_skill은 없었다. 각 navigation_trace의 사건 목록은
비어 있고 차단 connector, 복구, 행동 내부 재계획은 기록되지 않았다.

| 호출 | 행동 | 요청 시간 s | 응답 wall 시간 s | 종료 목표 거리 m | 출력 토큰 |
|---|---|---:|---:|---:|---:|
| 1 | plan_path | 0.25 | 7.57 | 6.043 | 584 |
| 2 | navigate_to | 0.2 | 164.68 | 6.040 | 39230 |
| 3 | navigate_to | 10 | 6.30 | 5.317 | 386 |
| 4 | navigate_to | 10 | 6.05 | 3.704 | 266 |
| 5 | navigate_to | 10 | 4.48 | 2.186 | 290 |
| 6 | navigate_to | 10 | 4.24 | 0.804 | 253 |
| 7 | navigate_to | 10 | 3.55 | 0.115 | 226 |

plan_path는 이동을 실행하는 도구가 아니다. 그 구간의 작은 실제 위치 변화는
명령된 내비게이션 이동의 증거로 해석하지 않는다. 짧은 두 번째 행동의 순이동도
약 0.0061m에 불과했다. 0.2초를 고른 모델 내부 이유는 로그만으로 확정할 수 없다.

최종 base XY는 `[6.889963, -0.034447]`, 목표 거리는 0.115303m이다. 시뮬레이션
235.930초에 반경 0.25m 안 연속 1초 체류를 충족해 마지막 행동 도중 성공했다.
해당 행동의 원래 마감은 241.350초였고 호출 3회가 남았다. 도착 반경 0.12m에는
235.870초에 들어가 goal hold는 약 0.060초만 수행했다. 나머지 체류는 영역 안으로
접근하는 동안 누적됐으므로 정지 상태에서 1초 유지한 검증이라고 표현하지 않는다.
마지막 20Hz 표본의 dwell 0.975초와 full-rate 종료 판정의 1초는 샘플 시각 차이로 설명된다.

- 상태 표본 4719개, 최소 표본 base 높이 0.74027m, 최대 표본 tilt 약 8.98도.
- contact_start/end 각각 3221개, fall 사건 없음.
- 접촉 209467행은 clear_floor와 두 ankle_roll_link 사이이며 비바닥 로봇/월드 접촉 없음.
  이는 기록 범위의 관찰이지 전신·self-collision 일반 안전성 보증은 아니다.
- 상자 XY 이동 약 2.17e-8m로 수치 오차 수준이며 밀기를 시도하지 않았다.
- 복구 분기는 이번에도 필요하지 않아 실제 G1 보행 복구 능력의 검증은 여전히 미완료다.

## 응답 비용과 대기 시간

사용량은 7/7 관측됐고 누락·충돌 없음이다. 새 실행 입력 토큰 204674, 출력 토큰 41235다.
특히 두 번째 호출(`api_call_001.jsonl`)의 출력 39230개가 전체 출력의 약 95.1%를 차지한다.
이 호출은 약 164.68초 후 정상 HTTP 200으로 완료했으며 timeout이나 재시도가 아니다.
저장된 usage에는 세부 reasoning_tokens 구분이 없어 39230개 전체를 추론 토큰이라고
단정할 수 없고, 긴 응답의 제공자 내부 원인도 확정하지 않는다. 토큰 수는 관측 사용량이며
가격표에 따른 실제 청구액을 계산한 것이 아니다.

이전 두 성공의 시뮬레이션 시간은 66.815초와 77.660초였다. 이번 도구 실행시간 합계는
45.005초로 직전의 44.595초와 비슷하다. 총 235.930초 중 나머지 190.925초는 초기
안정화·추론 대기 등이며, 전체 시간 증가를 보행 성능 저하로 해석할 근거는 없다.
API wall latency 합계 약 196.87초는 시뮬레이션 대기시간과 다른 척도다.

이번 배치에서 AFS 장면 제안 API는 호출하지 않았다(`selection_costs=[]`). 큰 출력은
로봇 정책의 호출에서 발생했다. 비용이 중요한 관찰 사항이지만 고정 비교 도중 모델,
추론 설정, 호출 예산, 사용자가 제거한 토큰 상한을 임의 변경하지 않는다. 비용 최적화가
필요하면 별도 승인과 새 로봇 조건의 실험으로 분리한다.

## AFS 해석과 다음 실행

저장된 P1 memory는 사례 1개, 중복 0개, success_control PASS 3 / FAIL 0,
bracket 0개다. states/events/actions/object_motion은 AVAILABLE이고 경고는 없다.
기존 성공 두 번과 새 성공 한 번을 합친 관찰이며, 모집단 성공률 100%는 아니다.

| 폭 m | 이번 suite의 실행 결과 | 해석 |
|---|---|---|
| 4.0 | 1 PASS, 이전 동일 조건 2 PASS | 기준 성공을 재확인 |
| 3.6 | 미실행 | 다음 단일 축 대조 |
| 3.2 | 미실행 | 그 다음 단일 축 대조 |

미실행 행의 baseline_pass=2는 참조 기준선의 이력이다. 해당 폭에서 두 번 성공했다는
뜻이 아니다. READY/pending=null은 `--max-new-attempts 1`에 맞춰 첫 시도만 마친 정상
상태다. 전체 suite 완료나 AFS/Random 비교 완료를 뜻하지 않는다.

다음 명령은 같은 동결 조건으로 3.6m를 한 번 실행한다. 이 검토에서는 실행하지 않았다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_afs_contrast.py run --suite /workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002 --live --max-new-attempts 1
```

3.2m까지 마친 뒤 관측된 PASS/FAIL 구간이 있으면 그 사이를 좁히고, 모두 PASS면 더 좁은
값 또는 다른 축의 근거 기반 가설을 검토할 수 있다. 폭 변경은 다른 설정값은 고정하지만
측면 fraction으로 정의된 물체의 파생 Y좌표도 바꾼다. 따라서 순수 벽 위치만의 인과효과나
단조 실패 임계값으로 주장하지 않는다. 기존 AFS/Random 캠페인에 이 외부 이력을 넣지 않는다.

## 산출물과 변경 범위

원본 rollout에 `report.html`, `rollout.mp4`, 상태/결정/접촉/호출 저널과
`terminal_diagnostics.json`, `navigation_trace_*.json`이 보존돼 있다. 이번 검토는
기록 분석이며 전체 영상을 재생한 검토는 아니다. GIF는 생성하지 않았다.

write-page 스킬의 근거와 한계 분리 원칙을 기존 저장소 이력 형식에 적용해 이 문서,
이력 색인, AGENTS 최신 검토 메모만 수정했다. 실행 코드·과거 결과·동결 suite·원본
산출물은 수정하지 않았고 신규 API/GPU 실행, 커밋, push도 하지 않았다.
