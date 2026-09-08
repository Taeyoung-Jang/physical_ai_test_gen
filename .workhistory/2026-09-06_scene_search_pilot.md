# 2026-09-06: SceneGraph-based mutation, baselines and adaptive search

## Request and initial state

User authorized all three planned steps: bounded scene mutations, Random/Sobol baseline
experiments, and adaptive AFS comparison using actual G1 CUDA navigation. Initial worktree
was clean. Existing five-stage navigation evidence and localhost:8000/8001 services were
preserved. No changes were made to the independent g1-local-nav project.

## Design decisions recorded before results

Use the successful obstacle fixture and move its shared SceneGraph/physics object
`obstacle_0`, X [-2,2] m and Y [-2.4,2.4] m. Keep task goal/spawn/walls/box size fixed.
Every mutation derives a new revision and a consistent graph/map/XML bundle. The existing
trusted local registration path avoids introducing a remote scene-editing API for a pilot.

The implementation is a dedicated local scene-bundle runner. It does **not** claim to have
added an adaptive plugin to the existing failure_client general orchestrator. This scoped
choice reuses scene registration, HTTP execution and server result/artifact contracts
without altering legacy intervention validation or candidate-count budget semantics.

Comparison protocol: methods random/sobol/afs, one seed 20260906, eight valid rollouts per
method, maximum 40 proposals each, speed .3 m/s, 120 s simulation limit, videos always.
Geometry rejections and invalid execution excluded from failure rate/training/valid budget.
AFS: four valid Sobol cold-start observations, 64-tree ExtraTrees surrogate, 512-point
candidate pool, lower-confidence heuristic plus novelty. Scalar utility separates valid
failure from success and ranks successful episodes by time slack. Not a physical-margin
certificate or calibrated posterior. Do not change bounds/deadline based on outcomes.

## Implementation

- `scene2test/src/procedural_world/search.py`: immutable mutation validation, evaluation
  utility and journal-rebuildable Random/Sobol/adaptive samplers.
- `scene2test/tools/run_scene_search.py`: frozen protocol, single-writer lock, atomic
  journal, pre-submission persistence and HTTP idempotency, resume validation, equal valid
  budgets, bounded attempts, artifact hash/size verification, CUDA/revision verification,
  structured and Markdown reports.
- `scene2test/tests/test_scene_search.py`: mutation consistency, invalid parameters,
  excluded invalid training, deterministic restart, adaptive feedback sensitivity and
  exclusion of failed/malformed execution.
- `scene2test/docs/G1_SCENE_SEARCH.md`: protocol, commands and claim boundaries.

## Verification and execution

Initial focused tests: 8 passed. Full client/server/procedural regression and actual GPU
comparison launched afterward. Final results and limitations will be appended after the
processes finish; launching a run is not recorded as successful completion.

## 최종 결과 및 감사

실험 경로: `/workspace/g1_failure/runtime/scene_search/20260906T191728_897030Z`.
`report.md`, `summary.json`, `protocol.json`, `journal.json` 및
`review/audit.json`, `review/mutation_space.png`를 보존했다.

| 방법 | 전체 후보 | 유효 실행 | 성공 | 실패 | 무효 장면 | 실행 오류 | 적응형 유효 실행 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Random | 10 | 8 | 8 | 0 | 2 | 0 | 0 |
| Sobol | 8 | 8 | 8 | 0 | 0 | 0 | 0 |
| AFS | 10 | 8 | 8 | 0 | 2 | 0 | 4 |

- 총 24회 실제 CUDA 실행에서 목표 도달, 충돌/넘어짐 없음. 무효 장면 4개는
  GEOMETRY_OVERLAP으로 사전 제외했으며 실패로 세지 않았다.
- 평균 시뮬레이션 시간: Random 45.10125 s, Sobol 45.575625 s, AFS 45.07125 s.
  이는 발견 성능의 우위나 실행 속도 개선을 의미하지 않는다.
- 모든 방법의 최대 최종 목표 거리 0.201291 m로 고정 허용치 0.25 m 이내.
- AFS는 유효 관측 4개 이후 실제 학습과 후보 선택을 4회 수행했다.
  후보별 training_count/predicted_utility/ensemble_std/acquisition을 journal에 저장했다.
- 312개 산출물의 HTTP 및 로컬 파일 해시/크기를 검증했다.
  MP4 24개, GIF 24개를 포함하며 실제 파일은
  `/workspace/g1_failure/runtime/navigation_server/outputs/jobs/<job_id>/` 아래에 있다.
- 모든 후보를 과거 관측으로 다시 생성했을 때 offsets와 acquisition 메타데이터가
  정확히 일치했다. 프로토콜 코드 해시 및 worker 코드 해시도 일치했다.
- Sobol/AFS의 공통 초기 장면 4쌍은 모든 task_facts가 동일했다.
  이는 이번 재실행의 증거이며 모든 환경에서 결정론적이라는 보장은 아니다.
- 최종 AFS 영상:
  `/workspace/g1_failure/runtime/navigation_server/outputs/jobs/job_40087a8efbe7467283239e71e0f4656c/rollout.mp4`.
- 회귀 테스트 명령:
  `PYTHONPATH=src .venv/bin/pytest tests/client tests/server tests/test_procedural_world.py tests/test_scene_search.py tests/test_scene_search_runner.py -q`
  → **96 passed**, Starlette/httpx 기존 deprecation warning 1개.
- Ruff 및 git diff --check 통과.
- 재개 테스트에서 서버가 접수한 직후 응답이 유실되는 상황을 재현했고,
  동일 idempotency key로 중복 실행 없이 복구했다. 무효 장면/실행 오류가
  유효 예산에 포함되지 않는 것과 미완료 보고서의 구분도 검증했다.

## 해석 및 남은 작업

이번에 완성한 것은 SceneGraph와 일치하는 환경 변형 → 실제 GPU 실행 →
관측 기반 적응형 선택의 **파일럿 폐루프**이다. 모든 방법에서 실패가 0건이므로
AFS의 실패 발견 효율 개선을 입증하지 못했다. 실험 결과를 보고 범위나 제한
시간을 바꾸지는 않았다. 단일 장면·단일 시드·2차원 변형의 결과를 일반화하지 않는다.

다음 연구는 사전에 고정한 복수 환경/시드 및 실패 경계가 존재하는 변형 공간에서
충분한 예산으로 비교하는 것이다. 더 풍부한 연속 안전 여유도, 유효 장면 필터링
효율, 일반 failure_client 플러그인/프로토콜 통합도 남아 있다. 외부 LLM/LAM,
센서 기반 미지 장애물 회피, 실제 로봇 안전 검증은 이번 범위에 포함되지 않았다.
