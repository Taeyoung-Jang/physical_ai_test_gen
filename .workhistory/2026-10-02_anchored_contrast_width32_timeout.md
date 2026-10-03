# AFS 통로 폭 3.2m 실험의 API 중단과 행동 변화 검토

2026-10-02 UTC. 사용자 실행의 세 번째 시도를 검토했다. 직접적인 중단 원인은
아홉 번째 로봇 API 호출의 HTTP read timeout 300초다. 원본 산출물은 검증됐지만
실행은 INCONCLUSIVE이며 목표 FAIL이 아니다. 그전에는 최종 목표 경로를 찾지 못한
GPT가 중간 지점을 골라 상자 북쪽까지 접근하는 행동 변화가 관측됐다. 이 관찰을
전체 목표 실패나 실제 밀기 수행으로 확대하지 않는다. 추가 유료 실행이나 코드 수정은 없다.

## 원본과 검증 결과

- Suite: `/workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002`
- Rollout: 위 경로의 `attempts/attempt_00002/rollout`
- Report: 위 경로의 `reports/20261002T095430_682721Z/report.html`
- 기존 `read_goal_run(RunInput(...))`으로 manifest 산출물 73개를 검증했다.
- evidence ID: `cc0e219913676c37e599cb5962829afc0d80b4ef588dc31c7512ea53b5f24f96`
- 판독 결과: status INCONCLUSIVE, exclusion_reason inconclusive_execution,
  termination_reason api_timeout, execution_valid false, task_outcome INCONCLUSIVE.
- result의 goal_reached null은 정상 완료 판정을 할 수 없다는 뜻이다. 별도 물리 상태의
  goal_progress.goal_reached=false는 중단 당시 목표 미달을 나타내며 둘은 모순되지 않는다.
- 3.6m 실행과 protocol의 차이는 scene_config와 scene_revision뿐이다. 설정 차이는
  corridor_width_m 3.6 → 3.2 하나다. 모델·로봇 코드·자원·목표·예산 조건을 바꾼 것은 아니다.
  다만 importer는 중단 실행에 정상 condition_id/행동 측정 레코드를 부여하지 않으며,
  이번 직접 로그 분석을 유효한 경계 표본으로 끼워 넣지 않았다.
- 자식 프로세스 returncode 0, interrupted null, wall 시간 약 421초다. 오류를 처리하고
  결과를 저장한 정상 프로세스 종료이지 실험 성공을 의미하지 않는다.

## 직접적인 중단 원인

`api_call_008.jsonl`은 observation_version 8, 즉 아홉 번째 호출이다.

1. 09:49:10 UTC에 호출을 시작했다. TCP/TLS 연결과 요청 헤더·본문 전송은 완료됐다.
2. 09:49:10.332부터 응답 헤더 수신을 기다렸다.
3. 09:54:10.403에 http11.receive_response_headers.failed가 기록됐다.
4. httpx/httpcore ReadTimeout으로 종료했다. result 진단 elapsed_wall_s는 약 300.442초,
   api_failed/policy_failed까지 포함한 저널 시간은 약 300.51초다.

응답 헤더를 받지 못했으므로 이 호출의 HTTP 응답 코드·정상 모델 응답·사용량은 없다.
앞선 8회는 모두 HTTP 200이며 수락 행동이 있다. 이 증거는 API 키 오류나 JSON schema
파싱 오류를 나타내지 않는다. 그러나 제공자 처리 지연, 중간 프록시, 네트워크 중 어느
부분이 응답 지연의 근본 원인인지 로컬 로그만으로 특정할 수 없다.

설정은 HTTP read 300초, runner deadline 330초, 시뮬레이션 상한 없음,
reasoning effort high, max_output_tokens null이다. 실패한 것은 HTTP read 제한이며
옛 120초 시뮬레이션 제한이나 출력 토큰 상한이 재도입된 것이 아니다.
retry_attempted=false다. 응답이 없었다고 미청구·제공자 측 미실행으로 단정하지 않는다.
검토에서 이 요청을 재전송하거나 timeout·추론 설정을 바꾸지 않았다.

## 중단 전 로봇 행동

8개의 수락 행동은 navigate_to 6회와 plan_path 조회 2회다. 이전 4.0m/3.6m 성공처럼
최종 목표만 계속 요청한 행동과 달리, 이번에는 내부 계획 결과를 보고 중간 좌표를 골랐다.

| 호출 | 로봇이 선택한 행동과 좌표 m | 실행 피드백 |
|---|---|---|
| 1 | navigate_to (7, 0) | no_path |
| 2 | navigate_to (4, 0.75) | blocked_endpoint |
| 3 | plan_path (7, 0) | no_path |
| 4 | plan_path (3, 0.95) | path_found |
| 5 | navigate_to (3, 0.95) | 실행 구간 종료, 약 (1.597, 0.876)까지 이동 |
| 6 | navigate_to (3, 0.95) | 중간 목표 도착, 약 (2.887, 0.912) |
| 7 | navigate_to (7, 0) | no_path |
| 8 | navigate_to (4, 0.95) | 중간 목표 도착, 약 (3.885, 0.915) |
| 9 | 다음 행동 요청 중 | 300초 HTTP read timeout, 새 행동 없음 |

