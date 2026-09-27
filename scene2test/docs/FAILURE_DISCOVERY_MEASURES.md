# 실패 발견 측정기 — P0 첫 구현

2026-09-26 UTC. [전체 계획](FAILURE_CASE_MEASUREMENT_PLAN.md)의 P0 측정 모듈과 최소 trace reader.
기존 goal-agent 기록을 읽는 **오프라인 도구**다. 로봇/GPU/유료 API를 실행하지 않으며 원본을 수정하지 않는다.
6종 실패 원인 detector와 회귀 실행기는 아직 구현하지 않았다.
후속 [P2 로컬 3축 캠페인](BEHAVIOR_AFS_CAMPAIGN.md)의 첫 구현은 별도 opt-in CLI다.

2026-09-27: `--with-memory`로 [P1 행동 시간선·failure memory](BEHAVIOR_FAILURE_MEMORY.md)를
추가할 수 있다. 원본 근거/재실행 조건과 성공·실패 반복을 보관하며, 기본 P0 측정 의미는 바꾸지 않는다.

## 실행 명령

`scene2test` 디렉터리에서 실행한다. API key는 필요 없다. 이미 설치된 환경에서는
`--no-sync`로 의존성 재설치를 생략할 수 있다.

최근 실행 기록 한 건을 점검하는 실제 명령:

```bash
uv run --no-sync python tools/measure_failure_discovery.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T151327_858717Z
```

이 기록은 manifest가 없어 유효 표본에서 제외된다. 이를 확인하는 것도 측정 결과이며,
실패율 0% 또는 로봇 FAIL을 의미하지 않는다. 완결된 새 실행은 `--run`에 그 폴더를 지정한다.
여러 건은 `--run`을 반복한다.

```bash
uv run --no-sync python tools/measure_failure_discovery.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T151327_858717Z --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T130019_070486Z
```

기본 저장 위치는 `/workspace/g1_failure/runtime/failure_measures/<UTC timestamp>/`다.
`--output-dir`로 **새 폴더**를 지정할 수 있지만 기존 폴더와 원본 run 내부에는 쓰지 않는다.
종료 코드 0은 보고서 생성 성공이지 유효 표본 확보나 연구 목표 달성을 뜻하지 않는다.
입력 계약 오류·상충하는 중복 기록·출력 경로 오류는 코드 2로 종료한다.

## 산출물과 해석

| 파일 | 내용 |
|---|---|
| `report.html` | 표본/예산/실패율, 비교 가능 여부, 제외 사유, 해석 제한 |
| `metrics.json` | method·seed별/전체 집계, 입력 순서별 누적 곡선, 중복/비용/coverage 상태 |
| `metrics.csv` | method·seed별 평면 요약표 |
| `episodes.jsonl` | 실행별 검증 상태, 원본 해시, 비교 조건 ID, 최소 행동 측정값 |
| `manifest.json` | 이번 보고서 산출물 해시 |

- FDR = 유효 FAIL / 유효 PASS+FAIL. 유효 표본 0개면 `null`이다.
- Gain = `(FDR_AFS - FDR_Random) / FDR_Random`. Random 실패 0개면 `baseline_zero`, 값은 `null`이다.
- Diversity는 고정 6종 분모와 검증된 detector registry를 사용하는 계산 함수를 구현했다.
  **현재 goal-agent importer에는 detector가 없으므로 실제 보고서는 `not_measured/null/UNSUPPORTED`다.**
  합성 단위 테스트의 4/6 계산 성공은 실제 로봇에서 4종을 찾았다는 증거가 아니다.
- `*_target_observed`는 해당 표본의 점추정이다. 통계적 우월성/재현성 검증 완료를 뜻하지 않는다.
- 같은 조건의 독립 반복도 예산에 포함한다. 고유 장면 수와 동일 장면의 반복 실패 수를 병기한다.
  고유 장면은 revision+XML 해시 기준이며 고유 실패 메커니즘 수가 아니다.
- `pooled_by_method`의 유형 합집합은 전체 seed의 총 예산 결과다. seed 하나의 예산과 비교하지 않는다.
- 모델/API 토큰은 decision에 기록된 부분만 집계하며 미수집 건수를 함께 표시한다.
  pending/실패 호출의 토큰, 전체 wall time, AFS 제안 비용은 이 importer로 완전히 측정하지 못한다.
- GIF나 새 MP4는 생성하지 않는다. 원본 실행의 미디어는 그대로 보존한다.

## 기록 검증과 최소 행동 측정

