# 최종 이동 체류 처리와 AFS 근거 보완

2026-10-02 UTC. 사용자가 완료 파일럿 분석 이후 다음 작업 진행을 요청했다.
목표 도착·체류 판정·마지막 호출 종료의 관계를 점검하고, 기존 결과를 보존하면서
선택 가능한 실행기 보완과 회귀 테스트, 제한된 후속 실행 명령을 구현했다.
이번에는 새 API 호출이나 실제 G1 CUDA rollout을 실행하지 않았다.

## 기존 근거와 판단

원본 캠페인은 `/workspace/g1_failure/runtime/afs_benchmark/20260929T163123_122521Z`다.
완료 결과 분석은 [이전 작업 이력](2026-09-29_obstacle_afs_completed_result.md)을 따른다.
이번 작업은 원본 파일·SQLite·판정·사용량을 수정하지 않았다.

- AFS attempt_00006은 목표 거리 약 0.119m, 체류 약 0.775초에서 마지막 호출이 끝났다.
- 기존 navigate_to는 요청 좌표에서 0.12m 미만이면 즉시 반환했다.
- 독립 평가기는 목표 0.25m 미만에서 연속 1초를 요구했다. 기존 FAIL은 그 계약과 일치한다.
- Random attempt_00009의 PASS는 이동 후 다음 추론 대기 중 목표 체류를 채운 결과였다.
- 이 차이는 종료 시점에 민감한 사례이며, 경로 불가능성·물리적 한계·추가 시간의 확정 PASS 근거가 아니다.

## 구현한 선택 옵션

`--navigation-completion goal_dwell_v1`을 로봇 CLI에 추가했다.
기본값은 `position_only_v1`이며 목표 평가 계약과 10회 호출 예산은 바꾸지 않았다.

GPT가 navigate_to의 목적지로 최종 목표 좌표를 선택하고 0.12m 이내에 도착하면,
그 행동에 이미 할당된 남은 시간 동안 기존 GT 위치·방향 유지 제어를 사용한다.
성공 여부는 독립 GoalEvaluator가 물리 상태를 관측해 결정한다.
이탈하면 체류를 초기화하고 같은 행동 기한 내에서 기존 경로 추종을 재개한다.
호출 추가, 행동 시간 연장, 예산 이후 유예, 물리 상태 고정은 없다.
중간 경유점·경로 없음·stop의 기존 처리도 유지한다.

이는 평가기가 경로·밀기 방향·중간 목표를 지시하는 것이 아니다.
로봇 내부 실행기의 도착 처리 옵션이며 AFS는 계속 환경 조건만 변경한다.
legacy_guarded와의 조합은 사전 거부한다. 점프·집기·새 보행 정책 개발은 포함하지 않는다.

구현 파일은 `scene2test/src/robot_vlm/navigation_completion.py`, `goal_runner.py`,
`goal_policy.py`, `push_policy.py`, `task_outcome.py` 및 해당 CLI다.

## 기록과 다음 탐색에 전달하는 근거

- protocol에 전체 navigation completion 계약과 새 모듈 해시를 저장한다.
- 프롬프트 버전은 goal v4, push v6의 navigation completion 버전으로 구분한다.
- GPT에 목표 진행 상태와 도착 처리 계약을 전달하고 `goal_context_NNN.json`에 보존한다.
- 이동 tool_result에 행동 시작·요청 시간·실제 마감, 최초 도착 시각, hold 시간을 기록한다.
- 행동 종료 시 목표 거리·현재 체류·남은 체류를 로봇 피드백과 P1 행동 근거에 기록한다.
- AFS의 전체 action_timeline이 이 수치를 보존한다. 예전 누락 값은 생성하거나 0으로 채우지 않는다.
- result의 goal_progress와 terminal_diagnostics.json, HTML 보고서에 종료 근거를 표시한다.
- 진단은 기존 목표 결과·실패 유형을 수정하지 않으며 counterfactual PASS나 원인 확정이 아니다.

