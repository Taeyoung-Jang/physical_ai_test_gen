# 중복 후보 진단과 고정 예산 재제안

## 발생한 문제

사용자 실행 세션 `/workspace/g1_failure/runtime/afs_autonomous/20261018T075715_819920Z`는
첫 AFS 응답 검증에서 중단되었다. 모델은 PASS 기준 장면의 두 번째 장애물 위치 비율을
`.7→-.7`로 제안했지만, 이는 기존 성공 환경20개 축과 정확히 일치했다. 변화량은 전체
범위의70%여서 최소10% 조건에는 충분했고, 당시 축 cooldown도 없었다.
직접 원인은 이미 관찰한 환경을 새 가설로 제안한 것이다.

중복 일치 case ID는 `5bdb9fe0948d7d09311e94d3854aab650f567e0c31ba322623b9d61944258968`,
선택한 PASS 기준은 `a315a95234aad6214e1c77e7b7ecf0a014719d1159116573035d34c9726bfe92`였다.
호스트는 정상 거절했지만 일반 ValueError만 보고하고 탐색 전체가 중단되었다.
세션은 NEEDS_ATTENTION, pending proposal0, 로봇 시도0, AFS1요청이다.
관측 비용은62945 input/1534 output tokens다. 로봇 실패나 신규 유형 발견이 아니다.

## 승인된 개선과 변경

사용자가 제안 회피·대안 후보·고정 호출 예산 내 재제안 개선을 승인했다.

- `SearchBudget.reproposal_policy`를 추가했다. 기본 `stop`으로 기존 모드를 보존하고,
  `bounded-rejection-v1`은 failure-branch-v3에서만 명시적으로 허용한다.
  `afs_failure_branch_luna.json`에 이를 켰으며 최대8 AFS요청/8시도/유효6개 목표는 그대로다.
- 기준별로 한 축만 바꾸어 기존 환경을 만드는 금지 조합을
  `observed_single_axis_endpoints`에 명시한다. 이는 이미 case_memory에 있던 장면 정보이며
  상세 행동 근거를 허위 추가하지 않는다. 요청은 대안2~4개를 권하지만 단일 유효 후보도
  수용한다. 한 응답에서 실행할 후보는 최대1개다.
- `NoEligibleEndpoint`는 공통 스키마·범위·근거·역할 검증이 끝났으나 후보 조건으로
  모두 거절된 경우만 나타내는 별도 ValueError 하위 타입이다. 후보별 축·값·기준값·기준 ID·
  거절 사유와 중복 case ID를 기록한다. 유효 후보가 함께 있으면 추가 호출 없이 선택한다.
- 명시 정책에서만 전체 거절을 `rejection.json` 및 해시·DB 이벤트로 저장하고 pending을
  해제한다. 다음 요청에 최근4개 거절 이유와 남은 호출 예산을 전달한다.
- 거절마다 AFS1요청 비용을 소비하고 로봇 시도/결과는 만들지 않는다. 전체 AFS 상한에서
  명시 중단한다. Random 대체·최소 변화 완화·축 쿼터 초기화·자동 예산 증가가 없다.
- API/transport/schema/ref/역할/stale context/해시 오류는 계속 중단한다. 같은 요청의
  자동 재전송이 아니라 완료된 거절에 대한 새 가설 요청만 허용한다.
- pending 응답과 선택된 후보가 자기 요청 context를 바꾸지 않도록, 피드백 잔여 예산은
  확정 거절과 실제 dispatch된 이전 제안만 반영한다. 저장 응답·원본 해시·whole-request
  semantic 비교와 실행 직전 후보 재검증은 유지한다.
- summary에 거절 수·잔여 요청 수를 추가했다. proposals.json, rejection.json, HTML에
  전체 거절을 남기고 부분 거절 후 선택한 후보의 selection_audit도 HTML로 제공한다.

## 실제 저장 응답의 오프라인 재현

기존 세션의 context/response 및 원래5개 이력을 읽어 새 진단 타입으로 동일 거절을
재현했다. 사유는 `already_observed`, 값-.7, 기준값.7, 일치 case는 위 기존 PASS다.
세션 파일218개를 검사 전후 SHA256 비교하여 모두 동일함을 확인했다.
DB 열기·업데이트, recovery fork, 새 세션, API·로봇 실행은 하지 않았다.

## 검증

신규 재제안10개와 분기14개 테스트24개가 통과했다. 완료 거절 후 신규 요청, 정확한 이유
전달·비용 합산, 한 응답 내 대안 선택, 요청 상한 중단, 오류의 재제안 금지, 구 stop 정책,
응답 저장 후 중단·거절 확정 후 중단의 재개, 거절 파일 tamper 거절, 정책 범위를 검사했다.
전체 관련 CPU/synthetic 회귀 테스트212개가50.47초에 통과했다. 실제 성공2개·실패3개
이력을 이용한 무상 plan도 통과했다. human-v5, 조건
`e8ec811981448476f029536ee0b49be2fcad786c53d86edc3a5ba5105813bd5b`,
Luna/로봇10호출/push/dwell/HTTP300초를 유지하고 새 재제안 정책을 확인했다.
plan은 디렉터리·세션·DB·API·로봇을 생성하지 않는다.
Ruff 및 format 검사, git diff 검사도 통과했다.

OpenAI Docs 스킬로 공식 Structured Outputs 문서를 확인했다. 형식 계약과 환경 신규성
검증을 분리하며, 새 정책은 서비스의 구조화 출력이 환경의 새로움까지 보증한다고 가정하지
않는다. 문서 작성 스킬 지침에 따라 이번 작업 내역과 실행 범위를 기존 저장소에 기록했다.
공식 참조: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

## 실행과 제한

같은 설정 경로의 새 코드로 실행하면 새 재제안 정책을 쓴다. 기존 실패 세션은 원본 그대로
보존하며 source drift 검사를 우회해 이어가지 않는다. 문서의 run 명령은 새 예산 세션을
시작한다. 이전 세션 AFS1요청에 새8요청을 더하면 개발 세션 합계 상한은9요청이다.
이는 이전 비용·예산을 지우거나 기존 세션 상한을 늘린 것이 아니다.

로봇/모델/목표/완료/분류기/임계값은 바꾸지 않았다. 새 정책의 실제 탐색 품질은
유료 실행 전이므로 아직 검증하지 않았다. 실패율30%·4종 발견·Gain 달성 실적은 없다.
이번 구현에서는 유료 API·GPU·로봇·새 runtime 출력·기존 판정 수정·commit/push를 하지 않았다.
