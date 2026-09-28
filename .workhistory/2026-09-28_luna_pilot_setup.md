# Luna 비용 점검용 캠페인 설정과 밀기 외 AFS 확장 검토

날짜: 2026-09-28 UTC.

## 사용자 요청과 범위

- 앞으로의 개선안과 밀기 외 시나리오, 특히 점프 가능성을 설명한다.
- 비용 때문에 `gpt-6-astra` 대신 `gpt-6-luna`로 실험한다.
- 로봇/AFS 양쪽을 Luna로 지정한 별도 소규모 캠페인으로 해석하고 사용자에게 알렸다.
- 기존 Astra 캠페인, 원본 결과, 이전 미커밋 작업을 보존한다. Git commit/push는 하지 않았다.

## 근거 검토와 결정

OpenAI Docs 스킬과 model-migration 지침을 읽고 로컬 model 전달 경로를 먼저 확인했다.
공식 문서 https://developers.openai.com/api/docs/models/gpt-6-luna 에서 이미지 입력,
Responses API, Structured Outputs, 현재 reasoning 수준 지원을 확인했다.
문서상 호환성은 이 계정의 접근 권한/실행 성공을 보장하지 않는다.
모델 전달은 이미 설정으로 지원하므로 기존 prompt/endpoint/schema/실행기를 수정하지 않았다.
기존 기본값/회귀 fixture를 일괄 치환하지 않고 새 명시적 config만 추가했다.

현재 `PushPolicy`와 `GoalPolicy`를 읽어 설치된 물리 행동 범위를 확인했다.
상자 질량·상자 마찰·바닥 마찰만 현재 AFS goal-agent backend의 탐색 축이다.
미로/방/지형 생성기 존재와 해당 goal-agent 실행 연결은 다르다.
점프/잡기/운반은 executor가 없으며 request_skill은 unsupported를 반환한다.
GPT가 점프를 말하는 것만으로 기존 CUDA 보행 정책이 점프를 실행하지 않는다.

## 변경 파일과 내용

- `scene2test/config/behavior_afs_luna_smoke.json`: 양쪽 모델 Luna, seed17,
  방법별 유효 목표3/최대 시도3/cold2, AFS 제안 최대1. 총 로봇 호출 최대60 + AFS1.
  회당 로봇10회, 시뮬레이션 시간 기본 상한 없음, HTTP300초, push 사용은 그대로다.
- `scene2test/tests/client/test_luna_pilot.py`: 기존 episode 계약 보존, 모델 전달,
  plan-only 무변경/호출 상한, 합성 6회 캠페인과 첫 AFS 제안, 이미지/schema 보존 검사 5개.
- `README.md`: 복사 가능한 Luna plan/live 명령과 예산·제약을 먼저 안내한다.
  기존 bare 명령은 Astra 기본값임을 명시한다.
- `scene2test/docs/LUNA_PILOT_AND_SCENARIO_PLAN.md`: 개선 우선순위와 capability별
  현재 지원/추가 작업을 구분한다. 미래 계획을 이번에 구현된 기능으로 표시하지 않는다.
- `AGENTS.md`, `.workhistory/README.md`: 새 opt-in 설정/검증 범위와 이력 링크를 기록한다.

## 검증

`scene2test`에서 실행:

```bash
uv run --no-sync pytest tests/client/test_luna_pilot.py tests/client/test_afs_pilot.py tests/client/test_research_campaign.py tests/test_robot_vlm.py -q
```

결과: **76 passed in 49.77s**. 합성 archive/가짜 proposer/transport의 로컬 테스트다.
새 Luna 테스트 5개는 실제 API나 CUDA 로봇을 호출하지 않는다.
합성 캠페인은 AFS/Random 각3회, AFS 제안1회로 완료되며 양쪽 첫2회 장면 일치를 확인했다.
이 결과는 실제 Luna의 판단 성능, 실제 물체 이동/목표 도달, 비용 절감률 증거가 아니다.
Ruff check/format 검사와 `git diff --check`도 통과했다.
포맷 정리 후 새 테스트만 재실행한 결과도 **5 passed in 24.76s**다.

```bash
uv run --no-sync python tools/run_afs_pilot.py --config config/behavior_afs_luna_smoke.json
```

exit0. 두 모델 `gpt-6-luna`, 유효 목표6/최대 시도6, robot 상한60/AFS 상한1,
domain_id `91eea285d1ad4da54b66485255b4095b0a5ca6b697aa70564db24f1ec33c86e3` 확인.
`PLAN_ONLY`로 캠페인 파일 생성/API/GPU 실행 없음.

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --config config/behavior_afs_luna_smoke.json
```

**exit2, `--live requires OPENAI_API_KEY in the local environment`**.
키 값은 조회/출력하지 않고 현재 환경에 있는지만 검사했으며 MISSING이었다.
캠페인 생성 이전에 중단되어 **실제 Luna API 호출·GPU rollout·새 실험 결과는 없다**.
사용자의 다른 터미널에 설정된 키가 도구 실행 환경으로 자동 상속된다고 가정하지 않았다.
키를 채팅/문서에 요청하거나 기존 로그에서 추출하지 않았다.
키를 설정한 사용자 터미널에서 위 live 명령을 실행하면 된다.

## 후속 우선순위와 해석 제한

1. Luna 연결/행동/실제 usage 점검. INCONCLUSIVE 사용량 누락과 feedback 입력 증가 개선은 남아 있다.
2. 쉬운 우회 장면 같은 개발용 성공 대조 확보 후 성공/실패 경계·반복 변동을 탐색한다.
   기존 4+4 유효 FAIL만으로 AFS 우월성을 주장하지 않는다.
3. goal-agent의 장면 계약에 위치/크기/통로 폭/우회/구간별 마찰을 연결한다.
4. 검증된 failure-family 계측과 회귀 실행 자산화. 장면 종류 수는 taxonomy coverage가 아니다.
5. 점프는 별도 실제 제어기/adapter/물리 검증 과제이며 AFS 선행 필수조건으로 두지 않는다.

모델 둘을 바꾼 소규모 연결 점검은 AFS 모델만의 성능 비교가 아니다.
전체 boundary/exploration/repeat 순서를 검증할 예산도 아니다.
실패는 고정된 최초 목표·예산에서 판단하고, AFS는 로봇의 방법/행동을 지정하지 않는다.
시간 기본 상한120초를 복구하지 않았으며 MP4 유지/GIF 비활성화도 바꾸지 않았다.
