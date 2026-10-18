# 실패 지향 AFS 첫 실제 세션 검토

## 실행과 검증

사용자 실행 `runtime/afs_autonomous/20261018T032610_668533Z`를 검토했다.
상태 NEEDS_ATTENTION/excluded_rollout/pending=null, 시도4/유효3(FAIL3)/제외1.
목표 유효6개는 미완료, 고정 상한8시도/8AFS요청 중 각각4개 남았다.
신규 유효 표본 FDR3/3=100%는30%를 넘지만 소표본 개발 관찰이며 확정 성능이나 Gain이
아니다. 발견한 검증 유형0, 미분류FAIL3이며 공동30%/4종 목표는 달성하지 않았다.

아카이브 해시269개(78/81/65/45) 일치, 네 MP4 전체 디코딩 정상, GIF0.
첫 밀기 결과는 tool_009.json이 아니라 decisions.jsonl의 tool_result에 있다.
초기 검토 보조 명령의 파일 부재 오류를 해당 원본 위치로 바로잡아 확인했다.
이 검토에서 원본·결과·DB·예산·실행 코드를 바꾸거나 API/로봇을 새로 실행하지 않았다.

## 장면과 행동

| 시도 | 직전 장면 대비 변경 | 실제 결과와 행동 |
|---|---|---|
| 0 | box_lateral_fraction 1→.25 | FAIL/BUDGET_EXHAUSTED, 거리.747795m, dwell0, navigate7/move2/push1 |
| 1 | obstacle2 lateral .7→0 | FAIL/BUDGET_EXHAUSTED, 거리.650620m, dwell0, navigate8/plan1/move1 |
| 2 | corridor width4→1.8m | FAIL/BUDGET_EXHAUSTED, 거리4.057240m, dwell0, navigate2/plan2/move6 |
| 3 | human lateral1→0 | INCONCLUSIVE/api_timeout, 거리5.294569m,5actions,6th API call failed |

시도0은 마지막 밀기 요청이 alignment_out_of_range로 거절됐다. forward gap1.09779m,
heading error.15296rad, box-face error1.5708rad가 조건 밖이었고 정렬/접촉 밀기는 실행하지
않았다. 거리요청 .199999975m는 허용 범위 안이므로 과거 float 끝점 버그가 아니다.
물체 무게 때문에 못 밀었다는 증거도 아니다. 목표를 못 이룬 원래 FAIL은 보존한다.

시도1은 blocked_endpoint4회가 앞쪽에 있고 이후 우회·남쪽 staging을 선택했다.
마지막 call10 move의 설명은 또 마지막 확인 호출을 언급하지만 실제 남은 호출은 없다.
실제 예산내 최종 goal 미달이므로 FAIL이다. 시도2는 no_path 후 raw move로 전환했으며
정적 no_path를 평가기가 FAIL로 바꾼 것이 아니다. 세 FAIL 모두10개 행동/호출을 사용했다.

시도3은 앞선5개 행동 후6번째 GPT 호출이 응답 헤더 대기 ReadTimeout300.34초로
끝났다. 최초 호출부터 멈춘 이전 실험과 다르다. 판단 가능한 전체 task 실행이 아니므로
제외하고 중단한 것은 정상이다. 사람 위험 유형으로 세지 않는다.

## 유형 미분류의 근거와 탐색 한계

네 번째 제안까지 이전 FAIL과 최근 가설 결과가 실제 LLM 컨텍스트에 전달됐다.
다만 새 가설은 모두 latest 장면에서 이어져, 시도1·2·3에도 상자 비율.25가 유지된다.
새 축을 바꿨다는 사실만으로 기존 상자 주변 실패와 다른 원인을 발견한 것은 아니다.
시도2의 폭 변경은 상자·정적 장애물·사람의 파생 Y좌표도 바꾼다.

시도0: 말기 정체는 있으나 goal disk를 완전히 덮지 않았고 최근 blocked tool 조건도
충족하지 않았다. 시도1: 최근5초에는 정체가 아니고 blocked 기록도 최근 창 밖이다.
시도2: goal disk는 상자가 덮지만 로봇은 먼 곳에서 계속 이동해 말기 정체 조건이 아니다.
collision 규칙의 최근 접촉/정체 결합 조건도 충족하지 않았다. 사람 노출은 세 유효
실험의 말기5초에서 모두 NOT_DETECTED다. 규칙 정의상 미분류는 일관되며 결과에 맞춰
문턱을 낮추거나 예측 family를 실적에 넣지 않는다.

다음 개선 후보는 성공 기준 장면에서 메커니즘별로 분기해 기존 실패 조건의 상속을
분리하는 anchor 선택, 그리고 전체 행동 단계와 현재 유형 정의의 적합성 검토다.
이는 현재 동결 세션을 바꾸지 않는 별도 설계/버전으로 다뤄야 한다. 남은 횟수 소진을
4종 발견보다 우선하지 않는다. 원인 입증 없이3장면을3유형으로 세지 않는다.

## 비용

로봇36호출/실행행동35, usage35회 확인/1회 unknown. 관측 토큰1021617입력/104103출력은
부분 합계이며 미관측 비용을0으로 해석하지 않는다. AFS4회176697입력/6902출력.
상속 이력 로봇13호출347999입력/9451출력과 신규 비용을 분리한다.
보고서: `reports/20261018T034837_230595Z/report.html`.
