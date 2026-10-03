# 목표 주변 AFS 대조: 기준 0.5 재실행 PASS 검토

## 요청과 결론

2026-10-02 사용자가 `goal_region_lateral_20261002/suite`의 첫 실행 결과 검토를 요청했다.
기준 장면 `box_lateral_fraction=0.5`는 **VALID/PASS, GOAL_REACHED**다. 기존 부분 점유
성공과 전체 프로토콜 및 scene.xml이 같으며, 같은 장면의 독립 기록은 PASS 2/FAIL 0이다.
완화 0.75와 도전 0.25는 아직 실행하지 않았다. READY/pending=null은 정상적인 단계별 진행 상태다.

이번 작업은 저장 근거의 읽기 전용 검사와 문서 기록이다. 새 API·로봇 실행, 실행 코드 수정,
DB/원본 결과 변경, 예산 변경, 폭 실험 재개를 하지 않았다. write-page 스킬에 따라 관측 사실,
추론 한계와 후속 절차를 구분하여 기존 저장소 문서 형식으로 기록했다.

## 근거 위치와 무결성

- Suite: `/workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002/suite`
- 새 rollout: 위 경로의 `attempts/attempt_00000/rollout`
- 보고서: 위 경로의 `reports/20261002T155936_352849Z/report.html`
- 이전 동일 장면: `/workspace/g1_failure/runtime/robot_goal_agent/20261002T143326_488034Z`
- 새 evidence ID: `6a60b1cdc3dc2dae00e975ad7dafc5cb3f006699dde02f1ae01dc0f55b389c64`
- 공통 정규화 condition ID: `8eadfca53d47c96b5393702d505e0069288b96605e61abf59736db3a145b654c`
- 공통 scene ID: `e4a46b7c5f80b7631ce26a8e43b37c1a014f394acb02862148881cf0fe56f3c7`

`read_goal_run`으로 새 rollout의 manifest artifact 66개를 검증했다. 보고서 manifest의 110개
해시도 일치했다. 이전 실행과 프로토콜 JSON 및 scene.xml 바이트가 동일하다. 읽기 전용 SQLite
조회에서 created → rollout_intent → observed, attempt 1회, pending 없음, 결과 해시 일치를
확인했다. 실행 receipt는 returncode=0, interrupted=null이다.

## 실제 행동과 목표 판정

Luna, CUDAExecutionProvider, goal_outcome_v1, goal_dwell_v1, clearance-recovery-v3 조건이다.
상자는 (7, 0.7)에 있으며 최종 목표는 기존 (7, 0), 반경 0.25m와 연속 1초 영역 체류다.

| 호출 | 실제 선택 | 실행 결과 | 행동 종료 시 목표 거리 |
|---|---|---|---:|
| 1 | navigate_to (7, -0.4), 10s | 실행 구간 종료 | 4.631m |
| 2 | navigate_to (7, -0.4), 10s | 실행 구간 종료 | 3.016m |
| 3 | navigate_to (7, -0.2), 10s 요청 | blocked_endpoint; 약 0.205s 처리 | 3.010m |
| 4 | navigate_to (6, -0.4), 10s | 실행 구간 종료 | 1.395m |
| 5 | navigate_to (6.5, -0.4), 10s 요청 | 중간 목표 도착 | 0.742m |
| 6 | move: body vx=0.18, vy=0.03, yaw=0, 2s | 실행 | 0.533m |
| 7 | move: body vx=0.10, vy=0.11, yaw=0, 2s | 실행 | 0.366m |
| 8 | move: body vx=0.10, vy=0.15, yaw=0, 2s | 실행; 영역 체류 0.605s | 0.178m |
| 9 | observe, 1s라는 응답 | 목표 판정 뒤 수신, **실행하지 않음** | 해당 없음 |

실행된 행동은 navigate_to 5회와 직접 move 3회, 총 8개다. plan_path나 push_object 실행은 없다.
일부 계획 설명에 밀기 접근이 언급되지만 그것은 물체 조작 실행의 근거가 아니다. GPT가 중간 목표와
직접 이동을 선택했고, 평가기나 사용자가 이 세부 행동을 지정하지 않았다.

8번째 행동 종료 시 시뮬레이션 시간은 200.715s, 체류는 0.605s였다. 다음 응답을 기다리며 기존
로봇 내부 pose/yaw hold가 실행되었고, 약 0.395s 뒤 201.110s에 체류 1초를 채워 성공했다.
full-rate 최종 위치는 (6.985420, -0.166574), 목표 거리 **0.167210m**다. 체류 부동소수 값
0.9999999999990905는 기존 허용 오차 내다. 마지막 저장 표본은 201.105s/0.995s이므로 최종
판정과 0.005s 차이가 있으며 모순이 아니다.