`robot-goal-agent-v5` + `goal_outcome_v1`만 공식 목표 표본으로 수용한다.
manifest의 모든 선언 파일 해시/경로를 검증하고 protocol/result/scene/states/decisions를 요구한다.
목표 계약, robot condition, scene revision, 종료 주체/이유, valid/goal/success 플래그 일치를 검사한다.
기록된 API 호출 수와 (존재하면) 전체 정책 호출 수가 선언된 `max_calls`를 초과하면
`INVALID / episode_call_budget_exceeded`로 제외한다. API 호출 수가 전체 정책 호출 수보다
많은 경우도 `inconsistent_policy_call_counts`로 제외한다. 원본의 목표 달성 여부는 수정하지 않으며,
예산 위반 결과를 정상 PASS/FAIL 표본으로 세지 않는다. 전체 정책 호출 수 필드가 없는 기록에서는
그 값을 0으로 만들거나 추정하지 않고, 확인 가능한 API 호출 수 상한만 검사한다.
잘못된 JSON, 중복 JSON key, NaN/Inf, 역행 시간, 빈 상태열 등은 INVALID로 남긴다.
구형 guard 결과는 UNSUPPORTED, API/수치 중단은 INCONCLUSIVE, 파일 누락은 INCOMPLETE다.
manifest는 trusted-local 무결성 확인이지 외부 작성자의 진위를 인증하는 서명이 아니다.

기존 run에는 영속 실행 UUID가 없으므로 핵심 증거 파일 내용으로 ID를 만든다.
복사본은 한 번만 세며, 완전히 같은 내용의 독립 재실행도 구별할 수 없으면 보수적으로 중복 처리한다.
같은 증거를 두 method/seed에 할당하거나 결과를 다르게 제출하면 오류로 거부한다.

최소 행동 측정은 샘플 기준 초기/최소/최종 목표 거리, 거리 진척, XY 이동거리,
기록된 최대 goal dwell, 최저 base 높이, 최대 기울기, 수락 행동 횟수, 사건 종류별 기록 수다.
사건 로그가 없으면 `null`이지 사건 0회가 아니다. 기울기를 안정성 여유/near-fall 판정으로 사용하지 않는다.
최종 목표 verdict는 고주파 평가기의 기록을 읽고, 20Hz 상태 샘플로 전체 물리를 재실행하지 않는다.
이벤트 횟수로 실패 유형이나 인과관계를 자동 추정하지 않는다.

## Random 비교용 입력 계약

단일 `--run`은 method/seed 출처를 알 수 없으므로 `unassigned`, 비교는 `missing_comparison_design`이다.
실제 같은 조건에서 AFS/Random 실험을 확보한 경우 아래 구조의 JSON을 `--input`으로 읽는다.
이 예의 경로와 condition ID는 **설명용 값**이므로 실제 기록 값으로 채워야 한다.
condition ID는 `episodes.jsonl`의 값을 사용한다. 경로는 입력 JSON 위치에 상대적이다.

```json
{
  "schema_version": "failure-measurement-input-v1",
  "campaign_id": "declared-comparison",
  "design": {
    "domain_id": "frozen-scene-domain-revision",
    "sampling_distribution": "recorded-uniform-domain-distribution",
    "condition_id": "REPLACE_WITH_RECORDED_CONDITION_ID",
    "valid_budget_per_seed": 1,
    "seeds": [17]
  },
  "runs": [
    {"path": "afs-run", "method": "afs", "seed": 17, "stage": "discovery"},
    {"path": "random-run", "method": "random", "seed": 17, "stage": "discovery"}
  ]
}
```

두 method의 각 seed가 선언한 유효 예산을 정확히 채워야 하며, 초과 자료를 조용히 잘라 쓰지 않는다.
로봇 조건/반환 모델/예산/seed가 다르면 `not_comparable`이다. 조건이 섞인 집단의 FDR도 합산하지 않는다.
`cold_start`, `repeat`, `boundary` 단계 역시 유효 예산을 소비한다.
하나의 물리 실행을 두 method의 공통 cold start로 이중 집계하는 것은 현재 importer에서 허용하지 않는다.
공통 초기 장면을 사용할 때도 각 method에 별도 실행을 배정해야 한다.

이 입력은 사후 선언이며 실제 Random 생성 분포나 사전 등록 사실까지 인증하지 않는다.
따라서 현재 출력은 **사후 기술 통계**다. 공정한 prospective 비교를 입증하는 ledger/자동 실행은 P2 범위다.

## P1 추가 출력과 다음 구현

`--with-memory`를 지정하면 `memory/index.html`, 실행별 행동 시간선, case별 장면/재현 조건과
선택 증거 bundle을 생성한다. MP4는 기본 원본 참조이며 `--bundle-video`로 복사할 수 있다.
GIF와 API 전송 원문은 복사하지 않는다. 성공 대조·혼합 반복도 보관하고 동일 조건의 단일 축
관측 bracket만 추출한다. [해석과 제한](BEHAVIOR_FAILURE_MEMORY.md)을 참고한다.

실패 유형 detector는 아직 없어 이 출력도 공식 coverage를 늘리지 않는다.
P2의 LLM 행동 근거 피드백·동일 유효 예산 AFS/Random campaign은 별도 CLI에 첫 구현했다.
실제 live 비교, 자동 회귀 실행과 추가 유형 계측은 후속 범위다. 로봇 행동이나 goal 판정은 바꾸지 않는다.
