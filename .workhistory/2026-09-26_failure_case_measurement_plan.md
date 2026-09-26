# Failure Case 목표 검토 및 측정/탐색/회귀 계획

날짜: 2026-09-26 UTC.
상태: 설계·문서화 완료. 신규 measure/campaign 기능 구현 및 실제 비교 실험은 미수행.

## 요청

`.blueprint/Failure_Case_Goal.md`의 평가 목표를 확인하고, 개선 방법 중
Active Failure Search 우선 탐색과 LAM/VLA 행동 검증·회귀 자산화에 집중하는 전체 계획 수립.
사용자의 기존 목표-only 실패 정의와 반복적인 난이도 상승이 아닌 경계/대안 탐색 원칙을 유지.

## 확인한 현재 구현

- `robot_vlm/goal_runner.py`, `task_outcome.py`, `scene_config.py`: 목표 평가·실행 로그·3축 고정 장면.
- `llm_afs/behavior.py`, `behavior_request.py`: 실제 행동 증거를 읽어 완화/경계/대안 장면 제안.
- `failure_client/methods/base.py`, `experiments/orchestrator.py`: propose/observe/checkpoint 및 기존 후보 예산.
- `failure_client/archive/{models,failure_archive}.py`, `reporting/exporter.py`: 반복 집계와 증거 export 재사용 가능.
- `lam_guided/{types,policy_oracle,failure_memory}.py`: Panda 전용 판정/필드, G1에 그대로 적용하면 안 됨.
- `llm_afs/expanded.py`, `docs/G1_SCENE_SEARCH.md`: 생성/기존 navigation 비교와 goal-agent 실행 경로는 다름.
- 통합 감사/로드맵, 최신 `GOAL_OUTCOME_AFS_IMPLEMENTATION.md`를 함께 대조.

## 설계 결정

1. 공식 목표는 FDR 30%, Random 대비 상대 Gain 20%, 6종 중 4종. episode 단위 분모와 예외를 고정.
2. 목표 결과, 행동 이벤트, 실패 유형 귀속을 분리. 접촉/낙상/no_path만으로 goal FAIL을 만들지 않음.
3. 동일 B에는 cold start·반복·경계 실험도 포함. 미완료·API 오류·legacy 조기 종료를 공식 실패에 합산하지 않음.
4. Random 0실패면 상대 Gain 계산 불가. 고유 실패·비용·여러 seed의 불확실성을 병기.
5. 6종 중 미지원 유형은 그대로 노출. 현재 3개 물리 축만으로 4종 coverage 완료를 주장하지 않음.
6. 기존 LLM-first AFS 유지. LLM 자신감을 확률/교정된 불확실성으로 포장하지 않음.
7. 기존 client 저장/복구/method/archive를 재사용하는 로컬 실행 adapter 중심.
   별도 HTTP 서버 확장·로봇 grasp/jump 개발·Panda/G1 혼합은 이번 우선 범위가 아님.
8. 단계: P0 지표 계약/계산기 → P1 행동/메모리 → P2 공정 폐루프 비교 → P3 유형/회귀 범위 → P4 동결 평가.
9. runtime 경로 유지, GIF 비활성화/MP4 유지, 120초 기본 상한 복구 없음.

## 산출물

- [전체 구현 계획](../scene2test/docs/FAILURE_CASE_MEASUREMENT_PLAN.md): 공식, 분모, taxonomy,
  trace measure, 회귀 자산, AFS 전략, 구현 위치/순서, 테스트 및 보고서 계약.
- `PROJECT_ROADMAP.md`와 `AGENTS.md`에 최신 계획의 우선순위 및 미구현 상태 안내.
- 이력 목록에 이번 기록 추가.

## 검증과 한계

- 작업 시작 시 git worktree는 깨끗했으며 기존 산출물·코드는 변경하지 않음.
- 문서 링크/경로와 diff 공백 검사를 수행. 기능 코드가 바뀌지 않아 pytest/live rollout은 실행하지 않음.
- 최초 Ruby 기반 링크 검사는 환경에 Ruby가 없어 실행되지 않았고, Bash/rg 기반 검사로 대체해 통과.
- 유료 API, GPU 실험, commit/push 미수행. 신규 CLI 이름은 설계안이며 아직 실행 명령이 아님.
- 다음 구현은 P0 + P1 최소 importer부터. 기존 미완결 실행을 임의로 공식 FAIL로 복원하지 않음.
