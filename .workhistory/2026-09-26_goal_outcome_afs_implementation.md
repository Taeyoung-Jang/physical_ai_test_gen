# Goal-outcome 평가기와 행동 AFS v2 구현

날짜: 2026-09-26 UTC. 요청: 사용자의 목표 중심 AFS 설계를 코드에 적용.

## 배경과 범위

사용자는 최초 goal을 로봇이 설치된 능력으로 달성하지 못하는 경우를 실패로 정의했다.
기존 실행기는 밀기 종료 직후 손–상자 접촉, 넘어짐, 해제 실패 등을 전체 과제의 종료로
처리했다. 특히 `20260926T130019_070486Z`의 push_handoff 재접촉은 새로운 목표 판정에서
바로 실패로 볼 수 없다. 원본 기록은 수정하지 않았고 실행되지 않은 후속 행동을 추정하지 않았다.

대상: 격리된 `robot_vlm/goal_runner.py`와 `llm_afs/behavior.py` 및 CLI/테스트/문서.
Panda/terrain/navigation server/velocity-only runner의 평가 의미는 변경하지 않았다.
자동 다중 캠페인, 신규 로봇 기술, 기하 변형까지 완료한 것으로 주장하지 않는다.

## 변경

1. `task_outcome.py`: 목표 계약/해시, 독립 GoalEvaluator, PASS/FAIL/INCONCLUSIVE와
   종료 주체. XY [7,0], 거리 <.25m, 1초 유지. 목표 계약에 항상 직립/상자 배치/무접촉을
   몰래 추가하지 않는다. robot stop과 유효 예산 미달은 FAIL, 인프라 오류는 INCONCLUSIVE.
2. goal runner 기본 `goal_outcome_v1`, protocol v5. 종전 `failed` 플래그를 `terminated`로
   바꾸고 접촉/낙상/120N 벤치 종료/skill release 종료를 기본 모드에서 제거했다.
   원래 물리와 로봇 내부 제어/전제조건은 유지했다. 마지막 호출의 행동·handoff를 실행하되
   명시적 simulation budget을 넘겨 계속 실행하지 않는다. 추론 중 budget 소진도 유효 FAIL.
3. `legacy_guarded`는 명시적 비교 모드다. 이 모드의 조기 중단은 새 goal 결과로 미확정이며
   새 AFS anchor로 거부된다. 과거 소스/프롬프트를 그대로 재현하는 기능은 아니다.
4. `behavior_events.py`: robot/world geom pair/phase별 접촉 episode, 최대 normal force,
   합산 force 적분, 낙상 자세와 복귀, skill failure. contacts.jsonl은 모든 robot/world 접촉의
   힘/실효 friction/거리/body/geom을 보존한다. 자기충돌/물체끼리의 접촉은 범위 밖이다.
   비동기 추론용 관측은 deepcopy snapshot으로 고정했다.
5. 로봇 프롬프트의 무접촉/무낙상 강제 문구를 새 목표 계약과 일치시켰다.
   관측에 제한된 최근 행동 이벤트를 추가했다. AFS 가설이나 경로/밀기 방향 지시는 보내지 않는다.
6. result/report에 목표 결과·종료 사유·이벤트를 분리하고 mock/live 고정 안내 오류를 수정했다.
   프로토콜 비교에는 task, 예산, 코드, 실제 robot audit 자원 hash, physics timestep과
   라이브러리 버전을 넣었다. XML/mesh/YAML/ONNX 자체를 변경하지 않았다.
7. AFS context/suite v2: 1–4개의 success_probe/boundary_probe/cross_mechanism 공간.
   한쪽 범위·같은 축의 다른 범위·도메인 끝점 허용. 기본 반복 2/독립 2 슬롯.
   비교 가능한 PASS/FAIL만 잠정 bracket으로 쓰며 실제 응답 모델명이 다르면 결합하지 않는다.
   명목 상자–바닥 마찰 max 규칙과 변경 여부, 비교/반복 횟수/근거/held_fixed를 저장한다.
8. 기존 축 전체 cooldown은 제거했다. 실제 완료된 같은 행동 패턴 FAIL 3회가 정규화
   거리 .05 이내에 있을 때 그 근방만 쉬고, 반복·먼 탐색은 남긴다. 이는 간단한 서명 휴리스틱이며
   인과 메커니즘 발견기가 아니다. 같은 run을 중복 제출해 반복 수를 늘리는 것은 거부한다.
