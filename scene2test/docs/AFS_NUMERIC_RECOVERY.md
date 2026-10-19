# AFS 숫자 범위 오류 처리와 저장 응답 복구

`breadth-v1`은 숫자 범위를 벗어난 후보만 `numeric_out_of_bounds`로 기록하고, 다른 유효 후보를 선택한다. 첫 축과 두 번째 축 모두 검사한다. 원본 응답과 후보 순서는 유지하고, 값을 보정하거나 승인 범위를 늘리지 않는다. 이전 단일 축 모드의 범위 오류 중단 정책은 그대로다.

모든 후보가 숫자 범위를 벗어나거나 다른 선택 조건을 충족하지 못하면 로봇을 실행하지 않고 후보 거절을 기록한다. 남은 AFS 요청 예산 안에서 새 제안을 받으며 거절된 요청도 비용과 상한에 포함한다. 근거 ID, 컨텍스트, 스키마, 비유한 수치, 허용되지 않은 축, 쿼터와 역할 오류는 여전히 전체 중단한다. 이는 모든 오류를 무시하는 재시도가 아니다.

## 중단된 세션

`20261018T160156_325966Z`는 로봇 실험 두 개를 완료했고, 세 번째 AFS 응답의 장애물 폭 1m가 승인 범위 .2~.8m를 넘어 중단됐다. 같은 응답의 첫 번째 후보인 통로 폭 3.6m와 장애물1 Y 크기 .65m는 검증을 통과한다. 소스가 바뀌었으므로 기존 세션을 직접 재개하지 않는다.

`recover-numeric`은 저장된 응답과 이력만 사용한다. 원본 DB와 응답을 보존하고 새 경로에 감사 가능한 복구본을 만든다. API와 로봇은 호출하지 않는다. 기존 실험 2회, AFS 요청 3회와 비용을 이어받으며 예산을 리셋하지 않는다. 유효 12개 목표에는 10개가 더 필요하고, 시도 최대 16회 중 14회 및 AFS 20요청 중 17요청이 남는다. 복구는 운영자 보조 개발 연속 실행이며 독립적인 새 성능 평가가 아니다.

## 무료 점검과 복구 생성

2026년 10월 18일 아래 `_numeric_recovery` 복구본은 이미 생성돼 READY 상태다. 해당 폴더가 그대로 있다면 생성 단계를 반복하지 말고 아래 유료 재개 명령만 사용한다.

다음 명령은 무료 dry-run이며 출력 경로를 생성하지 않는다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_afs_autonomous.py recover-numeric --session /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z --output-dir /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery
```

`--apply`를 붙이면 원본과 별도인 복구 폴더를 만든다. 이미 존재하는 출력 경로에는 덮어쓰지 않으므로 복구 폴더가 만들어져 있으면 이 단계를 반복하지 않는다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py recover-numeric --session /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z --output-dir /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery --apply
```

복구본은 READY이며 선택된 조합을 보유한다. 그다음 다음 명령은 **유료 로봇 실험과 이후 남은 탐색 예산**을 실행한다. 첫 조합은 기존 응답으로 선택하므로 AFS를 재호출하지 않는다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --session /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery
```

## 감사와 검증 제한

원본 완료 응답, 사용량, 모델, context/request 해시와 전체 컨텍스트를 대조한다. 요청 변경은 숫자 후보 거절 설명을 덧붙인 부분만 허용한다. 근거, 스키마, 모델 또는 입력 값을 새 컨텍스트로 재결합하지 않는다. 숫자 범위 외의 오류나 유효 대안이 없는 경우 복구를 거절한다.

과거 로봇 시도는 유효하게 완료돼 있어야 하며, 모호한 실행은 복구 대상으로 삼지 않는다. 로봇 자원·런타임과 관계없는 소스 변경도 거절한다. 허용 소스 변경은 범위 검증/설명, 이 복구 도구 및 감사 검증 연결 파일로 한정한다.

`recovery.json`, 원본 상태/프로토콜/ledger 사본과 해시를 저장한다. 과거 제안·시도 산출물과 소비 비용을 유지하며 원본 아카이브 경로도 계속 필요하다. 복구 후 다시 실행하기 직전에 선택 후보를 재검증한다. 보고서에는 제외한 후보의 원래 값과 승인 범위가 표시된다.
