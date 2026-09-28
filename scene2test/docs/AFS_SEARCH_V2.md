# 행동 근거·가설 중심 AFS 선택 v2

2026-09-28 UTC. 로봇 제어 개선이 아니라 **AFS 입력/선택/측정 개선**이다.
적용 경로는 `run_afs_pilot.py` / `run_afs_benchmark.py`의 로컬 campaign이다.
로봇 모델·프롬프트·제어기·목표·episode 예산·Random 분포를 바꾸지 않는다.
GIF를 다시 만들지 않으며 원본 rollout을 수정하지 않는다.

## 변경 요약

| 문제 | 새 동작 |
|---|---|
| 시간순 앞12개 구간만 전달해 후반 실패/회복 누락 | episode 전체 action_timeline + 중요 상세 구간 최대12개 |
| 발–바닥 접촉 횟수 차이가 다른 실패 서명이 됨 | 도구 상태 전환·진척·물체 변위 등의 버전된 행동 패턴 |
| 파라미터상 가장 먼 후보가 무조건 우선 | 실험 목적 → LLM 가설 순서 → 같은 가설 내 endpoint novelty |
| 혼합 PASS/FAIL 장면에도 경계를 좁히려 함 | boundary 슬롯에서 mixed case 반복을 우선 |
| FDR만으로 탐색 진척을 읽기 어려움 | 첫 성공/관측 bracket, 반복 패턴, 가설별 결과·비용 보조 보고 |

## 1. 행동 근거 선택

`search_evidence.compact_evidence`는 기록된 모든 행동(현재 episode 최대20회)의 관측 시간창,
tool 결과, 목표/명령 인자, 원본 해시/행 참조를 요약한다. 정확한 실행 시작 시각을 지어내지 않는다.
상세 구간은 초기/종료, 사건 종류별 최근 대표, tool 오류와 후속 행동, 진척이 가장 작거나
큰 실행 phase, 나머지 시간대 대표를 선택한다. 발–바닥 지지 접촉은 상세 선택에서 제외한다.

`evidence_selection`에 선택 인덱스/이유, 전체·선택 건수, 누락 상세 수를 남긴다.
전체 원본은 보존한다. 후속 move가 있다는 사실을 자동으로 "회복 성공"이라고 판정하지 않는다.
분석 구성 요소가 없거나 손상되면 AVAILABLE로 꾸미지 않고 기존 상태/경고를 전달한다.
이 제한은 구간 수 한도이지 모델 token 한도의 보장은 아니다. 요청 JSON의 UTF-8 bytes를
따로 기록하며 이것을 token 수나 청구 비용으로 변환하지 않는다.

실제 Luna 통로 archive를 오프라인 확인한 결과, 이전에는31개 적격 구간 중 앞12개,
행동4개만 상세 전달됐다. 새 입력에는10개 행동 전체와 후반 경로 거부2회,
후퇴·측방 move가 포함된다. 이는 API가 새 입력으로 더 좋은 제안을 했다는 증거는 아니다.

## 2. 행동 패턴과 cooldown

`behavior-pattern-v1`은 연속 중복을 합친 action/tool-status/reason 순서,
유효 사건 종류/접촉 대상, 마지막 목표 거리·진척(0.5m bin), 상자 XY 변위(0.1m bin)를 쓴다.
물체 측정/사건 availability도 포함한다. states/actions가 없으면 패턴 ID는 null이다.
기존 정확한 발–바닥 접촉 횟수는 서명에서 제외한다.

같은 robot/task/budget 조건에서 최신 FAIL과 같은 패턴이 정규화 최대축 거리0.05 이내에
3회 이상 있으면 그 이웃의 새 endpoint를 cooldown한다. 동일 장면 중복은 별도로 거른다.
반복 확인과 실제 관측 bracket 중점은 이 필터로 막지 않는다.
이는 경계값에서 달라질 수 있는 거친 유사성 휴리스틱이며 causal detector가 아니다.
공식6종 failure coverage는 계속 미측정이다.

## 3. 가설 중심 선택과 상태별 처리

새 캠페인의 `selection_policy` 기본값은 `hypothesis-v2`다.
기존 `spaces` 출력 schema는 그대로 사용하고 모델/endpoint/추론 설정은 유지한다.
실행 가능한 축/범위/증거 ID/context hash 검증도 유지한다.

1. 비교 가능한 PASS가 없으면 success_probe를 먼저, 다음 cross_mechanism을 본다.
2. 유사 근방 실패가3회 이상이면 cross_mechanism을 먼저 본다.
3. 그 외 LLM 슬롯은 cross_mechanism을 우선한다. 실제 bracket 검사는 별도 boundary 슬롯이다.
4. 같은 목적이면 LLM의 spaces 배열 순서를 가설 우선순위로 사용한다.
5. 같은 space의 low/high 중 기존 관측과 최소 정규화 거리가 큰 endpoint 하나를 선택한다.
   동률이면 low를 먼저 택한다. 양 끝을 모두 실행하거나 성공 확률을 학습한 선택기는 아니다.

`selection_audit`에는 상태, 목적 우선순위, 최신 anchor case/episode ID, 선택 mode,
eligible 후보, 중복/cooldown 제외 사유, 후보 없는 mode, 선택 가설 ID를 저장한다.
가설 ID는 해당 context/space의 식별자다. 서로 다른 요청의 자유문 가설을 자동 병합하지 않는다.
LLM은 범위의 양끝 모두가 같은 질문을 시험하도록 제안하고 서로 다른 질문은 space를 나눈다.

