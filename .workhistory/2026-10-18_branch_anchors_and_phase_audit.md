# 성공 기준 분기 AFS와 전체 행동 진단 구현

## 목적과 승인 범위

사용자가 최근 이슈와 다음 작업을 확인한 뒤 반영을 요청했다. 최신 실패 조건이 다음
후보에 누적되어 축만 다르고 같은 취약점에 머무를 수 있는 문제를 개선하고, 세 유효
실패가 미분류인 이유를 전체 행동과 현재 판정 계약을 비교해 기록한다.

목표 지표는 동일 목표·서로 다른 장면의 전체 유효 표본에서 FDR30% 이상과4종 이상
발견이다. 한 회차에서4종을 요구하지 않는다. Random 상대 Gain20%는 후속 과제다.
이번 변경은 개발 탐색과 진단이며 지표 달성 실적이 아니다.

## 변경 사항

1. 기존 v2와 legacy 계약을 보존하고 opt-in `failure-branch-v3`를 추가했다.
   `branch_anchors.py`는 제시된 실제 행동 근거가 있는 unmixed PASS/FAIL 장면만 허용한다.
   challenge/transfer는 PASS, relief는 FAIL을 사용한다. mixed/제외/미제시 기준은 거절한다.
2. `BranchPoint`/`BranchProposal`은 기준 ID와 이유를 필수로 받는다. 요청 스키마의 기준 ID는
   실제 catalog enum으로 제한하고, 근거·축·의도·유형 검증을 유지했다. 레거시 최신 장면
   기준 안내는 새 모드의 프롬프트에서 제거했다. 임의 기준 재설정이나 실행 중 변경은 없다.
3. 후보 생성·최소 변화량은 선택한 기준으로 계산한다. 기존 정확히 한 축 변경과 전체
   이력 중복 거절은 유지한다. 서로 다른 기준의 같은 숫자는 별도 제안으로 구분한다.
4. `branch_audit`로 기준·결과·실제 에피소드·이유·전후 값·나머지 값 검증을 저장한다.
   HTML과 다음 요청의 최근 예측 결과에도 전달한다. 기존 순위·예산·쿼터·cooldown을 유지한다.
5. `afs_failure_branch_luna.json`: Luna, 유효6개 목표/최대8시도·AFS8요청, 축별2회,
   자동 반복0회, 최소 변화10%, history_limit4, HTTP300초. 현재 로봇 최대80호출이다.
6. `tools/audit_failure_phases.py`는 선언된 아카이브 해시를 검증하고 전체 행동 구간과
   기존 taxonomy 측정·AND 조건을 JSON/HTML에 병기한다. 원래 판정·유형·임계값은 불변이며
   제외/누락 측정은 unknown으로 남긴다. 원본 내부 저장·기존 출력 덮어쓰기를 거절한다.

## 실제 이력 오프라인 검증

입력 성공 기록:

- `/workspace/g1_failure/runtime/robot_goal_agent/20261018T004636_410637Z`
- `/workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery/attempts/attempt_00001/rollout`

입력 실패는 `/workspace/g1_failure/runtime/afs_autonomous/20261018T032610_668533Z/attempts/`
아래 `attempt_00000`부터 `attempt_00002`까지의 rollout이다. 제외된3번은 기준에 넣지 않았다.

실제5개로 `plan` 통과: human-v5, robot Luna/10calls/push/dwell/HTTP300 유지,
조건 `e8ec811981448476f029536ee0b49be2fcad786c53d86edc3a5ba5105813bd5b`.
API·로봇·세션 디렉터리는 생성하지 않았다.

실제 이력을 바탕으로 요청 스키마와 후보 호스트 검증도 별도로 통과했다. 이는 수동 구성한
오프라인 검증 후보이지 LLM 제안이나 실험 결과가 아니다. 최신 상자 비율 `.25`에서
PASS 기준 비율 `1`을 선택하고 floor friction `.8→.05`를 시험하는 후보를 검증했으며,
생성 후보의 상자 비율은 `1`로 유지되어 기존 실패 조건의 자동 누적이 없었다.
catalog는 history_limit 안에서 실제 제시한4개 근거의 PASS1/FAIL3이었고,
요청 JSON 직렬화 크기는179745 UTF-8 bytes였다. 이는 토큰/과금/실제 전송 크기 추정이 아니다.

## 실제 실패 진단

진단 산출물:
`/workspace/g1_failure/runtime/failure_phase_audit/20261018T074329_464497Z/report.html`
및 동일 폴더 `audit.json`. 원래4개 rollout의 선언된 해시를 읽기 전용 검증했다.

| 회차 | 판정 | 전체 행동 | 주요 판정 조건 |
|---|---|---|---|
| 0 | VALID FAIL | navigate7/move2/push1 | stalled true, 전체 목표 점유 없음, 최근 막힘0 |
| 1 | VALID FAIL | plan1/navigate8/move1 | stalled false, 최근 막힘0 |
| 2 | VALID FAIL | navigate2/plan2/move6 | 전체 목표 점유 있으나 stalled false, 최근 막힘0 |
| 3 | INCONCLUSIVE | 유효 행동 측정 제외 | API timeout, FAIL 아님 |

세 실패의 기존 primary_family는 모두 null이다. 진단에 회차0의 과거 blocked_endpoint와
최종 rejected/alignment_out_of_range, 회차1의 과거4개 막힘, 회차2의 과거 blocked/no_path가
보존된다. 전체 행동의 과거 오류를 최근 시간창 오류로 바꾸지 않았다. 관찰된3/3 실패율과
미분류3개 상태는 그대로다. 새 유형을 넣거나 성공/실패 결과를 고쳐 쓰지 않았다.

## 자동 검증

관련 CPU/synthetic 회귀 테스트202개 통과. 신규 분기/진단17개를 포함한다.
PASS/FAIL 분기, 실제 인용, 잘못된 기준·혼합·미제시 기준 거절, 기준 상대 최소 변화,
중복, stale context, 필수 JSON 필드, 중단 후 저장 응답 재검증/추가 요청 없음,
HTML 감사 필드, 원본 불변·출력 덮어쓰기 금지·제외 unknown을 검사한다.
Ruff 및 diff 검사도 수행한다. 개발 중 첫 mock 응답에 assistant role이 누락되어1개
테스트가 실패했으나 테스트 fixture를 수정했고 최종 전체202개가 통과했다.
인터넷 중단으로 이전 프로세스의 최종 출력을 회수하지 못해 전체 CPU 테스트를 재실행했다.

## 인계와 남은 일

실행 설명은 `scene2test/docs/AFS_BRANCH_ANCHORS.md`, 최신 진입 링크는 루트 README에 있다.
기존 실패 지향/복구 세션은 보존한다. 새 코드로 소스 동결 검사를 우회하여 재개하지 않는다.
다음 실제 검증은 새 설정·별도 예산의 bounded 개발 세션이다. 지표 평가 전에 유형 계약을
확대할 필요가 있는지는 이번 전체 행동 근거로 별도 검토해야 한다. 현재4개 규칙 지원이
실제4종 발견을 의미하지 않으며, 이번에는 분류기를 느슨하게 만들지 않았다.

유료 API·GPU·로봇 실행, 기존 DB/아카이브/예산/판정 변경, commit/push는 수행하지 않았다.
새 무상 진단 파일만 runtime 아래 생성했다. GIF·출력 토큰 상한·암묵적 simulation cap은 없다.
