# Goal-outcome 실제 실행 결과 검토 — 151327

검토일: 2026-09-26 UTC.
요청: 사용자 실행 `20260926T151327_858717Z` 결과 확인/분석.
범위: 저장 기록·코드·메모리 지표의 읽기 전용 진단과 이 검토 문서 작성.
실행 코드 수정, 원본 산출물 변경/복구, 신규 API/GPU 실험, commit/push는 하지 않았다.

## 실행 조건

- 실행 폴더: `/workspace/g1_failure/runtime/robot_goal_agent/20260926T151327_858717Z`
- 환경: `/workspace/g1_failure/runtime/behavior_afs/20260926T123153_802880Z/candidate_000.json`
- 상자 질량 2kg / 상자 friction .5 / 바닥 friction .8.
- protocol robot-goal-agent-v5 / evaluation_profile goal_outcome_v1.
- policy_origin openai_api / 모델 gpt-6-astra / execution_provider CUDAExecutionProvider.
- 호출 예산 10, simulation budget 없음, HTTP read 300초 / runner deadline 330초.
- 목표: base XY [7,0], 반경 .25m 미만 1초 유지.
- MuJoCo 3.12.0 / NumPy 1.26.4 / ONNX Runtime GPU 1.22.0.
- 저장된 runner source hash와 현재 goal_runner.py hash 일치 확인.

## 정상 완료 여부

로봇의 10개 응답/행동과 마지막 상태는 남았으나 실험 아카이브 저장은 완료되지 않았다.

존재: protocol, robot_audit, scene.xml, api_call_000..009, camera/observation_000..009,
decisions, states, contacts, events, terminal_state, rollout.mp4, tool_000/001.
없음: result.json, manifest.json, report.html, rollout.gif, error.json,
unexpected_error.json, failure_diagnostic.json.
현재 해당 로봇 Python 실행 프로세스도 남아 있지 않았다.

API 10개는 모두 HTTP 200 및 policy_completed. 전부 accepted이며 실제 tool_result가 있다.
마지막 action(move, 2초) 결과 시각과 terminal_state 시각은 460.2699999996539초로 일치한다.
events의 6401 contact_start와 6401 contact_end로 정상 observer close 흔적도 확인된다.

로그로 판단하면 호출 예산을 모두 사용한 목표 미달이며 예상 runner 결과는
FAIL / BUDGET_EXHAUSTED다. 그러나 이 값은 **기록 기반 추정**으로 공식 result.json이 아니다.
원본 결과를 임의로 재생성하거나 완전한 manifest 검증 run으로 취급하지 않았다.
현재 AFS 입력으로 바로 쓰면 manifest 부재 때문에 거부된다. 복구 검증이 선행되어야 한다.

## 로봇 행동

| 호출(index) | 선택 | 실행 결과/의도 |
|---|---|---|
| 0 | plan_path [7,0] | 보수적 원형 footprint 지도에서는 no_path |
| 1 | navigate_to [3.15,0], 10초 | 상자 서쪽 접근; 실제 base [2.5729,-.0461,.7430] |
| 2 | move .5초 | 남쪽 틈을 시험하려는 계획, 회전/횡이동 |
| 3–5 | move 각 2초 | 북쪽 bay 쪽 우회 계획으로 변경, 상자 서쪽 접근 |
| 6 | move .5초 | 아주 작은 후진; 계획 설명의 ‘북쪽 이동’과 실제 명령은 다름 |
| 7 | move 2초 | 후진·회전으로 곡선 접근 재설정 |
| 8–9 | move 각 2초 | 북쪽 틈으로 이동 시도, 목표 도달 전 예산 소진 |

총 plan_path 1 / navigate_to 1 / move 8 / push_object 0 / stop 0.
raw move 명령 duration 합은 13초, navigate 10초, planner 실행 .2초다.
나머지 대부분은 추론 대기 중 자세 유지다(20Hz 상태 표본 기준 약 435초, sim 시간의 약 94.5%).
API wall latency 합은 491.35초, 개별 24.31–79.24초. wall과 simulation 시간은 다른 수치다.

최종 base [3.473777, .493249, .743633], 원래 목표까지 3.560554m.
상자 중심은 초기 [4,0]에서 [4.089849,.012689]로 약 9.07cm 이동했다.
밀기 기술을 선택해서 수행한 이동이 아니라, 이 실행에서는 보행/자세 유지 중 무릎 접촉을
관측했다. 상자가 움직였다는 사실을 push executor 성공으로 기록하면 안 된다.

- 왼쪽 무릎–상자: t=243.22–339.245초 사이 922 per-contact samples,
  최대 normal force 90.80N.
- 오른쪽 무릎–상자: t=243.50–460.015초 사이 1105 samples, 최대 48.93N.
- non-floor contact samples 중 move 135, inference_wait 1892. 중복 contact point/tick이
  포함되므로 samples를 접촉 episode 수 또는 별도 실패 수로 읽지 않는다.
