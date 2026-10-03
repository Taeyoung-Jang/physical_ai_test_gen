# AFS 근거 ID 오류 예방·원본 보존 복구

2026-09-28 UTC. `unknown evidence reference`로 중단된 첫 AFS 제안을 위한
명시적 오프라인 복구다. API 재시도, 로봇 조작, 예산 확대 기능이 아니다.

## 무엇을 고쳤나

기존 요청은 evidence_refs를 자유 문자열로 허용했다. 실제 Luna 응답이 입력의 64자리
근거 ID에서 `9` 한 글자를 누락해 host 검증에서 중단됐다. 이제 standalone / 기존
campaign / hypothesis-v2 요청 모두 `evidence_refs.items.enum`에 **제공한 ID만** 넣는다.
context_sha256과 허용 axis 제약도 유지한다. 범위·증거의 의미 검증을 대신하지 않는다.
허용 목록 밖의 응답은 계속 거부하며, 오류 파일에 unknown/allowed 목록도 남긴다.

[공식 OpenAI Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs)의
enum 지원을 적용했다. 모델명, API endpoint, 추론 설정, 로봇 조건은 변경하지 않았다.
실제 새 API 호출로 예방 효과를 확인한 것은 아니며 JSON Schema/host 검증을 오프라인 시험했다.

## 복구의 범위와 보호 조건

- 기본은 사전 검증(dry run). 유료 API나 로봇을 시작하지 않는다.
- `NEEDS_ATTENTION`인 첫 pending proposal, 이전 결과가 모두 유효 cold start일 때만 지원한다.
- 사용자가 명시한 **하나의 ID 보정**만 허용한다. 63자리 hex에서 문자가 하나 빠졌고,
  입력의 64자리 ID 중 유일하게 대응되는 경우다. 가설/축/범위/다른 필드는 변경하지 않는다.
- 이미 유효한 ID 교체, 여러 오타, 모호한 대응, stale context, API 거절/실패,
  범위 오류, 변경된 근거는 복구하지 않는다. 자동 근사 매칭이나 몰래 재요청은 없다.
- 원본 캠페인 잠금을 확보하고, SQLite는 임시 복사본(DB+존재하는 WAL)에서 읽는다.
  읽기 전용 SQLite가 원본에 WAL/SHM 파일을 만드는 부수 효과까지 피한다.
- 원본 결과/응답/DB를 수정하지 않는다. **별도 새 폴더**에 감사 기록·계승 checkpoint를 만든다.
- 로봇/목표/분포/예산/의존성/자원 변경은 거부한다. 이번 증거 검증·복구 관련 5개
  코드 경로의 변경만 별도 기록해 새로운 코드 고정 조건으로 승인한다. 일반적인 drift 우회가 아니다.
- 기존 4회, API 사용량, AFS 요청 1회, 진행 순서를 계승한다. 무료 cold start나 비용 초기화가 아니다.
- 예전 rollout/MP4는 **원본 폴더의 경로를 참조**한다. 원본 폴더를 삭제/이동하면 안 된다.
  복구 폴더는 독립 백업이 아니다. resume/report 시 기존 근거 해시를 재검증한다.

복구 파일:

- `recovery.json`: 보정 전후 ID, 이유, request/response/context/후보 해시, 코드 변경, 계승 수량.
- `source_snapshot.json`: 원본 checkpoint/protocol/ledger의 읽기 전용 스냅샷.
- `proposals/proposal_00000/`: 원본 request/response/error의 그대로인 복사본.
- `protocol.json`, `campaign.sqlite3`: 별도 복구 캠페인의 고정 조건과 진행 상태.

보정은 원래 모델 응답으로 위장하지 않는다. 이 캠페인은
`operator_assisted_continuation_not_prospective_comparison`으로 표시한다.
FDR 등 관측 결과와 비용은 보고하지만, **완료해도 공식 Random 대비 Gain은 null**이고
comparison은 not_comparable이다. 수정 없는 탐색 정책의 성능 비교가 필요하면 새 캠페인을
별도로 시작해야 한다. 이 제한을 피하려고 원본 해시나 기록을 수동 수정하지 않는다.

## 이번 캠페인의 다음 실행

작업 디렉터리:

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

복구 준비가 완료된 폴더의 상태 확인(API/GPU 실행 없음):

```bash
uv run --no-sync python tools/run_afs_benchmark.py status --campaign /workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z_evidence_recovery
```

먼저 **다음 로봇 실험 1회만** 실행한다(API 키 필요, 유료):

```bash
uv run --no-sync python tools/run_afs_benchmark.py run --live --max-new-attempts 1 --campaign /workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z_evidence_recovery
```

이 1회는 기존 proposal_00000의 명시적 ID 보정본을 사용한다. AFS 모델에 다시 요청하지
않으며, 로봇 Luna 호출은 최대 10회 발생한다. 선택된 장면은 최신 AFS 장면에서 통로 폭을
4.0m로 바꾼 success_probe다. 로봇이 어떤 행동을 선택할지는 로봇 시스템이 결정한다.

실행 후 보고서 생성(API/GPU 실행 없음):

```bash
uv run --no-sync python tools/run_afs_benchmark.py report --with-memory --campaign /workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z_evidence_recovery
```

결과를 점검한 후 남은 전체 실험을 진행할 때만 실행한다(유료):

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --campaign /workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z_evidence_recovery
```

복구 직후 기준 남은 시도는 AFS 4회 + Random 4회, 새 로봇 API 최대80회,
새 AFS 요청 최대1회다. 전체 상한은 기존 120회+2회 그대로이며 실제 요금 상한은 아니다.
원본과 복구본을 동시에 진행하지 않는다. 이후 코드가 바뀌면 일반 drift 검사가 다시 적용된다.
MP4는 기존 경로/새 attempts에 보존하며 GIF를 생성하지 않는다.

## 다른 머신에서 복구를 다시 준비해야 할 때

이미 복구 폴더가 있으면 이 단계를 반복하지 않는다. 원본 캠페인과 동일한 코드/환경을
가져온 경우, 다음 dry run을 실행한다. 원본 캠페인을 일반 run으로 먼저 열 필요는 없다.

```bash
uv run --no-sync python tools/run_afs_benchmark.py recover-evidence-refs --campaign /workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z --mapping config/recovery/corridor_20260928_evidence_ref.json
```

출력의 `RECOVERY_PLAN_SHA256`을 확인하고, 아래 `REVIEWED_PLAN_SHA256`을 **실제 값으로** 바꾼다.

```bash
uv run --no-sync python tools/run_afs_benchmark.py recover-evidence-refs --campaign /workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z --mapping config/recovery/corridor_20260928_evidence_ref.json --output-dir /workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z_evidence_recovery --apply --expected-plan-sha256 REVIEWED_PLAN_SHA256
```

이 단계도 API/로봇 실행은 없다. 원본 상태/코드가 검토 후 바뀌었으면 plan hash가 달라져
거부된다. 위 매핑 파일은 이번 정확한 ID에만 해당하며 다른 오류에 재사용하지 않는다.