두 번째·여덟 번째 plan_summary에는 상자 북쪽에서 접근해 남쪽으로 짧게 미는 방안을
고려한다는 설명이 있다. 이는 모델이 출력한 계획 설명이지 내부 추론을 관찰한 것은 아니다.
실제 push_object 또는 조작 skill 실행은 없었다. 평가기가 중간 지점을 지정하거나
밀기를 강제하지 않았고, 중간 좌표는 기록된 GPT action에 들어 있다.

no_path는 반경 0.40m에 추종 여유를 더해 planning_radius 0.50m로 계획하는 보수적인
정적 2D 계획기의 결과다. 조작까지 포함한 물리적 해결 불가능성이나 로봇 전체의
goal FAIL을 뜻하지 않는다. 이동이 실행된 세 구간에서는 차단 connector 0개였고
여섯 navigation_trace 모두 복구·행동 내부 재계획 사건이 없었다. 계획 단계에서 경로가
없다는 것과, 이미 생성된 경로를 추종하다 막히는 것은 구별해야 한다.

마지막 이동은 시뮬레이션 113.330초에 끝났다. API 대기를 포함한 종료 시각은
395.235초, 최종 목표 거리는 3.22686m, dwell 0초다. 호출 예산은 9/10을 사용했으며
한 번이 남아 있었다. 남은 호출로 성공했을지 실패했을지는 관측하지 못했다.

- 상태 표본 7905개, 그중 inference_wait 7354개. API wall 시간과 시뮬레이션 시간은
  다른 척도이므로 정확히 같은 간격으로 합산하지 않는다.
- 최소 표본 base 높이 0.74089m, 최대 표본 tilt 약 8.78도.
- contact_start/end 각각 5507개, fall 사건 없음.
- 접촉 352809행 모두 clear_floor와 두 ankle_roll_link 사이다. 기록된 비바닥 로봇/월드
  접촉은 없다. 모든 종류의 전신 안전성이 보장됐다는 뜻은 아니다.
- 상자 XY 표본 순변위 약 3.65e-8m로 수치 오차 수준이며 실제 밀기 근거는 없다.

## 사용량 누락의 의미

이번 시도는 API 9회, 그중 8회에서 입력 204453·출력 9019토큰이 관측됐다.
아홉 번째 호출의 사용량은 미상이다. usage_audit는 PARTIAL이며 충돌은 없고
calls_missing_usage=1이다. 0토큰이나 0원으로 해석하지 않는다.

사용자 로그의 전체 신규 누적은 API 22회, 관측 입력 559320·출력 52375토큰이다.
missing_attempts=0은 각 시도에서 관측 합계를 얻었다는 뜻이지 모든 호출의 비용이
완전하다는 뜻은 아니다. 별도 calls_missing_usage_observed=1이 이번 누락을 드러낸다.
기존 성공 두 번의 비용은 inherited_history_costs로 분리되며 AFS 선택 API는 없었다.

## AFS 결론과 후속 범위

4.0m는 기존 결과 포함 PASS 3회, 3.6m는 PASS 1회이며 3.2m는 판정 보류다.
저장된 failure memory에는 유효 episode 4개, 장면 사례 2개, excluded 1개,
duplicates 0개, brackets 0개가 남아 있다. 이번 중단을 FAIL이나 실패 유형으로 바꾸지 않는다.

3.2m에서 직접 목표 경로가 사라지고 로봇이 중간 지점·조작 준비를 고려한 것은 다음
검사에 유용한 행동 변화다. 하지만 3.2–3.6m를 목표 성공/실패 경계라고 보고할 수 없다.
폭은 파생 물체 Y좌표에도 영향을 주며, 물리·계획기·정책의 원인도 분리되지 않았다.

원래 계획한 3회 시도는 모두 소비했다. excluded도 고정 예산을 차지한다.
pending=null이므로 회수할 미확정 실행은 없다. 같은 run 명령을 반복해도 자동 재시도하지
않는다. continue-after-exclusion은 남은 계획을 진행하거나 제외 포함 완료를 확인하는
옵션이며 이번처럼 남은 계획이 없으면 새 로봇을 실행하지 않는다. next도 제외가 있는
suite의 자동 후속 탐색을 거부한다. 검토에서는 DB 상태를 변경하지 않았다.

권장 다음 작업은 원본을 그대로 보존하고, 별도로 승인한 예산으로 3.2m 장면을 다시
관찰하는 것이다. 기존 모델·프롬프트·300초 timeout을 유지하면 같은 선언 조건의 재검사다.
timeout이나 추론 설정을 바꿀 경우 새 로봇 조건이므로 성공 대조도 함께 새로 평가해야 한다.
무한 재시도·자동 대체·기존 예산 확장이나 결과 덮어쓰기는 하지 않는다.

## 변경과 산출물

원본의 report.html, rollout.mp4, api_call_008.jsonl, result.json,
terminal_diagnostics.json 및 행동·물리 로그는 그대로 보존돼 있다. GIF는 만들지 않았다.
이번은 저장 로그 검토이며 전체 영상 재생 검토는 아니다. write-page 스킬의 근거와
한계 구분을 적용해 이 이력·색인·AGENTS 최신 메모만 추가했다. 실행 코드·원본 suite·
과거 판정 변경, 새 API/GPU 실행, 커밋, push는 하지 않았다.