새 기본 모드도 진행 상태를 프롬프트에 추가하므로 과거 코드의 정확한 재생이라고 하지 않는다.
scene을 제외한 조건 해시에 프로파일이 포함되며, old/new 결과를 동일 조건 bracket으로 합치지 않는다.

## AFS와 회귀 실행 연결

RobotSettings에 옵션을 추가하고 로컬 실행 명령에 전달한다. 캠페인 및 회귀 수집 단계가
요청한 실행 조건과 실제 프로토콜을 대조해 불일치를 제외한다.
오프라인 reader는 새 계약의 전체 구조를 검증하고, 기존 필드 없는 프로토콜은 원래
position-only 의미로 읽는다. 기존 파일을 변경하거나 새 코드 drift를 우회하지 않는다.

회귀 plan/init은 `--navigation-completion`을 명시한 경우에만 source 옵션을 덮어쓴다.
생략 시 각 baseline의 옵션을 상속한다. 실행 중에는 동결된 설정을 바꿀 수 없다.
목표·장면·예산을 고정한 로봇 버전 비교이지 과거 로봇 판단의 동일 재현이나 인과성 실험은 아니다.

## 검증 결과

관련 로봇·행동 AFS·캠페인·회귀·측정 테스트 23개 파일: **388 passed, 5 skipped**.
검증 대상은 CPU MuJoCo, 모의 정책/제어기, 합성 아카이브와 모의 API다.
5개 선택적 테스트의 skip을 GPU/실험 통과로 계산하지 않는다.

테스트는 다음을 확인한다.

- 마지막 이동 시 기존 0.75초 체류 FAIL을 재현하고, 새 옵션은 같은 scripted 입력에서 1초 체류 PASS.
- 이탈 후 연속 체류시간 재시작, 중간 목표·no_path·stop 처리 유지.
- 행동 시간이 짧거나 시뮬레이션 상한에 도달하면 FAIL 유지, 추가 호출 없음.
- API/수치 오류는 기존 INCONCLUSIVE, 접촉·낙상 이벤트는 기존 복구 가능한 관측.
- 상태 진행 조회는 evaluator 상태를 변경하지 않고 비유한 좌표는 unknown으로 기록.
- 프로파일 상속/명시적 변경·실행 명령·프로토콜 일치·잘못된 조건 제외·원본 해시 보존.
- 체류 필드가 AFS 행동 요약까지 도달하며 FAIL이나 attribution을 변경하지 않음.
- GIF 비활성, MP4 스트리밍, 호출/토큰 사용량과 보수적 중단 처리를 유지.

마지막 프롬프트 버전 표기와 밀기 후 진행 상태를 반영한 핵심 5개 파일을 재검증해 **96 passed**였다.
앞의 확장 테스트와 중복되는 검사이며 합산해 독립 테스트 수로 주장하지 않는다.
변경 파이썬 파일의 Ruff 검사 및 git diff --check도 통과했다.
테스트 좌표의 scripted 이동은 실제 G1 능력 증거가 아니다.

## 실제 후속 계획의 오프라인 확인

기존 아카이브 3개를 read-only plan에 넣어 검증했다.

| 원본 | 역할 | 새 반복 수 |
|---|---|---:|
| attempt_00006 | 목표 근접 실패 | 2 |
| attempt_00009 | 성공 대조 | 2 |
| attempt_00004 | 장애물 간섭 연관 실패 | 2 |

plan 결과는 3 cases, max_attempts 6, robot_api_call_upper_bound 60, afs_requests 0이다.
모델은 기존 gpt-6-luna, 호출 최대 10, 명시적 시뮬레이션 상한 없음,
response timeout 300초, push 활성 상태를 상속했다. 이번에는 plan만 검증했고 suite 생성·live 실행은 하지 않았다.
제외도 예산을 소비하며 자동 대체하지 않는다. 토큰/금액 상한은 아니다.

