# AFS 근거 ID 출력 제한·명시적 복구 구현

## 요청과 원칙

앞선 진단에서 Luna가 근거 ID의 `9` 한 글자를 누락해 첫 적응형 제안이 거부된 것을
확인했다. 사용자가 예방 수정과 원본/비용을 보존하는 복구 구현을 승인했다.
기존 dirty worktree는 보존했고 커밋/push를 하지 않았다. 이번 작업에는 새 유료 API,
GPU 로봇 실험, 기존 결과 재분류, 예산 확대가 없다.

OpenAI Docs 스킬을 적용해 [공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs)를
확인했다. enum 제약을 기존 Responses 요청에 적용했으며 모델/추론/endpoint를 바꾸지 않았다.

## 구현

1. `llm_afs.behavior.evidence_ids`로 요청/검증의 허용 근거 ID 목록을 통일했다.
   standalone / campaign_single_endpoint / campaign_hypothesis_endpoint 모두
   `evidence_refs.items.enum`을 제한한다. 빈 목록/빈 ID/중복 ID는 요청 전에 거부한다.
2. host 검증은 유지한다. `EvidenceReferenceError`와 proposal error.json의 validation
   필드에 unknown/allowed ID를 남긴다. 모델 응답을 자동 수정하거나 재요청하지 않는다.
3. `failure_client/experiments/proposal_recovery.py`와
   `run_afs_benchmark.py recover-evidence-refs`를 추가했다. 기본은 dry run이다.
   적용은 명시적 매핑, 사유, 검토한 plan hash, 새 비중첩 output directory가 필요하다.
4. 복구 지원 범위는 첫 pending proposal, 완료된 VALID cold starts, 한 글자가 빠진
   63자리 hex ID에서 제공된 64자리 ID로의 유일한 대응이다. 다중 보정/유효 ID 교체/
   모호한 대응/범위·context 오류/API 오류·거절/근거 변조는 거부한다.
5. 원본 캠페인 잠금을 잡고 DB+WAL을 임시 디렉터리로 복사해 조회한다.
   원본 request/response/DB/rollout은 건드리지 않는다. source_snapshot.json 및
   recovery.json에 과거 ledger/protocol/checkpoint, 보정, 해시, 코드 차이를 기록한다.
6. 현재 코드로 별도 복구 캠페인의 조건을 고정한다. 이번 관련 5개 코드 경로 이외의
   변경이나 robot/resources/dependencies 변화는 거부한다. 기존 config/budget, 진행
   순서, 4개 결과, 제안 호출/토큰 비용은 계승한다. 기존 archive 경로는 원본을 참조한다.
7. 복구 audit/request/response/candidate 변조를 resume/report 전에 검증한다.
   일반 `_fresh` 코드 고정 검사도 유지된다. 원본 폴더를 삭제/이동하면 안 된다.
8. summary/report에 operator-assisted continuation을 표시한다. 비교 완료 이후라도
   relative_gain=null, per_seed=[], not_comparable로 유지하고 보정 이유를 노출한다.
   이 복구본은 완전 자율의 prospective AFS/Random 우월성 증거로 사용하지 않는다.

추가 문서: `scene2test/docs/AFS_EVIDENCE_RECOVERY.md`.
README/AFS v2/캠페인 가이드/AGENTS.md에 연결·범위를 기록했다.

## 검증

- 첫 집중 검사: 35 passed, 1 failed. SQLite `mode=ro`만으로는 원본에 빈 WAL/SHM이
  생길 수 있음을 원본 전체 파일 해시 테스트가 검출했다. 임시 DB+WAL 사본 조회로 수정했다.
- 수정 후 집중 검사 36 passed. 이후 committed WAL 및 복구 후 원본 근거 변조 검사를
  더해 **38 passed (15.53s)**.
- 최종 관련 전체 테스트 **321 passed (111.22s)**:

```bash
.venv/bin/python -m pytest tests/client tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_behavior_request.py tests/test_corridor_scene.py tests/test_goal_outcome_runner.py -q
```

- Ruff 변경 Python 파일 검사 및 `git diff --check` 통과.
- 합성 복구에서 4회 계승 → 추가 1회(제안 재호출 0) → 총 12회 완료를 검증했다.
  기존 비용 유지, 부분/완료 보고서의 정식 Gain 차단, 원본 모든 파일 해시 동일을 확인했다.
- 손상된 원본/복구 audit/응답/request, 잘못된 mapping, plan hash 변경, 실행 중 source lock,
  변경된 자원/코드/의존성은 거부되는 테스트를 수행했다.
- API 모델이나 실제 GPU 주행 성능을 새로 검증한 결과는 아니다.

## 실제 중단 캠페인의 오프라인 복구

원본: `/workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z`

복구본: `/workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z_evidence_recovery`

사용한 명시적 매핑: `scene2test/config/recovery/corridor_20260928_evidence_ref.json`.

적용한 계획 SHA256:
`2b1a54f42fe104e05db51fdfbdba6439d3e5ca2ddfce71d892cb2f8e2d2829ab`

실제 4개 archive와 pending context를 재검증해 별도 복구본을 생성했다.
API/runner를 호출하면 즉시 실패하는 double을 주입하고 `run(max_new_attempts=0)`을
실행해 새 코드의 고정 조건 및 저장 제안의 정상 재개 준비를 확인했다.

- 상태 READY, pending proposal_00000은 검증된 READY 후보로 대기.
- AFS 2/6, Random 2/6, 제외 0. 새 로봇 실행 0.
- 기존 로봇 API 39회, 입력 1,104,831 / 출력 21,768 tokens 유지.
- 기존 AFS 요청 1회 유지(재요청 없음), 최대 요청 수 2회 그대로.
- 다음 후보는 통로 폭 4.0m success_probe다. 질량 9.335359386209577kg,
  상자 마찰 1.116672996420528, 바닥 마찰 0.9224795804663011,
  lateral fraction -0.1792382426966863은 기존 최신 AFS 장면 값 그대로다.
  폭 변경 시 실제 box Y도 바뀌는 기존 coupling은 유지된다.

추가 실행은 사용자 명령으로만 한다. 먼저 1개 rollout을 실행하도록 문서에 안내했다.
남은 시도는 최대8회, 새 로봇 호출 최대80회, 새 AFS 요청 최대1회다.
지금의 복구본을 계속 쓰려면 코드가 다시 바뀌지 않아야 한다.

최종 오프라인 보고서:
`/workspace/g1_failure/runtime/afs_benchmark/20260928T115610_236724Z_evidence_recovery/reports/20260928T131859_576317Z/report.html`

복구/0회 재개 검사/보고서 생성 전후 **원본의 494개 파일 전체 해시와 파일 목록이 동일**했다.
원본 오류 응답도 그대로이며, 보정본은 감사 기록을 통해서만 파생한다.
