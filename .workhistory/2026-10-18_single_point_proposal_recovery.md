# 단일 값 환경 제안과 동일 끝점 응답 복구

## 원인과 승인 범위

사용자 실행 20261018T014205_556509Z의 첫 Luna 응답은 사람 모형 측면 비율을
low=high=0.0으로 제안했다. 0.0은 승인된 [-1,1] 안이지만 기존 범위 계약의 low<high를
어겼다. AFS 1회 완료(입력19067/출력1162토큰), 로봇0회 상태로 중단되었다.
context/request/response 해시3개는 일치했다. 이 문제는 실험 중 장면 변경이나
로봇의 goal FAIL이 아니다. 사용자는 단일 값 지원과 원본 보존 명시적 복구에 승인했다.

## 코드와 실행 경계

자율 탐색 전용 EndpointProposal에 PointSpace(axis/value)를 추가했다. 기존 Space
범위와 Proposal 계약은 다른 도구에서 유지했다. 두 형식 모두 동일한 근거·축·도메인·
쿼터·cooldown·최소10% 변화·중복 필터로 선택한다. 잘못된 값은 클리핑하지 않는다.
범위 오류 메시지는 실제 축·제안 값·허용 범위·형식 요구를 표시한다.

OpenAI Docs 스킬의 공식 Structured Outputs 지침을 확인해 루트 객체, 중첩 anyOf,
required 전체 필드, additionalProperties=false를 유지했다. 요청 프롬프트에는 단일
값을 기본으로 제안하고 환경은 회차 시작 전 확정하며 AFS가 실행 중 개입하지 않는다고
명시했다. 근거: https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses

point_recovery.py와 recover-point CLI는 기본 dry-run이며 --apply만 새 세션을 만든다.
원본 OS 잠금 아래 DB/WAL을 임시 복사해 checkpoint/ledger/protocol을 검증한다.
첫 제안1회·로봇0회·완료 응답만 허용하고, 원본 파일/컨텍스트/사용량/환경을 검증한다.
허용된 AFS 계약 변경 외 로봇·리소스·런타임 변화는 거절한다. 현재 컨텍스트가 원본과
같아야 하므로 hash 재바인딩은 하지 않는다. 동일 끝점만 같은 값의 단일 제안으로
변환하고 나머지 근거·가설·수치는 보존한다.

새 폴더에 원본 세 파일을 바이트 그대로 복사하고 normalized_proposal.json 및
recovery.json을 별도로 기록한다. 감사 해시를 세션 lock에 고정하고, 실행 직전 원본
응답에서 재변환한 결과와 비교한다. 원본 세션·예산·유료 호출 비용은 변경하지 않는다.
새 세션에도 사용한 AFS1회를 포함하므로 최대 새 요청7회만 남는다. 첫 후보 실행에는
추가 AFS 호출이 없다. 실행은 별도 --live 명령이며 이번 작업에서 로봇을 실행하지 않는다.

## 검증

단일 값 스키마·허용 범위·비유한 값·혼합 필드·근거·컨텍스트·최소 변화·중복·쿼터를
검사했다. 합성 복구는 dry-run 무생성, 원본 전체 파일 해시 불변, 비용/예산 보존,
추가 제안 호출 없는 첫 실행, 재개 무중복, 변환 파일 변경 거절과 원본 잠금 충돌을
확인했다. 초기 테스트 오류 두 건은 예상 오류문구 차이와 테스트 import 누락이었고
수정 후 단일 값/복구 테스트15개가 통과했다. 기존 자율 탐색32개도 통과했다.
최종 통합 검사 및 실제 복구 적용 결과는 아래에 추가한다.

최종 통합 회귀 **261 passed in 84.31s**. Ruff check, format --check(8파일),
git diff --check 통과. 기존 범위 도구·자율 재개·사람 측정·공동 발견 지표를 함께 검증했다.

실제 오프라인 복구 폴더:
`/workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery`.
상태 READY/pending=null/로봇시도0, 저장 후보 human_lateral_fraction=0.0.
현재 소스/리소스 검증과 실행 직전 후보 재계산이 MATCH였다. 원본55개 파일의 해시는
복구 전후 모두 동일했다. 원본 요청·응답·컨텍스트는 복구 폴더에도 바이트 그대로 보존했다.
사용한 AFS1회/19067입력/1162출력을 유지하므로 새 AFS 요청은 최대7회 남는다.
추가 API0/로봇0, 원본 DB/결과/예산 수정0, commit/push0.
보고서: `reports/20261018T022334_149784Z/report.html`.
별도 실행은 `run_afs_autonomous.py run --live --session <위 복구 폴더>`를 사용한다.
