# 행동 근거 기반 실패 지향 AFS

후속 `failure-branch-v3`는 새 메커니즘을 관찰된 PASS에서, 완화 제안을 관찰된 FAIL에서
분기한다. 최신 실패 조건의 자동 누적을 피하는 새 세션 설정과 진단은
[성공 기준 분기 AFS 안내](AFS_BRANCH_ANCHORS.md)를 사용한다. 아래는 기존 v2 계약이다.

`failure-directed-v2`의 목표는 로봇의 고정된 최종 goal을 달성하지 못하게 하는 장면을
탐색하고, 같은 유효 실험 집합에서 실패율30%와 측정 근거가 있는4종을 함께 관찰하는
것이다. PASS도 유효한 탐색 결과다. PASS가 나온 전략을 분석해 다른 조건에서 실패할
가능성을 시험하며, PASS를 오류로 처리하거나 FAIL로 바꾸지 않는다.

이 모드는 검토된 외부 이력을 사용하는 개발 탐색이다. 독립 AFS/Random 비교·Gain
측정이 아니며, 가설의 타당성이나 실제 실패율 향상을 코드 검사만으로 입증하지 않는다.

## 제안과 선택

제안은 하나의 환경 축과 구체적인 값, 기존 가설·대안·반증 조건에 더해 다음을 요구한다.

- `behavior_refs`: 실제 제공된 에피소드 행동 근거 ID. case_memory만으로 대신할 수 없다.
- `vulnerability`: 관찰된 행동과 새로 추정하는 취약 조건을 구분한 설명.
- `failure_prediction`: 어떤 과정으로 최종 goal 미달이 발생할 수 있는가.
- `change_rationale`: 현재 값에서 선택한 방향이 그 가설을 시험하는 이유.
- `intent`: challenge, mechanism_transfer 또는 조건부 relief.
- `target_family`: 탐색용 예상 유형 또는 unclassified. 실제 분류·발견 실적이 아니다.

예를 들어 ‘장애물을 옮겨 경로가 달라지는가’만 묻는 대신, 관찰된 이동 전략에서 어떤
접근 공간이나 우회 선택을 바꾸어 목표 미달 가능성을 시험하는지 설명해야 한다.
자유 서술이 물리적으로 옳다는 것을 호스트가 자동 증명하지는 않는다.

호스트는 의도 우선순위, 아직 측정상 발견하지 못한 지원 유형, 해당 유형을 겨냥한
시도 수, 축 시도 수, LLM 제안 순서, 신규성 순으로 후보를 선택한다. 예측 유형을
우선하는 것은 명시된 탐색 휴리스틱이며 실패 확률 추정이나 유형 확인이 아니다.
지원되지 않는 유형에는 unclassified를 사용하며, 이를4종 실적으로 세지 않는다.

기존 v1의 최소 사용 축만 허용하는 규칙은 제거했다. 같은 축도 쿼터 안에서 재검토할
수 있지만 직전 축 cooldown·축별 최대2회·최소 전체 범위10% 변화·중복 거절은 유지한다.
회차당 파라미터 하나만 바꾸고, 자동 중간값·반복 슬롯은 두지 않는다.

실제 비교 가능한 FAIL이 없으면 relief는 금지한다. FAIL이 있더라도 최근3회차에
relief가 있었다면 다시 허용하지 않는다. PASS 없이 FAIL이2개 이상 쌓인 경우에만
허용된 relief를 우선해 성공 쪽을 확인한다. 그 외에는 다른 메커니즘/도전을 우선한다.
이미 실패한 물체를 계속 무겁게 만드는 식의 악화 반복을 기본 전략으로 쓰지 않는다.

최근4회차의 예측과 결과를 다음 요청에 전달한다. PASS는 GOAL_FAILURE_NOT_OBSERVED,
FAIL은 GOAL_FAILURE_OBSERVED_MECHANISM_UNCONFIRMED, 제외는 유효 판정 없음으로
구분한다. 예측과 측정 유형은 별도이며 원인 입증 여부를 자동 판정하지 않는다.

## 유지하는 실험 경계

로봇 모델·goal·기술·정책 호출 예산·완료 조건·평가기는 변경하지 않는다. 환경은 회차
전에 확정하고 실행 중 AFS는 개입하지 않는다. 경로 없음·접촉·노출 자체는 FAIL이 아니다.
사람 측정은 종료 직전5초에 한정되며, 규칙4개 지원과 실제4종 발견을 구분한다.
인프라 오류는 제외 후 중단하고 자동 재시도·무작위 대체·예산 증가는 하지 않는다.
GIF나 출력 토큰 제한·암묵적 시뮬레이션 제한을 추가하지 않았다.

출력 계약은 [OpenAI 공식 Structured Outputs 지침](https://developers.openai.com/api/docs/guides/structured-outputs)에 따라 필수 필드와 추가 필드 금지를 유지한다.
기존 범위/단일 값 계약은 구버전 모드에서 유지하고 새 모드는 필수 근거를 갖춘 단일
값만 받는다. 새로운 실패 가설 필드가 없는 과거 제안을 몰래 승격해 사용하지 않는다.

## 새 세션 실행

기존 `20261018T014205_556509Z_point_recovery`는 보존한다. 새 선택기와 기존 동결
세션을 섞거나 코드 변경 검사를 우회해 이어서 실행하지 않는다. 아래 명령은 새로운
버전·별도 예산의 세션을 만든다. 기존 두 PASS의 로봇 비용은 입력 이력 비용으로
분리하며, 로봇 아카이브에 없는 과거 AFS 비용은 unknown으로 표시한다.

오프라인 사전 검사:

```bash
uv run --no-sync python tools/run_afs_autonomous.py plan --config config/afs_failure_directed_luna.json --run /workspace/g1_failure/runtime/robot_goal_agent/20261018T004636_410637Z --run /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery/attempts/attempt_00001/rollout
```

API 키가 설정된 터미널에서 유료 탐색 시작:

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --config config/afs_failure_directed_luna.json --run /workspace/g1_failure/runtime/robot_goal_agent/20261018T004636_410637Z --run /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery/attempts/attempt_00001/rollout
```

기본은 유효6개/최대8시도, AFS최대8요청·현재 로봇기준 최대80호출이다. 검토 후
`afs_failure_directed_20_luna.json`을 별도 세션에 사용하면 유효20개/최대24시도,
AFS최대24요청·로봇최대240호출이다. 한 명령으로 고정 예산까지 순환하되 오류는 중단한다.
신규 표본만으로 FDR/유형/공동 달성을 보고하며 입력 PASS를 분모에 더하지 않는다.