9. manifest·결과/계약 일치를 검사한다. legacy/INCONCLUSIVE anchor는 유료 호출 전에 거부한다.
   앞서 수정된 context hash 전달/스키마 enum 고정/원본 보존 복구 코드는 유지했다.
10. 설계/구현 현황, BEHAVIOR_AFS, 한국어 한 줄 명령, ROBOT_GOAL_AGENT 및 AGENTS 갱신.

## 검증

유료 API 호출 0회, 실제 G1 CUDA rollout 0회. 테스트는 CPU MuJoCo와 가짜 정책·제어기로
실제 goal runner 루프를 실행하며 테스트용 상태 이동을 주입한다. 이는 G1이 넘어졌다
일어나거나 장애물을 해결할 수 있다는 물리 성능 증거가 아니다.

초기 핵심 테스트: 43 passed. 확대 회귀: 154 passed, 5 skipped (24.06초).
이후 원래 문제인 push_handoff 재접촉 사례와 관측 snapshot/응답 모델 비교 검사를 추가했다.
확대 회귀 재검증: **155 passed, 5 skipped (25.61초)**.
마지막으로 goal 달성 때문에 진행 중인 기술을 중단한 경우를 skill_failure가 아닌
skill_interrupted로 구분하고, 실행 루프 전체 **11 passed (12.01초)**를 재확인했다.
이 11개는 확대 회귀와 중복되는 테스트를 포함하므로 통과 수를 합산하지 않는다.
Ruff 변경 파일 검사 및 `git diff --check` 모두 통과했다.

재현 가능한 관련 회귀 명령 (`scene2test` 디렉터리):

```bash
.venv/bin/python -m pytest tests/test_robot_*.py tests/test_goal_outcome*.py tests/test_behavior*.py -q
```

GPU opt-in 환경 변수는 활성화하지 않았다. 5 skipped는 실제 GPU 통합 테스트다.

테스트 범위: goal dwell/reset, 접촉 후 도착, 넘어짐 자세 후 복귀/도착, release 실패 후 다음
판단/도착, 마지막 호출 실행, 명시적 시간/추론 예산 소진, 수치/API 오류, legacy guard,
실효 마찰의 MuJoCo 반영, 한쪽 탐색/도메인 끝점, 중복·근방 cooldown, 반복 양쪽 배정,
문맥 해시 복구/위변조 거부, 요청 스키마·진단·밀기/정렬·예산 기존 회귀.

기존 결과 읽기 전용 점검:
`/workspace/g1_failure/runtime/robot_goal_agent/20260926T130019_070486Z`
→ 원본 reason `FORBIDDEN_CONTACT`, valid_execution true는 보존.
→ 새 요약에서 evaluation_profile legacy_guarded, task_outcome INCONCLUSIVE.
영상/manifest/result 원본은 수정하지 않았다.

정적 검사: 변경 Python 파일 Ruff 검사 및 git diff --check 수행.
실행기/AFS를 실제 API로 재실행하지 않았으므로 다음 실제 실행은 새 기준선부터 해야 한다.

## 작업 환경·지침

기본 읽기 명령은 bwrap namespace 권한 오류로 실패했다. 범위를 한정한 승인된 읽기/테스트
실행을 사용했고, 코드/문서는 apply_patch로 수정했다. 컨테이너 보안 설정은 바꾸지 않았다.
기존 dirty 변경과 history 문서는 보존했다. git commit/push는 요청받지 않았으며 수행하지 않았다.

OpenAI Docs 스킬에 따라 공식 Structured Outputs 문서를 확인했다:
https://developers.openai.com/api/docs/guides/structured-outputs
기존 지정 모델 gpt-6-astra와 Responses JSON schema/전송/인증/재시도 정책은 유지했다.
API 키를 조회하거나 기록하지 않았고, 문서 점검 이외의 네트워크 호출은 테스트의 mock HTTP뿐이다.

## 남은 사항

새 프로파일 실제 GPT/GPU 기준선·후보 실험, 자동 campaign/재개/valid-rollout 예산,
factorial interaction/통계적 경계 추정, 이미지 AFS, 기하·동적 장면, Random/Sobol 공정 비교.
이 구현은 기존 3개 물리 축의 목표 중심 피드백 루프를 정비한 것이며 전 로드맵 완료가 아니다.