실행 명령은 [최종 도착 처리 가이드](../scene2test/docs/GOAL_NAVIGATION_COMPLETION.md)에
단독 근접 실패 1회와 별도 회귀 suite 방식으로 구분했고, 둘 다 실행하면 비용이 중복됨을 명시했다.
README와 로드맵, AGENTS에도 현재 범위와 다음 단계를 반영했다.
문서 작성 지침에 따라 구현 완료, CPU 검증, 오프라인 계획, 아직 하지 않은 live 검증을 구분했다.

## 남은 한계와 다음 순서

추론 대기가 물리 시간에 포함되는 정책은 유지했다. 응답 시간·원격 모델·물리의 변동성이
사라진 것은 아니다. 새 옵션은 성공 보장이 아니고 다른 행동 전체에 유예를 주는 정책도 아니다.

1. 비용을 확인한 후 새 옵션으로 근접 실패 1회 또는 회귀 suite 첫 슬롯을 실행한다.
2. 결과의 목표 진입·연속 체류·도착 처리·종료 이유를 확인한다.
3. 선택한 새 조건의 반복을 확보한 뒤 동일 조건에서 AFS 성공 측·경계 탐색을 계속한다.

기존 Gain 20% 수치, coverage 또는 과거 PASS/FAIL을 재계산해 개선으로 주장하지 않는다.
이번 변경을 commit/push하지 않았다.

## 실제 실행 요청 후 사전 점검

사용자가 실제 실행을 요청하여 같은 근접 실패 장면 1회, Luna, 최대 10회 호출로
실행 준비를 점검했다. 장면 파일이 존재하고 NVIDIA RTX PRO 4500 Blackwell GPU가
조회됐으며, 관련 실험 프로세스는 발견되지 않았다. 다만 에이전트 실행 프로세스에
`OPENAI_API_KEY`가 없었다. 키 값이나 다른 비밀 파일은 조회하지 않았다.
따라서 유료 API 호출과 로봇 rollout은 시작하지 않았고 새 실행 결과도 생성하지 않았다.
이 기록은 GPU 조회 성공이지 CUDA 보행 실행 성공이 아니다.
키를 채팅으로 받지 않고 실행 환경에 제공하거나 사용자가 지정한 로컬 키 파일을 통해
전달받은 뒤, 승인된 1회 실행을 이어가야 한다.

## 사용자 실행의 EGL 시작 실패 진단

사용자가 키를 설정하고 실행한 뒤 `eglQueryString` AttributeError를 공유했다.
현재 hostname `8589a5c3255e`가 사용자 로그의 Pod와 일치하는 것을 확인했다.
Ubuntu 24.04.3에서 GPU는 조회됐으나 `find_library("EGL")`는 None,
`ctypes.CDLL("libEGL.so.1")`은 파일 없음 오류였다. dpkg에도 libegl1이 없었다.
NVIDIA vendor EGL 라이브러리는 ldconfig에 나타나지만 vendor-neutral EGL 진입점이 누락됐다.
`MUJOCO_GL=egl` 환경에서 `import mujoco`만 실행하여 같은 오류를 재현했다.

이 오류는 run directory 생성·정책 생성·API 요청 전에 발생한다.
이번 사용자 실행은 로봇 FAIL이 아니라 시작 전 환경 오류이며, GPT API 호출도 시작하지 않았다.
API 키 자체의 유효성을 확인한 결과는 아니다. 이전 GPU 조회와 CPU/모의 테스트는
실제 EGL context 검증을 대체하지 못했다.

권장 조치는 `apt-get update` 후 `apt-get install -y --no-install-recommends libegl1`이다.
[Ubuntu 공식 패키지 설명](https://packages.ubuntu.com/en/noble/amd64/libegl1)에서 EGL 지원을 확인했다.
현재 apt-cache에는 패키지 목록이 없어 update가 선행되어야 한다.
이번 진단에서는 시스템 패키지를 설치하거나 코드·기존 결과를 수정하지 않았다.
설치 뒤 API 없이 MuJoCo GLContext 생성과 GL_RENDERER를 확인하고,
EGL_OK 및 NVIDIA renderer가 확인될 때 기존 단독 실행 명령으로 재시도하도록 안내했다.
