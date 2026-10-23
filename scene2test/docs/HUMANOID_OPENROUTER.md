# OpenRouter 휴머노이드 개발 실행

사용자 지정 모델은 `openai/gpt-6-luna-pro`다. 로봇의 행동 정책만 OpenRouter로
전환하며, AFS 호출은 없다. 기존 OpenAI timeout 실행과 구분되는 새 개발 조건이다.
모델과 제공 경로가 함께 바뀌므로 결과 차이를 제공 경로만의 효과로 해석하지 않는다.

## 연결 계약

- 명시적 `--api-provider openrouter`; 기본 OpenAI 전송은 유지한다.
- 고정 endpoint `https://openrouter.ai/api/v1/chat/completions`.
- `OPENROUTER_API_KEY`만 사용한다. OpenAI 키로 대체하지 않는다.
- 기존 RGB·관측·지시·reasoning effort·strict JSON action schema를 변환 전달한다.
  응답은 기존 typed robot action parser로 검증하며 JSON 보정이나 추가 호출은 없다.
- `provider.allow_fallbacks=false`, `require_parameters=true`; 단일 지정 모델만 요청한다.
  요청별 upstream 선택은 OpenRouter가 수행하며 반환 provider·모델을 기록한다.
- HTTP read 300초와 기존 명백한 pre-send TCP 재시도만 유지한다.
  읽기 timeout·429·5xx·잘못된 출력은 재전송하거나 다른 모델/제공 경로로 대체하지 않는다.
- OpenAI direct의 `--service-tier default/flex`는 이 adapter에서 허용하지 않는다.
  `service_tier`를 생략하며 direct Standard와 동일한 서비스 조건이라고 주장하지 않는다.
- 반환 generation ID, 사용 토큰, 반환된 cost와 provider는 진단 로그에 보존한다.
  timeout 사용량은 UNKNOWN이며 0으로 계산하지 않는다.
- `policy_origin=openrouter_api`로 API 호출·승인 행동 수를 집계한다.
  후속 동적 평가 연결에서 archive reader/새 paired 개발 계획에도 origin을 등록했다.
  기존 평가에 표본을 합치거나 옛 frozen 캠페인을 재개하지 않는다.
  [동적 탐색 연결](HUMANOID_DYNAMIC_SEARCH.md)을 참고한다.

## 실행

사용자 터미널에서 `OPENROUTER_API_KEY`를 설정한다. 키를 채팅이나 명령 인자로
전달하지 않는다. 아래는 새 에피소드 1회, 최대 로봇 정책 호출 10회다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_robot_goal_agent.py \
  --live --api-provider openrouter --model openai/gpt-6-luna-pro \
  --scene-config config/humanoid_crossing_development.json \
  --enable-push --max-calls 10 --navigation-completion goal_dwell_v1 \
  --response-timeout 300 \
  --output-root /workspace/g1_failure/runtime/humanoid_crossing_openrouter
```

`--dry-run`을 추가하면 설정만 출력하고 자격 증명·GPU·API를 확인하거나 실행하지 않는다.
실제 OpenRouter 모델 접근 권한과 응답 지연은 mock 검사/dry-run으로 확인할 수 없다.
이번 구현에서는 실제 키 접근·유료 호출·GPU 실행을 하지 않았다.

OpenRouter의 [모델 설명](https://openrouter.ai/openai/gpt-6-luna-pro)은 Pro가 더 많은
추론 토큰과 시간을 사용할 수 있다고 안내한다. 300초 timeout 해결을 보장하지 않는다.
[routing 문서](https://openrouter.ai/docs/guides/routing/provider-selection)에 따라
provider fallback을 끄고 모든 요청 파라미터 지원을 요구한다.

## 이전 실행 보존

`/workspace/g1_failure/runtime/humanoid_crossing/20261023T003536_637106Z`의
manifest 35개 artifact 해시가 일치했다. OpenAI Luna/default 3요청 중 2정상 응답,
2승인 행동(plan_path, navigate_to 1초), 세 번째 요청은 response headers를
약 300초 기다린 ReadTimeout이었다. 결과 INCONCLUSIVE, 세 번째 사용량 UNKNOWN.
사람 최소 중심 거리 3.2887m > 트리거 2m로 출발하지 않았고 사람 접촉은 0이었다.
회피 성공/실패를 평가할 증거는 아직 없다. 이전 실행/예산/결과는 수정하지 않는다.
