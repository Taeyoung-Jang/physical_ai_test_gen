# 목표 중심 평가와 행동 AFS v2 구현 현황

2026-10-02 추가: [최종 도착 처리와 체류 검증](GOAL_NAVIGATION_COMPLETION.md).
별도 선택 옵션으로 최종 navigation의 남은 행동 시간에 자세 유지를 수행한다.
기존 목표 평가·예산·기본 도착 처리와 과거 결과는 유지하며 새 코드/관측 조건으로 기록한다.

2026-09-26. [설계](GOAL_OUTCOME_AFS_DESIGN.md)의 첫 세 단계 중 실행 가능한 핵심을 반영했다.
대상은 `tools/run_robot_goal_agent.py`와 `tools/run_behavior_afs.py`의 격리된 G1 경로다.
기존 Panda, velocity-only `run_robot_vlm.py`, navigation 서버의 평가 규칙은 바꾸지 않았다.

## 적용된 평가

기본 프로파일은 `goal_outcome_v1`, runner protocol은 `robot-goal-agent-v5`다.
최초 목표는 robot base XY가 `[7, 0]`에서 거리 0.25m 미만으로 1초 유지하는 것이다.
어떻게 도착했는지, 상자를 어디에 두었는지, 내내 서 있었는지는 추가 성공 조건이 아니다.
쓰러진 상태로도 이 XY 조건을 충족하면 PASS다. 이를 원하지 않으면 연구 시작 전에
별도의 목표 계약으로 정의해야 하며 결과를 보고 사후 조건을 추가하지 않는다.

| 최종 상태 | task_outcome |
|---|---|
| 유효한 물리 상태에서 원래 목표 달성 | PASS |
| 목표 미달로 호출/명시적 시간 예산 소진, 또는 로봇 stop | FAIL |
| API/스키마/수치 오류, 취소, 예상하지 못한 실행 오류 | INCONCLUSIVE |

접촉·낙상 자세·밀기 목표/해제 실패는 이벤트와 로봇 피드백으로 남기고 계속 실행한다.
벤치의 120N 초과 즉시 종료도 기본 프로파일에서 제거했다. 물리적 충돌은 정상 작동한다.
기존 로봇의 힘 기반 속도 조절, 자세 유지, 팔 후퇴, 기술 전제조건/명령 범위는 유지했다.
집기·점프·기립 회복 정책을 새로 구현한 것은 아니다. 로봇이 회복할 수 있다는 보장도 없다.

호출 예산의 마지막 행동과 push handoff까지 실행한다. 명시적 simulation budget이 있으면
그 시점에서 중단한다. 추론 대기로 그 예산을 소진해도 물리가 유효했다면 FAIL이다.
기본 시간 상한은 여전히 없고 호출 10회 기본값 및 개별 HTTP/runner deadline은 유지한다.

`--evaluation-profile legacy_guarded`는 구형 접촉/낙상 조기 종료 비교용이다.
그 조기 종료는 goal 결과에서는 INCONCLUSIVE다. 과거 코드/프롬프트의 완전 재현 모드는 아니다.
기존 결과 파일은 수정하지 않는다. 새 AFS는 새 프로파일 PASS/FAIL만 anchor와 bracket에 사용한다.

## 기록과 프롬프트

- protocol: 목표 계약·해시, 평가 버전, 코드·XML/mesh/YAML/ONNX 자원 해시,
  MuJoCo/NumPy/ONNX runtime 버전, 예산과 관측 조건.
- result: `task_outcome`, `goal_reached`, `termination.actor/reason`, `execution_valid`,
  `robot_condition_sha256`, `task_contract_sha256`, `events_summary`.
  기존 `success`, `valid_execution`, `reason`도 유지하지만 `valid_execution=true`만으로
  목표 실패 표본이라고 해석하면 안 된다.
- contacts: robot/world contact의 body·geom ID/이름, 시간·phase·거리, 실제 normal force,
  MuJoCo effective friction. 발–바닥 및 비허용으로 분류되던 접촉도 힘을 기록한다.
- events: geom pair/phase별 접촉 시작·끝, 최대 per-contact force와 합산 force의 적분,
  낙상 자세 시작·끝/직립 복귀, 기술 실패. tick마다 별도 실패를 세지 않는다.
- states: 원래 qpos/qvel/ctrl 외에 목표 거리와 dwell 시간.
- report.html, rollout.mp4, 로봇 카메라 이미지, 요청 진단 파일은 유지한다.
  2026-09-26 사용자 요청으로 GIF 저장과 전체 RGB 프레임 누적은 주석 처리했다.
  MP4는 프레임별로 저장하며, 결과 저장 전에 GIF를 변환하지 않는다.
  report에 목표 판정과 이벤트 요약을 분리해 표시하고 mock/live 고정 문구 오류를 수정했다.

