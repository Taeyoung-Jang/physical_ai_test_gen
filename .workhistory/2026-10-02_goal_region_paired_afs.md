# 두 성공 행동을 이용한 AFS 양쪽 배치 제안 구현

2026-10-02 UTC. 사용자는 빈 목표와 부분 점유의 성공을 AFS에 전달하고, 부분 점유 기준
반복과 여유 있는 배치·좁은 배치를 시험하는 후속 작업을 승인했다. 새 개발용 제안 세션을
구현했다. 기존 대조 실행기·행동 메모리·목표 판정을 재사용하며 로봇 행동은 수정하지 않았다.
이번 작업에서는 유료 API·GPU 추론·로봇 rollout을 실행하지 않았다.

## 실제 근거와 범위

입력은 사용자 실행 `20261002T141132_394018Z`와 `20261002T143326_488034Z`다.
각각 빈 목표/부분 점유 PASS이며 순서대로 마지막 기록을 고정 anchor로 사용한다.
사전 검증에서 두 기록의 무결성, 동일 조건·기하 정규화, 현재 로봇 소스·외부 자산·런타임
일치를 확인했다. 원본을 수정하거나 기존 폭 suite·AFS/Random 캠페인을 재개하지 않았다.

생성 요청에는 부분 점유 행동 10개(plan_path, navigate_to 5개, move 4개), 빈 목표 행동
4개(navigate_to 4개)가 모두 들어간다. 각 실행의 대표 상세 구간은 12개다. JSON 요청
전체 UTF-8 크기는 사전 점검에서 73288바이트였다. 이미지/영상 전체를 LLM에 전송하지 않는다.
초반 계획 거절뿐 아니라 후반 직접 이동 성공을 보존한다. 상자가 움직이지 않았다는 사실을
밀기 실패로 해석하지 않으며 목표 반경 체류와 정확한 목표 중심 도착을 구분한다.

## 구현

- `afs_paired_contrast.py`: `goal-region-paired-proposal-v1` 요청·검증·durable 선택 세션.
- `run_afs_contrast.py prepare-pair`: 원본/조건 확인, context/request/protocol/이력 저장.
- `select-pair`: 한 번의 Luna 제안 또는 저장 응답 검증, 기존 실행기로 총 세 시도 준비.
- `behavior_regression.py`: 기존 보고서에 제안 가설과 실제 행동 비교를 추가한다.
- 기존 `afs_contrast.py` 미리보기는 새 probe 목적을 표시한다. 기존 대조 동작은 유지한다.

초기 세션은 같은 v4의 성공 장면 2–8개만 받는다. FAIL/혼합 결과는 이 시작 단계가 아니라
기존 후속 `next`의 반복/경계 선택 경로에서 처리한다. 상자 측면 위치 이외에 차이가 있거나,
중복 archive·불완전 결과·로봇 조건이 다르면 거부한다. 마지막 `--run`이 anchor라는 운영자
선택을 명시하며 LLM이 anchor를 선택했다고 주장하지 않는다.

허용 축은 `box_lateral_fraction`뿐이다. 이번 anchor 0.5에서
`0 <= challenge < 0.5 < relief <= 1`을 요구한다. 같은 양의 Y 방향에서 공간을 줄이거나
늘리는 대조이며, opposite-side 배치나 다른 17축 탐색은 이번 단계 밖이다. 이미 관측한
0.5와 1.0은 새 후보에서 거부한다. 범위 끝 0.0 자체를 정적 경로 없음 때문에 거부하지 않는다.
relief/challenge는 기하 가설 이름일 뿐 실제 난이도·결과가 단조라고 선언하지 않는다.

모델 출력은 두 값, 고정 hash/anchor/axis, 각 가설·예상 관측·반증 조건·근거 ID다.
제안 전체가 두 관측을 모두 인용해야 한다. 근거 ID enum과 호스트 검증을 함께 적용한다.
허용하지 않은 필드/로봇 명령/다른 축·NaN/Inf/bool 값·잘못된 방향/중복/오래된 context는
거부한다. 후보 값은 아직 LLM이 제안하지 않았으므로 실제 폴더에 예제값을 대입하지 않는다.

## 예산과 오류 복구

최초 준비 단계는 무료다. 선택 세션마다 AFS 요청 최대 1회, 성공한 제안으로 기준 반복·relief·
challenge 각 한 번을 준비한다. 원본 Luna 10회 호출 조건에서 로봇 요청 상한은 30회다.
준비/제안 명령은 로봇을 실행하지 않고, `run --live --max-new-attempts 1`로 한 번씩 실행한다.
기본 출력 토큰·시뮬레이션 상한, API 자동 재시도, 대체 실행을 추가하지 않는다.

