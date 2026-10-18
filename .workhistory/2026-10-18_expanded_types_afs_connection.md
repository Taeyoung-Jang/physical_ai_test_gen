# 확장 10종 측정과 AFS 환경 선택 연결

## 요청과 구현 범위

사용자가 사후 분류에 추가한10종을 실제 AFS 선택에도 연결하도록 요청했다.
입력 이력 재분류→선택 요청→호스트 검증→실행 결과 재분류→다음 요청→신규 지표를
한 프로필로 연결했다. 실제 새 로봇·API 실행은 포함하지 않았다.

## 변경 사항

- `SearchBudget.taxonomy_profile`을 추가했다. 기본 `scene-default`로 기존6종 계약을
  유지하고 `expanded-ten-v1`은 failure-branch-v3에서만 명시적으로 허용한다.
- `evaluation/taxonomy_profiles.py`로 이력·신규 결과의 classifier와 metric registry/inventory를
  공유한다. 같은 새 세션에서 사후10종과 신규6종을 섞지 않는다.
- `development_plan` 입력 이력과 `_observe`의 새 VALID 결과가 선택한 프로필을 쓴다.
  원본 로봇 아카이브를 바꾸지 않고 세션 내부 파생 record에만 분류를 저장한다.
- `failure_objective`는 새 모드에서10종 지표로 실제 발견 유형을 계산한다. 보여 준
  에피소드마다 실제 primary, 보조 진단, 상태, 체류·넘어짐·조작·실행 정체 근거를 전달한다.
- 기존 선택 순위가 미발견 지원 유형·해당 유형의 시도 수를 사용하도록 새 결과를 연결했다.
  동일 의도에서 관측한 goal_completion_failure와 미관측 fall을 비교하면 후자를 우선한다.
  목표별 강제 쿼터나 특정 동작 강제, 실제 실패 가능성 보장은 추가하지 않았다.
- 새 ExpandedBranchPoint/Proposal을 추가해4개 신규 target_family를 받는다. 구 FailurePoint와
  BranchPoint는 기존 enum을 유지한다. 요청 JSON schema와 호스트가 같은 새 계약을 사용한다.
- 새 프롬프트는 대표1개 집계, 예측/측정 분리, 조작 거절과 힘 부족의 구분, 실제 실행과
  대기의 구분, 목표 체류 부족과 일반 예산 종료의 구분을 명시한다. 미지원 도달 불가·
  인식 오류는 여전히 목표로 허용하지 않는다. support와 discovery는 다르다.
- 새 `afs_expanded_ten_luna.json`: Luna/HTTP300초, 유효6개 목표/최대8시도·AFS8요청,
  축별2회/반복0/최소10%/history_limit4/제한된 재제안을 유지한다. 기존 branch 설정은
  수정하지 않았다. 로봇10호출 기준 최대80회다.
- summary의 신규 실험 지표도 활성10종 inventory를 사용한다. warm history는 신규 유효
  목표나 분모에 들어가지 않으며, 입력 비용·신규 로봇 비용·AFS 선택 비용은 분리한다.
  예측 목표가 실제 발견 라벨을 만들지 않으며 다음 요청의 예측/관측 결과는 별도다.

## 자동 검증

신규7개 테스트와 기존 관련 검증을 포함해230개 CPU/synthetic 테스트가51.20초에 통과했다.
초기 집중38개도 통과했다. 새4개 목표의 schema/host 일치, old mode 거절, unsupported
유형 거절, 실측 유형 우선순위, import/observe/summary/resume의 같은 프로필, 예측 fall과
관측 goal_completion_failure의 분리를 검사했다. 테스트용 detector 결과는 wiring fixture이며
실제 로봇 성능 근거가 아니다. Ruff/format 및 diff 검사도 수행했다.

OpenAI Docs 스킬로 [공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)를 확인했다.
필수 필드·추가 필드 금지·동일 enum을 유지하고 내용 판정은 호스트에서 수행한다.
문서 작성 스킬 지침으로 기존 안내의 미연결 상태를 갱신하고 실행 범위와 한계를 기록했다.

## 실제 저장 이력 오프라인 검증

입력은 완료 세션 `20261018T081720_637822Z`의 신규6개 rollout이다. CLI plan은
human-v5, 조건 `e8ec811981448476f029536ee0b49be2fcad786c53d86edc3a5ba5105813bd5b`,
Luna/10호출/push/dwell/HTTP300초를 유지한 채 새 프로필로 통과했다.
plan은 세션 디렉터리·DB·로봇·API를 생성하지 않았다.

앞선 실제 재분석6개 episode를 사용해 메모리와 새 요청도 구성했다. 측정된 대표는
goal_completion_failure1종, 미발견 지원 유형은 collision/obstacle_interference/goal_occupied/
human_safety_risk/fall/locomotion_stall/manipulation_failure의7종이다.
지원 규칙은8개이고 inventory는10종, 도달 불가·인식 오류는 미지원 상태다.

수동 검증 후보2개를 동일 PASS 기준에서 만들었다. floor friction .05를 관측된
goal_completion_failure 목표로, box mass10을 미발견 fall 목표로 제시했을 때 후자가
호스트 순위로 선택됐다. JSON schema와 host 검증이 통과했다. 이는 LLM 제안이나 로봇이
넘어졌다는 결과가 아닌 오프라인 계약 검증이다. 이때 요청 JSON은202219 UTF-8 bytes였으며
토큰 수·과금·wire capture로 해석하지 않는다. 입력6개여도 남은 신규 유효 목표는6개다.

## 인계와 제한

`scene2test/docs/AFS_EXPANDED_TEN.md`에 무료 plan과 새 유료 run 명령을 저장했고
기존10종 안내와 README도 갱신했다. 다음 실제 실행은 새 설정의 별도 예산 세션이다.
이미 완료된 세션의 남은 슬롯을 소모하거나 source drift를 우회해 재개하지 않는다.
이번 모드는 외부 이력을 쓴 개발 탐색이며 독립 Random 비교나 Gain 평가가 아니다.

실제 새 모드의 실패율·유형 다양성 향상은 아직 관측하지 않았다. 단일 대표 집계에서
4종에는 최소4개 실패 장면이 필요하며6개 유효 실험이4종 달성을 보장하지 않는다.
기존6종 결과·10종 사후 보고서·로봇·목표·완료 평가·분류 임계값·모델·예산은 유지했다.
새 유료 API·GPU·로봇·시뮬레이션·runtime 세션 생성, 원본 DB/판정 변경, commit/push는 없다.
출력 토큰 상한·암묵적 시뮬레이션 제한·GIF도 추가하지 않았다.
