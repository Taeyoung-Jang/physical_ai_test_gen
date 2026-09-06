# 프로젝트 통합 감사 및 로드맵 정리

- 날짜: 2026-09-06 UTC
- 요청: 로봇 자체 검증이 아닌 프로젝트 전체의 다음 작업 중 1번 진행.
- 범위: 구현/설계/기존 실행 증거 대조, 후속 마일스톤 정의. 새 시뮬레이션·알고리즘 구현·서비스 재시작 없음.

## 조사 및 결과

README, 루트와 g1-local-nav의 AGENTS, Client Architecture, 기존 GAP_ANALYSIS, AFS/LAM/scene3d, Client method/orchestrator, Server API/worker/bootstrap/jobs/controller, 대시보드 및 테스트를 검토했다.

Client 실행·평가·observe·복구는 구현되어 있다. 내장 method는 non-adaptive baseline 또는 사전 생성 후보 import이며 원래 AFS의 surrogate 학습을 G1 결과로 수행하지 않는다. scene3d는 로컬 mesh 기반 AFS 기능이 존재하지만 Server ingestion과는 다르다. g1-local-nav는 별도 프로젝트로 유지한다.

주요 선행 과제는 유효 평가 예산 집계, 실제 실행 자원 provenance, evaluator/controller 버전 고정이다. 이후 현재 지원하는 마찰·외력 공간에서 적응형 method와 Random/Sobol 비교를 진행하도록 순서를 정의했다. 장애물·대시보드·정책 조건부 장면 생성은 후속 마일스톤으로 구분했다.

동시 실행 제한과 cancel 경합은 코드 검토상 위험이며 이번에 재현된 장애라고 주장하지 않는다. 실제 실행 결과의 SUCCEEDED는 연구상 PASS와 같지 않다.

## 검증

- 실행 위치: `scene2test`
- 명령: `PYBULLET_MODE=DIRECT .venv/bin/python -m pytest tests/client tests/server -q`
- 결과: 55 passed, 1 warning, 44.18s. Starlette/httpx deprecation 경고.
- 범위 제한: 계약/probe/단위 테스트 포함. fake gateway 100-job 테스트를 GPU soak로 해석하지 않음. 전체 저장소 테스트나 새 GPU E2E는 수행하지 않음.
- health 읽기: groot_mujoco backend 및 groot root 가용성 확인. 지원 task는 stand/locomotion, operation은 spawn/friction/external force.
- 기존 runtime SQLite를 읽기 전용 조회: 81 SUCCEEDED, 2 FAILED. 유효성·연구 verdict를 포함하지 않는 job 상태 수이므로 성공률로 사용하지 않음.
- 기존 GPU 검증 상세와 산출물: [평가 수정 및 경로 유지 검증](2026-09-06_heading_fixes.md). 기존 출력 기본 경로 `/workspace/g1_failure/runtime` 유지.

## 문서 산출물

- [통합 감사](../scene2test/docs/PROJECT_INTEGRATION_AUDIT.md)
- [마일스톤/완료 기준](../scene2test/docs/PROJECT_ROADMAP.md)
- 기존 README·AGENTS·GAP_ANALYSIS에는 최신 문서와 범위 구분 안내를 추가한다.

기존 미커밋 보행/평가 변경과 실험 증거를 보존한다. 다음 실제 구현 단위는 M0이며 이번 감사에서는 실행 코드를 수정하지 않았다.