SQLite intent를 네트워크 호출 전에 저장하고 OS 잠금으로 중복 동시 호출을 거부한다.
응답 전 중단/transport 오류 후 동일 세션은 재전송하지 않는다. 저장된 응답은 비용 재발생
없이 검증할 수 있다. schema 오류/미완료 응답도 response/usage/error를 보존한다.
수동 반입 응답은 cryptographic provider 증명이 아니며 외부 기존 비용은 미확인으로 둔다.
로컬 intent 후 response 저장과 usage 저장 사이에서 중단된 경우에도 이미 시도한 1회를 보존한다.
소스·자산·의존성·근거를 호출 전후 검증하며 변경 시 거부한다.

선택 오류는 로봇 FAIL이 아니다. 기존 실행기의 조건 변경/인프라 제외, pending 수집과
명시적 resolve, 제외도 예산 소비, 완료 후 추가 실행 없음 규칙을 재사용한다. 제안·원본 이력·
새 실행 비용은 구분한다. 완료된 제안 세션에 다시 select를 해도 새 요청하지 않는다.

## 결과 보고와 후속 탐색

보고서에 원본과 신규 실행의 측면 값·목표 결과·호출 수·마지막 상태 표본 거리·행동 수·MP4를
나란히 표시한다. `paired_comparison.json`은 각 probe의 가설·반증 조건에 실제 전체 행동
요약을 연결한다. 가설 판정은 `NOT_ADJUDICATED`이며 LLM의 말이나 단일 FAIL을 원인 확정으로
바꾸지 않는다. 저장 표본의 거리/체류는 full-rate terminal 판정과 다를 수 있음을 표시한다.

세 번 완료 후 기존 `next`는 같은 조건의 혼합 결과 반복을 먼저, 관측 PASS/FAIL 구간이 있으면
미측정 중점과 기준 반복을, 없으면 다음 LLM 요청을 준비한다. 새 실행은 별도 승인/예산이며
자동 무한 탐색하지 않는다. 개발용 외부 이력은 기존 frozen benchmark arm에 넣지 않는다.

## 검증과 수정 기록

새 코드 작성 중 저장한 SceneGraph tuple이 JSON list로 바뀌어 직접 객체 비교가 실패하는
문제를 발견했다. canonical JSON 내용 hash로 비교하도록 수정했다. 변조된 근거·목표는
여전히 거부하며, API에 hash를 계산시키거나 stale context를 임의로 교정하지 않는다.

첫 주요 회귀 묶음은 새 선택·기존 대조·회귀·v4 캠페인 66개 테스트를 통과했다.
합성 API/합성 로봇 테스트에서는 한 번 제안 후 세 시도, 고정 예산, PASS/PASS/FAIL과
후속 0.375 중점 선택을 확인했다. 이 값과 결과는 테스트 입력이며 실제 Luna/G1 결과가 아니다.
정적 no_path 후보 허용·CLI 호출·기존 행동 메모리/요청 테스트를 추가한 최종 묶음은
**134 passed in 52.80s**였다. Ruff 정적 검사·포맷과 `git diff --check`도 통과했다.

실제 `prepare-pair` CLI로 다음 새 세션을 저장했다.
`/workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002`
상태는 PREPARED, calls_attempted=0이다. context/request/history/protocol과 SQLite가 있으며
아직 response·후보 값·로봇 suite·새 MP4는 없다. 성공 기준의 입력·환경을 준비했다는 뜻이지
LLM 제안이나 로봇 실험이 완료됐다는 뜻이 아니다. 다음 명령은 문서의 `select-pair --live`다.

실제 원본 검증은 읽기 전용이며 신규 실패 발견·경계·밀기·복구·네 번째 유형 검증이 아니다.
공식 operational 규칙은 계속 세 개이며 4/6 coverage/Gain 달성을 주장하지 않는다.

## 문서와 참고

[실행 안내](../scene2test/docs/AFS_PAIRED_GOAL_CONTRASTS.md)에 복사 가능한 준비·제안·실행 명령을
기록했다. README와 로드맵을 함께 갱신한다. OpenAI Docs 스킬로
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)를 확인하고,
기존 strict JSON schema 요청 위에 수치·근거·실험 설계의 의미 검증을 추가했다.
write-page 스킬을 사용해 관측 사실, 제안 가설, 실제 실행 전 상태를 구분해 기록했다.
키·원본 실험·로봇 정책은 수정하지 않았고 commit/push는 하지 않았다.
