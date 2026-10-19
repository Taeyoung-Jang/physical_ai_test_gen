# 외부 이력 없는 독립 AFS 평가 실행기

사용자가 다음 구현 진행을 승인해, 평가 준비 manifest를 실제 seed별 초기 장면 실행과 AFS 탐색에 연결했다. 목표는 같은 로봇·목표·사전 시험 집합에서 FDR 30%와 검증된 primary 실패 유형 4종을 함께 측정하는 것이다. Random 상대 Gain은 후속 단계다.

## 실행 계약

새 `independent_discovery.py`의 `DiscoveryEvaluation`은 사전 순서의 seed를 실행한다. `IndependentSeed`는 기존 실행기의 durable intent·저장 응답 수집·엄격한 환경 및 결과 검사를 재사용하되 별도 mode와 입력 정책을 사용한다. 과거 대조 자료는 실행 조건과 자원의 provenance에만 쓰고, 평가 탐색 이력은 빈 목록으로 시작한다. 다른 seed의 기록도 입력하지 않는다.

각 seed의 정해진 초기 시도는 full-domain uniform이며 seed와 인덱스로 재현한다. 유효 PASS/FAIL은 전체 평가 분모와 유형 집계에 포함하고 제외도 시도 예산을 소비한다. 모두 제외되면 대체 초기 실행이나 외부 PASS 없이 멈춘다. PASS 기준이 없을 때 기존 FAIL 완화 규칙만 허용하고, 유효 기준이 없어지면 `no_eligible_observed_anchor`로 멈춘다. 자동 Random 대체나 무제한 완화는 없다.

초기 실행을 포함한 전체 시도 인덱스로 작은·큰·조합 순환을 적용한다. 초기 장면은 단일 축 변경 quota를 소비하지 않는다. 정책·목표·판정·검출 임계값·모델·10호출 예산은 유지했다. 출력 토큰 상한이나 암묵적인 시뮬레이션 시간 제한은 추가하지 않았다.

## 동결과 집계

새 v2 manifest는 조건·geometry·origin·실행 도구와 source/resources/runtime 해시를 고정한다. 캠페인과 seed별 DB는 manifest에 묶이고 source drift는 실행 전 거절한다. 준비 전용 v1은 재동결해야 한다. `init`과 상태·보고서는 API를 호출하지 않는다. `run`은 명시적 `--live`가 필요하고 호출당 시도 제한은 seed 전체에 적용한다.

초기·탐색·제외 시도를 모두 보존하고 새 기록에 AFS/seed/stage를 붙여 집계한다. 보고서는 seed별 예산·AFS/로봇 비용·ledger·원본 로봇 보고서와 MP4 링크, 전체 pooled 측정값을 제공한다. `joint_target_at_complete_budget`은 모든 사전 유효 목표가 완료되기 전 null이다. 부분 규칙 지원 때문에 일반 coverage는 여전히 null일 수 있으며 primary 종류 수를 별도로 읽는다. 공통 imported-data 계산기의 주의사항은 삭제하지 않았다.

## 검증

CPU 모의 검증은 초기 실행의 결정성·비용·분모, 외부 및 cross-seed 근거 차단, 전체 seed 완료, 불확실한 요청 무재전송, 저장 응답 재개, 제외 후 다음 사전 장면, 초기 근거 부재와 PASS 기준 부재 중단, 소스 drift 및 출력 재사용 거절, 요청 상한, FDR 달성 후 조기 중단 금지를 확인했다. 최종 관련 회귀 테스트 121개가 32.06초에 통과했다. 변경한 Python 8개 파일의 Ruff 검사와 형식 검사, git diff whitespace 검사도 통과했다.

실제 보관된 numeric recovery의 PASS attempt_00002로 무료 `evaluation_plan`을 확인했다. 로봇 조건은 기존 `e8ec8119…`와 같고 external history는 빈 목록이다. 설정은 seed 17·29·43, 각각 유효 20개·최대 24시도, 전체 유효 60개·최대 72시도·최대 720로봇호출·AFS 72요청이다. 이는 실제 실행 비용이 아니라 동결 예정 상한이다.

사전 초기 장면 6개는 모두 서로 다른 유효 scene config로 컴파일됐다. 실제 환경 fingerprint를 사용한 무료 초기화·상태·보고서 검증은 `/tmp/independent-afs-offline-rkrppvd8/campaign`에서 READY·시도 0·AFS 요청 0을 확인했다. 임시 보고서는 그 아래 `reports/20261019T053826_355528Z/report.html`이며 live 성과 자료가 아니다.

구조화 출력의 strict schema 계약은 [OpenAI 공식 안내](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)를 확인해 유지했다. 모델 호환성이나 live 성능을 추가 검증한 것은 아니다. 문서 작성 스킬은 실행 순서와 중단 조건을 기존 저장소 문서에 정리하는 데 사용했다.

## 다음 단계

[실행 명령](../scene2test/docs/AFS_REFERENCE_RECOVERY_AND_EVALUATION.md#독립-평가-실행)에 따라 새 manifest와 캠페인을 만든 뒤 초기 장면 한 번을 live 검증한다. 개발 결과를 최종 평가에 합치지 않는다. 이 구현에서는 API·GPU·로봇·새 runtime 캠페인·실제 복구본을 실행하거나 만들지 않았고 원래 세션·판정·예산도 수정하지 않았다. commit/push는 하지 않았다.