- fall/skill_failure 이벤트 없음. sampled base 최저 .73955m, 최대 tilt 약 8.97도.
  안정성 여유나 회복 능력의 측정값이라고 해석하지 않는다.

접촉 후에도 10회 모두 실행되었으므로 이전의 FORBIDDEN_CONTACT 즉시 중단은 발생하지 않았다.
무거운 상자를 못 밀었다는 결론도 낼 수 없다. 이번에는 해당 기술을 아예 요청하지 않았다.
이번 행동에서 다음 후보의 근거는 제한된 호출 예산 안의 우회 계획/명령 효율과 통로 접근이다.
질량·마찰의 기계적 한계를 확정하거나 즉시 질량을 증가시키는 근거로 쓰지 않는다.

## 영상과 저장 중단 원인

ffprobe 및 실제 이미지 디코딩으로 확인:
rollout.mp4 = H.264 / 960x540 / 12fps / 5524 frames / 460.333333초.
마지막 구간 이미지(t=459.83초)는 로봇이 상자 북서쪽에서 서 있는 상태다.
camera_000/009와 마지막 외부 시점 프레임을 실제로 열어 확인했다.
MP4 원본은 유지하고 마지막 프레임만 /tmp의 임시 진단 폴더로 추출했다.
영상의 녹색 bay marker는 legacy push_goal이고 이번 로봇 최종 목표 [7,0]와 다르다.

현재 코드의 저장 순서는:

`전체 RGB frames 리스트 누적 → MP4 close/terminal_state → imageio.mimsave(GIF) → result → report → manifest`

5524개의 RGB 원본 프레임만 약 8.00GiB다. 설치된 imageio PillowPlugin.write를 확인하면
list 입력을 np.stack으로 묶고 각 프레임을 PIL 이미지로 만들어 images_to_write에 다시
보관한다. 따라서 원본 프레임에 추가 사본/인코딩 버퍼가 함께 메모리에 올라간다.
GIF를 만들기 전에 result/manifest를 먼저 저장하지 않는 순서 때문에 인코딩 중 프로세스가
죽으면 이미 끝난 로봇 실행 결과 파일도 남지 않는다.

컨테이너 읽기 전용 진단:

- `/sys/fs/cgroup/memory.max`: 30,999,998,464 bytes = 약 28.87GiB.
- `memory.peak`: 같은 상한값.
- `memory.events`: max=21073, oom=1, oom_kill=1.
- 검사 시 memory.current 약 1.30GB; 호스트 free -h의 총 125GiB는 컨테이너 상한이 아니다.
- dmesg 접근은 Operation not permitted여서 OOM 대상 PID/정확한 시각을 매칭하지 못했다.

결론: **GIF 생성 중 호스트 RAM 한도 초과로 OOM-kill 되었을 가능성이 매우 높다.**
누락 파일 위치, 실제 코드 경로, 메모리 상한/peak/oom_kill 기록이 일치한다.
다만 cgroup 카운터는 누적값이므로 PID·시각까지 증명된 확정 로그는 아니다.
GPU/모델 추론 오류나 API timeout으로 확인된 것이 아니다.
기존 CPU 통합 테스트는 GIF writer를 mock 처리했으므로 실제 긴 영상 인코딩 RAM 문제를
검출하지 못했다. 실제 영상 저장 스트레스/메모리 검증의 공백을 기록한다.

## 별도 효율 관찰

입력 tokens: 첫 호출 7,554 → 마지막 40,485.
총 input 256,941 / output 18,480 / total 275,421 (저장된 API usage 합계).
이벤트/실행 피드백이 최근 8개 행동 기억에 반복 포함된다. 미래 개선 시 발–바닥의
일상적 접촉을 요약하고 중요한 비정상/진행 이벤트를 우선하는 문맥 예산을 검토할 가치가 있다.
단, 긴 응답의 원인을 문맥 길이 하나로 단정하지 않으며, 로봇 관측 조건을 바꾸면
새 비교 기준선/프로토콜로 분리해야 한다. 이번 검토에서는 프롬프트/기억을 바꾸지 않았다.

## 권장 다음 조치 (미실행)

1. 유료 rollout 재실행 전에 영상 저장 파이프라인 수정: 결과를 먼저 내구 저장,
   GIF는 해상도/fps/길이/메모리를 제한한 preview 또는 MP4 기반 별도 스트리밍 변환.
2. 기존 MP4와 완전한 실행 로그를 사용한 명시적 복구 도구/별도 provenance 기록.
   원본 실패 흔적을 덮지 말고 복구 산출물을 구분한다. 재현 없는 확정 판정 위조 금지.
3. 긴 실행의 실제 인코딩 메모리 및 후처리 실패에도 result가 보존되는 통합 테스트.
4. 아카이브 복구 검증 후 새 목표 기준 AFS에 입력. 로봇은 움직였지만 목표 미달이고,
   저장 시스템도 실패했다는 두 층을 별도로 관리한다.