9번째 응답의 observe는 `pending_call.json`에 `completed_after_termination`, executed=false로
보존됐다. 응답이 도착해서 observe를 실행한 것이 성공 원인이 아니다. 완료 응답 보존 파일과
suite의 미해결 pending은 다른 개념이며 후자는 null이다. 9번째 요청의 실제 사용량도 비용에 포함됐다.

최종 목표용 navigate_to hold는 활성화되지 않았다. 연속 1초는 목표 **영역 안의 체류**이며
완전 정지 1초를 뜻하지 않는다. 추가 호출, 사후 유예, 시간 연장은 없고 10회 중 1회가 남았다.
raw move에는 navigate_to의 보수적인 원형 경로 여유 검사가 적용되지 않으므로 이 성공을
계획기 기준 전 경로 안전성 증명으로 해석하지 않는다.

## 행동 계측과 영상 확인

상태 4,023개, 접촉 표본 178,786개를 확인했다. 접촉은 모두 clear_floor와 발목 사이였다.
이벤트는 contact_start/end 각 2,758개뿐이며 넘어짐이나 바닥 외 로봇 접촉은 기록되지 않았다.
표본 기준 최소 base 높이 0.74059m, 최대 tilt 8.776도다. 상자 XY 순변위 약 1.46e-8m는
수치 잡음 수준이며 물체 이동 성공/실패의 근거가 아니다. 경로 추종 blocked connector,
clearance recovery, within-action replan은 모두 0이다. blocked_endpoint 한 번과 구분한다.

P1의 상태·이벤트·행동·물체 이동 근거는 AVAILABLE/warnings 없음이며, AFS용 요약에는 실행된
8개 행동과 후반 직접 이동이 모두 남았다. 미실행 observe를 실행 타임라인에 추가하지 않는다.
읽기 전용 failure memory는 이 두 archive를 같은 success_control PASS 2/FAIL 0으로 묶고,
중복 또는 PASS/FAIL bracket은 없다. 새 실패 유형이나 다양성 coverage를 부여하지 않았다.

`rollout/rollout.mp4`는 H.264, 960×540, 12fps, 2,414 frame, 약 201.167s다. 파일 전체
디코딩 검사는 성공했고 종료 부근 한 프레임을 확인했다. 전체 영상을 육안 재생한 것은 아니다.
GIF는 만들지 않았다. 검사용 마지막 프레임은 `/tmp/g1_goal_pair_control_review_VLDoPf/final.png`다.

## 이전 성공 및 비용과의 비교

| 항목 | 이전 부분 점유 성공 | 이번 기준 반복 |
|---|---:|---:|
| 판정 | PASS | PASS |
| API 호출 / 실행된 행동 | 10 / 10 | 9 / 8 |
| 시뮬레이션 시간 | 198.570s | 201.110s |
| 행동 실행 시간 합 | 45.585s | 40.975s |
| 최종 목표 거리 | 0.190542m | 0.167210m |
| 종료 phase | move | inference_wait |

시뮬레이션에는 추론 대기가 포함된다. 호출이 줄었다고 총 소요 시간이 줄거나 로봇 성능이
개선됐다고 단정할 수 없다. 동일 조건 재성공은 개발 기준선의 추가 근거이지 모집단 성공률,
단조 난이도, 경계, 원인 또는 AFS 우월성의 증명은 아니다.

| 비용 범위 | 호출 | 관측 입력 토큰 | 관측 출력 토큰 |
|---|---:|---:|---:|
| 이번 로봇 실행 | 9 | 268,905 | 16,111 |
| 앞서 완료한 AFS 후보 선택 | 1 | 25,635 | 1,312 |
| 상속한 두 로봇 성공 이력 | 14 | 388,372 | 16,336 |

새 로봇 호출은 9/9 usage 완전 관측, 충돌·누락·재시도 없음이며 각 요청은 HTTP 200으로 완료됐다.
미실행 9번째 응답의 48,702 입력/166 출력 토큰도 포함된다. AFS 선택은 이번에 재호출하지 않았다.
위 수치는 사용량 관측이지 청구 금액이 아니다. `baseline_pass=1`은 동결된 상속 기준이므로 새
성공을 반영하려고 기존 계획 필드를 다시 쓰지 않는다.

## 다음 단계

고정 suite의 3회 중 첫 기준 반복만 소진했다. 같은 명령을 다시 실행하면 **완화 0.75 한 장면**을
진행하고 기준을 재실행하지 않는다. 이번 후속 단계는 로봇 API 최대 10회이며 새 AFS 제안은 없다.
그 다음은 도전 0.25다. 두 후보 모두 아직 결과 미정이고 baseline_pass=1은 후보 성공이 아니다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_afs_contrast.py run --suite /workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002/suite --live --max-new-attempts 1
```

원래 3회/최대 로봇 API 30회 예산과 조건, 원본 archives, 중단한 폭 실험을 보존한다. 유료
후속 실행은 사용자 명령으로 별도 진행하며 이번 검토에서 자동 실행하지 않았다.
