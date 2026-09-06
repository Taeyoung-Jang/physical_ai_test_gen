# 프로젝트 통합 현황 감사

기준일: 2026-09-06 UTC. 범위: 설계·코드·테스트·기존 실행 증거의 대조. 이번 감사에서 새 GPU 실험이나 기능 구현은 하지 않았다.

## 결론

G1을 실행하고 결과를 보존하는 Client/Server 기반은 존재한다. 다음 과제는 이를 다시 만드는 것이 아니라, **결과에 적응하는 실패 탐색과 공정한 비교 실험을 연결하는 것**이다. 기존 Panda AFS의 적응형 탐색이 G1 서버에서도 작동한다고 해석하면 안 된다.

```text
SceneGraph / scene3d → 기존 AFS 또는 LAM → 로컬 Panda/PyBullet → 기존 보고서·대시보드
                         │ 사전 생성 후보의 import만 가능
                         ▼
Client method → propose/execute/evaluate/observe → HTTP Server → G1/MuJoCo/CUDA
                    └→ archive/checkpoint/export       └→ 상태·지표·영상

g1-local-nav: 별도 MLX/계층형 내비게이션 프로젝트 — 위 프로젝트와 병합하지 않음
```

## 구현과 검증 범위

| 영역 | 확인된 구현 | 남은 연결·검증 |
|---|---|---|
| 기존 AFS | surrogate 학습, acquisition, 로컬 PyBullet 평가 | G1 관측으로 학습하는 Client method 없음 |
| LAM-guided | 행동 프로파일·family 기반 후보 생성·로컬 평가 | G1 연결 및 guided gain 비교 실험 미확인 |
| scene3d | HM3D/mesh/SceneGraph 입력, 로컬 workspace 및 AFS 재사용 | Server scene ingestion 아님; raw mesh의 의미 분해도 아님 |
| Client | propose→evaluate→observe, 재개·분기·체크포인트·artifact 검증·실패 export | 내장 random/Sobol은 관측에 따라 분포를 학습하지 않음 |
| legacy adapters | 기존 AFS mutation/LAM 후보를 operation으로 변환 | 원래 탐색기를 호출·학습하지 않음; LAM의 add_mesh는 현 서버 미지원 |
| Server | stand/locomotion, spawn/friction/external force, 비동기 job, 결과·영상 | 장애물 삽입·임의 장면 실행·일반 로봇 호환은 미완성 |
| GPU 실행 | 기존 저장 결과와 작업 이력에 G1 CUDA 보행 및 path_hold 검증 | 장면 탐색·다중 모델·장시간 서비스 신뢰성의 검증은 아님 |
| 보고서 | Client failure export, 보행 분석 도구, JSON/영상 | 보행 분석 도구는 Server 로컬 DB 의존; 원격 Client 통합 보고 필요 |
| 대시보드 | app.py의 로컬 AFS UI | 새 Client archive/Server job과 미연결 |
| g1-local-nav | 별도 MLX 모델 서비스·로봇 어댑터·테스트 코드 | 이번 Linux 감사에서 E2E 미검증; 해당 AGENTS의 독립성 유지 |

## 우선 해결할 갭

### P0 — 비교 가능한 실험 계약

1. **예산 단위 불일치.** Client 실행 루프는 저장된 candidate 수를 기준으로 예산을 진행한다. 설계의 valid evaluated rollout 예산과 같지 않으며 반복 횟수도 구분해야 한다. invalid, indeterminate, infra error, retry, repeat를 별도 집계하고, 동일 유효 평가 수와 총 시도/시간을 함께 보고해야 한다.
2. **실행 자원의 재현성 부족.** API는 registry revision을 검사하지만 worker/컨트롤러는 알려진 XML·설정 경로를 선택한다. bootstrap의 XML/ONNX hash만으로 XML 종속 mesh, gains YAML, 실행 코드, supervisor까지 고정되지 않는다. 기존 manifest가 있으면 재생성을 건너뛴다. 요청 revision과 실제 사용된 resource digest를 결합해야 한다.
3. **판정 버전과 정책 구분.** 최근 수치 불안정과 넘어짐의 구분, 좌표계 지표 수정, path_hold 옵션을 반영했다. 그러나 이전 결과와 새 결과를 섞어 비교해서는 안 된다. evaluator/metrics/controller/supervisor 버전을 실험 프로토콜에 고정한다. path_hold는 원 정책 성능 개선의 증거가 아니라 별도 제어 조건이다.