고정된 llm/boundary/exploration/repeat 슬롯은 유지한다. 단 boundary 슬롯은
mixed case 반복 → 미실행 관측 bracket 중점 → 새 가설 요청 순서로 처리한다.
repeat 슬롯도 mixed case가 있으면 우선한다. 반복할 case는 현재 반복 수가 적은 것을 고른다.
독립 탐색/반복을 없애거나 자동 유료 재시도/Random fallback을 추가하지 않는다.
모든 cold start, 성공 probe, 반복은 기존 유효 rollout 예산을 소비한다.

`novelty-v1` 선택 시 endpoint 거리 우선 순위를 비교할 수 있다. 그러나 근거 요약·서명 등
공통 코드도 바뀌었으므로 **이 옵션이 옛 실행의 완전 재현을 의미하지 않는다**.
이번에는 anchor를 LLM이 임의 선택하는 새 출력 schema까지 확장하지 않았다.
단일 축은 최신 관측 장면에 적용한다. 과거 anchor 자유 선택·학습형 획득 함수는 후속이다.

## 4. 측정과 보고서

`--with-memory` 보고서 및 pilot 자동 보고서에 다음이 추가된다.

- `metrics.json.search_diagnostics`, `search_diagnostics.csv`, HTML 요약표/상세.
- arm/seed별 최초 관측 성공과 최초 관측 bracket까지 valid rollout/총 시도/관측된 로봇 비용.
- 현시점 bracket 양끝의 실제 PASS/FAIL 횟수, 폭, mixed cases, 예산별 변화 곡선.
- 실패 패턴의 관측 종류 수/반복 비율과 패턴을 측정할 수 없는 실패 수.
- campaign에서는 선택 가설·반증 조건과 실제 결과, anchor 대비 최종 목표 거리 차이를 연결.
  자유문 가설을 자동으로 지지/반증 또는 원인 확정하지 않으며 `NOT_AUTOMATICALLY_ADJUDICATED`다.

첫 관측 bracket은 나중에 혼합 반복이 생기면 사라질 수 있다. 최초 시점만 보고 확정 경계로
부르지 않는다. 파라미터 한 축의 관측 bracket이지 전 공간의 단조성/최소 실패 변화 증명이 아니다.
특히 비중앙 상자의 폭 변화는 실제 상자 Y도 바꾸는 기존 parameterization을 유지한다.

비용: manifest/계약이 유효한 INCONCLUSIVE archive에서도 기록된 decision usage를 보존한다.
그 결과를 목표 FAIL 학습에 넣지는 않는다. 잘못된 usage/누락은 null+경고다.
campaign summary는 robot_tokens, AFS request bytes와 기존 AFS tokens를 분리 보고한다.
실패했으나 응답 usage가 남지 않은 요청, 불완전 manifest의 사용량, 실제 청구금액은 여전히 미상이다.
오래된 campaign checkpoint의 누락 비용을 자동 덮어쓰지 않는다.

FDR/Gain 및6종 coverage 정의는 바꾸지 않는다. 양쪽 전부 FAIL이면 FDR100%여도 Gain0%다.
행동 패턴 종류가 늘어난 것을 공식 실패 유형 발견 수로 바꾸지 않는다.

## 5. 실행 — 새 캠페인 사용

코드/탐색 설정이 바뀌었으므로 과거 캠페인의 drift 검사를 끄거나 lock을 수정하지 않는다.
첫 제안의 근거 ID 누락은 [명시적 복구 절차](AFS_EVIDENCE_RECOVERY.md)로 별도
operator-assisted 캠페인에 계승할 수 있다. 원본/비용을 보존하며 정식 Gain 비교는 제한한다.
로봇 개선이나 별도 성공 실행을 강제 선행 조건으로 요구하지 않는다. 실패도 정상 탐색 근거다.
기존 수동 Luna 실행은 이번 입력 검증에만 사용했고 정식 캠페인에 무료 warm history로 넣지 않았다.

작업 디렉터리:

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

5축 Luna/Luna 캠페인 계획 확인 (파일 생성/API/GPU 실행 없음):

```bash
uv run --no-sync python tools/run_afs_pilot.py --config config/behavior_afs_corridor_luna.json
```

사용자가 예산 확인 후 실행할 유료 명령:

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --config config/behavior_afs_corridor_luna.json
```

AFS/Random 각각6회 유효/최대6회 시도, 로봇 최대120회 + AFS 최대2회 호출이다.
기존 API 키 설정을 사용한다. 위 숫자는 호출 수 상한이며 비용 상한이 아니다.
이번 구현 과정에서는 이 live 명령을 실행하지 않았다.

## 6. 검증 범위와 남은 작업

합성 archive/정책 double 테스트와 보관된 Luna archive의 오프라인 입력 검증만 실행한다.
실제 새 AFS 응답/로봇 성공률/Random 대비 우월성/요금 절감은 입증하지 않았다.
로봇 경로 추종 개선, 새로운 장면 축/점프, family detector, 회귀 실행기는 이번 범위 밖이다.

OpenAI Docs의 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
계약을 확인하고 기존 required 필드/추가 필드 금지/schema+host validation을 유지했다.
탐색 목적과 선택 순서는 프롬프트와 실제 host 로직에 함께 명시했다.