로봇 GPT는 목표 계약, 최근 이벤트 최대 24개와 현재 활성 상태 최대 32개를 이미지/지도/
GT pose/최근 행동 결과와 함께 받는다. AFS의 가설이나 추천 전략은 받지 않는다.
이 관측/프롬프트 변경 자체가 새 로봇 조건이므로 이전 프로토콜과 섞어 경계를 만들지 않는다.
자기충돌/물체–물체 접촉 사건 분류, 미끄럼 접선속도, 안정성 여유, 이벤트별 영상 클립은 미구현이다.

## AFS 선택 변경

허용 축은 그대로 상자 질량·상자 마찰·바닥 마찰이다. 후보 생성이 로봇 행동을 바꾸지 않는다.

- 1–4개 공간, `success_probe`/`boundary_probe`/`cross_mechanism`.
  항상 현재값 양쪽이나 서로 다른 두 축일 필요가 없다.
- 각 공간 끝점을 one-axis 비교 후보로 만든다. 같은 조건의 반대 목표 결과가 있으면
  boundary_probe에서 중간점을 사용한다. 이는 확정 경계/단조성 증명이 아니다.
- 기본 반복 2개 + 독립 탐색 2개를 예약한다. 두 공간이면 기본 8개 슬롯이다.
  `--repeats`, `--exploration`으로 조절하며 duplicate는 자동 재충전하지 않는다.
- 비교 가능한 양쪽 조건 반복과 관측 PASS/FAIL 횟수를 기록한다. 실제 실행은 별도이며
  suite가 반복을 예약했다고 재현성이 확인된 것은 아니다.
- 실제 동일 행동 패턴 FAIL 3회 이상이 근처에 있을 때 해당 근방 probe만 쉬어 간다.
  축 전체를 금지하지 않는다. 패턴 분류는 간단한 로그 서명이고 인과성 추정이 아니다.
- 상자–바닥의 명목 접촉 마찰 max 규칙을 기록해, geom 값을 바꿔도 그 접촉 마찰은
  그대로일 수 있음을 표시한다. 손–상자나 발–바닥 효과가 같다는 의미는 아니다.
- 이전 suite는 중복 계획 방지, 실제 run 이력은 목표 표본/반복/쿨다운 근거로 구분한다.
  같은 run을 여러 번 제출해 독립 반복으로 세는 것은 거부한다.

기록의 manifest와 목표 계약 일치 여부를 검증한다. INCONCLUSIVE/legacy 입력으로
유료 제안을 요청하면 API 호출 전에 거부한다. 준비 전용 모드에서는 진단용 읽기가 가능하다.
정확한 context hash를 응답 schema에 고정하는 기존 수정도 유지한다.

## 실행과 검증 범위

복사하기 쉬운 한 줄 명령은 [실행 문서](BEHAVIOR_AFS_RUN_COMMANDS_KO.md)에 있다.
기존 robot CLI는 그대로 사용할 수 있으며 새 평가가 기본값이다. 새 기준선을 실행한 뒤
그 run을 AFS `--run`에 지정한다. AFS 출력 자체에는 로봇 영상이 없고 실제 robot 실행이
별도 MP4를 만든다(GIF는 비활성화). 결과 기본 위치는 모두 `/workspace/g1_failure/runtime` 아래다.

CPU MuJoCo + 가짜 정책/제어기 통합 테스트로 접촉 뒤 도착, 낙상 자세 뒤 복귀/도착,
밀기 해제 실패 뒤 다음 판단/도착, 예산 소진, 수치/API 이상 분류를 확인한다.
이 테스트의 scripted state 이동은 테스트 입력이지 실제 로봇의 달성 능력 증거가 아니다.
이번 변경에서 유료 API 호출 및 실제 G1 CUDA rollout은 실행하지 않았다.

남은 설계: 자동 다중 rollout campaign/재개 및 유효 예산 관리, factorial interaction,
통계적 경계 추정, AFS 이미지 분석, 기하/동적 환경 확장, Random/Sobol 공정 비교.

OpenAI Docs의 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
지침을 확인하고, 기존 Responses 구조화 계약과 지정 모델 `gpt-6-astra`를 유지했다.
프롬프트의 평가 의미만 맞췄으며 인증·전송·재시도 정책은 바꾸지 않았다.