### P1 — 적응형 탐색의 연결

`FailureDiscoveryMethod`와 observe 경로는 이미 있으므로 새 orchestration을 만들 필요가 없다. 현재 지원하는 마찰·외력 공간에서 첫 적응형 plugin을 구현하는 것이 가장 작은 연결이다. 기존 AFS의 surrogate/acquisition 아이디어는 재사용할 수 있지만 Panda의 8D mutation·6개 margin을 G1 지표로 그대로 해석해서는 안 된다.

### P2 — 서비스 계약과 장면 확장

- advertised parallel limit 1에 대응하는 전역 실행 admission/queue 보장이 코드상 명확하지 않다. 여러 Client 동시 요청의 GPU 과점유 가능성을 검증해야 한다.
- cancel 이후 worker 완료/실패가 상태를 덮어쓰는 경쟁 가능성은 추가 테스트 대상이다. 이번 감사에서 재현한 장애로 분류하지 않는다.
- Manual method의 사전 capability 요구 추출은 nested operations까지 포괄하지 않는다. 개별 candidate validation은 존재하므로 검증 전체가 없다는 뜻은 아니다.
- scene query는 정적 manifest 중심이다. 장애물·mesh 삽입과 실제 worker 장면 자원 연결 없이는 scene-conditioned failure generation을 주장할 수 없다.
- recording 설정의 모든 채널이 동일하게 구현된 것은 아니다. 지원 채널과 실제 산출물 일치 검사가 필요하다.

### P3 — 관찰·보고의 통합

Client archive를 기준으로 성공/실패/무효·예산·재현 정보·영상 링크를 함께 제공한다. 기존 AFS 대시보드와 새 G1 실행을 명확히 구분한다. 원격 Client에서 Server SQLite를 직접 읽지 않아도 보고서가 만들어져야 한다.

## 확인 근거

- 설계: [Client Architecture](../../.blueprint/CLIENT_ARCHITECTURE.md), [기존 AFS/LAM 갭](GAP_ANALYSIS.md). 전자의 Client-only 범위는 현재 저장소 Server 구현과 다르며 설계 당시 범위로 해석한다.
- 탐색: [AFS](../src/active_failure_search.py), [LAM loop](../src/lam_guided/lam_guided_loop.py), [scene3d search](../src/scene3d/failure_search.py), [scene sources](../src/scene3d/sources.py).
- Client: [orchestrator](../src/failure_client/experiments/orchestrator.py), [registry](../src/failure_client/methods/registry.py), [baselines](../src/failure_client/methods/baselines/), [adapters](../src/failure_client/methods/adapters/).
- Server: [API](../src/simulation_server/main.py), [worker](../src/simulation_server/worker.py), [bootstrap](../src/simulation_server/bootstrap.py), [controller](../src/simulation_server/groot_locomotion.py), [jobs](../src/simulation_server/jobs.py).
- UI: [app.py](../app.py). GPU 결과 및 평가 수정: [작업 이력](../../.workhistory/2026-09-06_heading_fixes.md).

## 이번 감사의 검증

`scene2test`에서 `PYBULLET_MODE=DIRECT .venv/bin/python -m pytest tests/client tests/server -q`: **55 passed, 1 warning, 44.18s**. 경고는 Starlette TestClient/httpx deprecation이다.

이 테스트들은 Client 계약·복구 및 Server probe/지표 단위 검증을 포함한다. fake gateway의 100-job acceptance는 실제 GPU 100회 부하 시험이 아니다. 이 결과를 전체 저장소 테스트 통과 또는 새 GPU E2E 통과로 확대 해석하지 않는다. 조회 당시 health는 groot_mujoco/루트 가용성을 보고했지만 health만으로 정상 보행을 판정하지 않는다.

후속 순서와 완료 기준: [프로젝트 로드맵](PROJECT_ROADMAP.md).
