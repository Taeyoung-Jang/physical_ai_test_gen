# 목표 중심 로봇 에이전트 v2

2026-09-18. 기존 `run_robot_vlm.py`/velocity-v1과 별도 버전이다.
최종 목표는 유지하되 중간 목표, 계획, 도구 선택과 재계획을 GPT가 결정한다.
원래 실패 장면/기록을 보존하며 로봇 capability를 바꾼 결과를 v1과 혼합하지 않는다.

## 로봇이 선택하는 도구

| 행동 | 실제 실행 |
|---|---|
| plan_path | GPT가 지정한 world XY까지 로봇 내부 BFS 경로 질의 |
| navigate_to | 지정 XY까지 경로 계산 및 제한 시간 동안 로컬 추종 |
| move | 기존 body-frame 속도/회전 명령, 최대 2초 |
| observe | 위치·방향 유지 후 재관측 |
| request_skill | 자유로운 추가 기술 요청, 현재는 unsupported 결과 반환 |
| stop | 에피소드 종료 |

`plan_summary`는 GPT가 작성하는 짧은 현재 계획이다. 숨겨진 사고 과정을 요구하지
않는다. 최근 8개 행동과 실제 도구 결과를 다음 이미지/지도/GT pose와 함께 제공한다.
경로, 실제 도착 여부, 제한 시간 내 미도착, 지원하지 않는 행동, 오래된 응답 거부를
기억할 수 있다. 전체 대화 무제한 보존이나 외부 영속 장기 기억은 아니다.

계획/이동 좌표는 GPT가 선택한다. 내부 경로 계획기는 관측된 공개 기하와 현재
로봇 위치만 사용한다. 외부 평가기의 정답 경로나 AFS 실패 가설은 받지 않는다.
팔 조작·집기·운반이 새로 생긴 것은 아니다. `request_skill`은 능력 부족을
명확히 반환하는 통로이며, 임의 코드 실행이나 물체 teleport의 통로가 아니다.

## 제어와 한계

- 관측: 실제 RGB + 전체 기하 지도 + GT pose. 카메라 위치/회전/fovy 제공.
- 5cm 격자, 반경 0.4m의 보수적 circular-footprint BFS. 회전된 형상은 AABB로 처리.
- navigate_to는 로컬 추종을 매 physics step 계산하며 0.12m 이내를 로컬 도착으로 본다.
  이는 평가기의 최종 과제 성공(0.25m 내 1초 유지)과 다르다.
- 네비게이션 실행 조각은 최대 10초. 완료하지 못하면 execution_slice_ended로 반환한다.
- 현재 지도는 정적 slice 조건이다. 동적 장애물 재계획/연속 전신 충돌 예측은 없다.
  경로 없음은 planner 모델하의 결과이지 모든 가능한 조작 전략 불가능 증명이 아니다.
- raw move는 VLM 속도 명령 그대로이며 내부 계획기가 대신 경로를 고르지 않는다.
- settle/응답 대기/observe에 별도 GT 위치·yaw 유지 제어를 추가했다.
  이는 zero-command v1과 다른 로봇 조건이며 강건한 hold를 보장하지 않는다.
- 기존 금지 접촉/넘어짐/수치 이상 종료와 15cm/0.2rad 응답 신선도 검사 유지.
  자기충돌 분류는 여전히 미구현. 토크를 GPT가 직접 출력하지 않는다.

## 실행

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
# 실제 GPU + 모의 정책. GPT 능력 검증 아님.
uv run python tools/run_robot_goal_agent.py --max-calls 2 --max-seconds 10

# OPENAI_API_KEY가 설정된 같은 터미널에서만 실행. 유료 호출 최대 10회.
uv run python tools/run_robot_goal_agent.py --live --model gpt-6-astra --max-calls 10 --max-seconds 120
```

기본 10회/120초, 모델 high reasoning, 호출별 출력 최대 4096 tokens.
API timeout/응답 대기 deadline은 기존 30초; 높은 reasoning이 이 제한을 넘으면
명시적 infrastructure 실패이며 재시도하지 않는다. API 접근·비용은 키 소유자 환경에
의존한다. 키를 로그/CLI 인자로 남기지 않는다. 이 구현 검증에서는 실제 호출 0회.
모든 도구 질의도 모델 호출 예산을 사용한다. 10회가 10개 이동 행동을 보장하지 않는다.

산출물: `/workspace/g1_failure/runtime/robot_goal_agent/<UTC>/`의 실제 영상/GIF,
카메라 이미지, 관측, 계획/행동/도구결과, physics states, protocol 및 hashes.
tool_NNN.json은 계획 당시 route 결과, decisions.jsonl의 tool_result는 실행 후 결과다.
최종 성공 여부는 GPT 주장이 아닌 독립 측정이다. 기존 scene은 상자로 막혀 있어
이동 전용 로봇의 no_path/지원 부족/정지 또는 실패가 정상적인 실험 결과일 수 있다.

## 검증 상태

오프라인/모의 HTTP 테스트 30개 통과. 실제 GPU 모의 정책에서 임의 근거리 목표
추종과 막힌 최종 목적지의 no_path 반환을 확인했다. 이 모의 목표는 테스트 fixture의
고정값이며 live GPT에 제공되는 정답/지시가 아니다. 실제 GPT 목표 계획·재계획 실행은
현재 agent 환경에 API 키가 없어 미검증이다. 대기 안정화의 장시간 반복 검증도 남아 있다.

OpenAI Docs 스킬로 공식 structured-output 계약을 확인해 기존 이미지 API 형식에
계획/도구 스키마를 확장했다. 여기서는 Responses의 구조화 JSON을 로컬에서 dispatch하며
네이티브 function_call 이벤트를 구현했다고 주장하지 않는다.
[공식 구조화 출력 문서](https://developers.openai.com/api/docs/guides/structured-outputs)

## Reliability update (2026-09-18)

API/local action schemas and diagnostic/video failure handling were corrected after the
initial implementation. See [ROBOT_API_RELIABILITY.md](ROBOT_API_RELIABILITY.md).
The existing CLI is unchanged; new requests use an action-specific command envelope.
