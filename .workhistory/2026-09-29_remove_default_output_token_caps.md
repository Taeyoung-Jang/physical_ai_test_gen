# 로봇·AFS 기본 출력 토큰 상한 제거

2026-09-29 UTC. 사용자 요청: `max token 은 그냥 없애버리세요.`
직전 파일럿에서 로봇 9번째 호출이 4096토큰 상한으로 미완성 종료된 진단에 대한 변경이다.

## 구현

- `robot_vlm/policy.py`: 기본 max_output_tokens=None. API 요청에는 해당 필드를 넣지 않는다.
- `robot_vlm/goal_policy.py`: 기본 카메라 요청에 4096을 강제로 전달하던 코드를 제거했다.
  PushPolicy는 상속한 요청을 사용하므로 push 사용 시에도 같은 변경이 적용된다.
- `llm_afs/provider.py`: 기본 4096을 제거해 behavior/캠페인/terrain AFS가 같은 생략 규칙을 사용한다.
- `tools/run_llm_afs.py`, `tools/run_expanded_afs.py`: 기본 4096/8192를 None으로 바꿨다.
  기존 `--max-output-tokens` 옵션과 helper 인자는 명시적 재설정을 위한 호환성 목적으로 유지한다.
  사용자가 이 옵션을 지정하지 않으면 숨은 기본 상한은 적용되지 않는다.
- `robot_vlm/goal_runner.py`, `runner.py`: 새 protocol의 max_output_tokens_per_call을 null로,
  output_token_limit_policy를 provider_default_no_client_cap으로 기록한다.
- Journal은 기존 body.get 경로로 API 요청에 상한이 없음을 null로 기록한다.
  저장된 AFS request.json에도 max_output_tokens가 없다.
- README, 장애물 AFS 실행 문서, AGENTS 메모리를 갱신했다.

## 변경하지 않은 것

- 로봇 행동 호출 예산, 유효/최대 시도 예산, 시뮬레이션 시간 설정, HTTP/runner deadline.
- 추론 강도(high/medium), 모델 이름, 프롬프트·관측·행동 기술·목표 판정.
- strict schema/출력 형식 검증, 관측 payload 크기 제한, 비밀정보 보호.
- 미완성 응답의 INCONCLUSIVE 분류, 상세 오류/토큰 사용량 기록, 자동 재전송 금지.
- 원본 실험·이전 프로토콜·SQLite 체크포인트·고정 예산. 이전 제외를 삭제하거나 FAIL로 바꾸지 않았다.
- 유료 API 호출, GPU 로봇 재실행, 새 live 캠페인 생성, commit/push는 하지 않았다.

## 공식 API 확인 및 한계

OpenAI Docs 스킬로 공식 create response 문서를 검색하고 실제 페이지를 열어 확인했다:
https://developers.openai.com/api/reference/cli/resources/responses/methods/create

max_output_tokens는 선택적 필드이므로 생략했다. null/무한대/임의의 큰 수를 API 요청에 보내지 않는다.
우리 코드의 기본 ceiling을 제거한 것이지 API·모델의 자체 출력/컨텍스트 한도를 제거한 것이 아니다.
따라서 향후 미완성 응답이 절대 없다는 보장은 없으며, 비용/지연이 늘어날 수 있다.
이번 작업은 실제 API의 생략 동작을 유료 호출로 검증한 것이 아니라 요청 형식과 오류 처리의
오프라인/모의 검증이다. 기존 high 추론 강도를 비용 절감 목적으로 몰래 낮추지 않았다.

## 검증

- 새 test_output_token_defaults.py: robot/AFS 기본·명시적 None에서 필드 생략,
  명시적 cap만 적용, 기존 잘못된 cap 거부, terrain/expanded CLI 기본 request-only 경로에서
  필드 생략과 API 호출 0을 검사한다.
- 기존 모의 transport 테스트에서 velocity/goal/push/AFS 실제 전송 body에 상한이 없는지 검사한다.
- 모든 behavior request 선택 정책에서 생략, Journal의 null 기록, 실제 CPU runner protocol의
  null/정책 표기, GIF 미생성, 미완성 응답 진단/재시도 금지 유지 등을 검사한다.
- 관련 단위/CPU/모의 API 테스트: 187 passed, 3 skipped (34.10초).
  제외 3개는 명시적 opt-in GPU 오류/지연 스모크 테스트다. 실제 GPU/LLM 성공 근거가 아니다.
- 변경 Python 코드·테스트 Ruff 검사 통과. git diff --check 통과.
- 캠페인/고정 조건/파일럿/통로/AFS 선택/회귀/유형·사용량/발견 측정 검사:
  183 passed (77.40초). 앞 검사와 합계 370 passed, 3 skipped.
  tests/client/test_research_campaign.py, test_campaign_integrity.py, test_afs_pilot.py,
  test_corridor_campaign.py, test_afs_search_improvements.py, test_behavior_regression.py,
  test_usage_taxonomy.py, test_discovery_measures.py를 실행했다.

## 기존 캠페인 처리

출력 조건과 source hash가 바뀌므로 변경 전 고정 캠페인을 새 코드로 재개하면 drift 차단이 정상이다.
이 검사를 우회하거나 기존 원본에 새 프로토콜을 덮어쓰지 않는다.
새 조건으로 실행하려면 새 캠페인을 시작해야 한다. 단, 기존 장애물 config의
유효 목표 6회/최대 시도 6회는 제외 여유가 없다는 한계가 그대로이며 이번 토큰 변경과 별개다.
시도 여유/비용 상한을 바꾸는 작업은 요청 범위를 넘어 자동 적용하지 않았다.
