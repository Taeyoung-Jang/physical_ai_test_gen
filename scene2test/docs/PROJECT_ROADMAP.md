# 프로젝트 다음 단계와 완료 기준

2026-09-28 AFS 우선 갱신: [행동 근거·가설 중심 선택 v2](AFS_SEARCH_V2.md)를 추가했다.
로봇 코드를 고정한 상태에서 근거 선택/유사 실패 억제/실험 목적/탐색 지표를 개선한다.
다음은 새 동결 캠페인으로 선택 품질을 확인하는 것이며 로봇 기능 개발이 선행 조건은 아니다.

2026-09-28: [통로 폭·배치 5축 AFS](CORRIDOR_AFS.md)의 첫 구현을 추가했다.
원래 3축과 별도 domain으로 goal-agent/campaign/행동 메모리에 연결했고 CPU/합성 테스트로
검증한다. 실제 Luna 성공 대조 확보, 다중 기하 확장과 유형 detector/회귀 실행은 후속 단계다.

## 2026-09-27 우선순위 갱신 — P0/P1·P2 로컬 pilot 첫 구현

사용자가 지정한 [Failure Case 평가 목표](../../.blueprint/Failure_Case_Goal.md)에 맞춰
AFS 탐색 효과와 행동 검증·회귀 자산화에 집중한다. 최신 실행 순서와 measure 계약은
[실패 발견·행동 검증·회귀 구현 계획](FAILURE_CASE_MEASUREMENT_PLAN.md)을 따른다.
목표는 FDR 30%, Random 대비 상대 Gain 20%, 6종 중 4종 발견이며 아직 달성 결과가 아니다.
목표-only 평가를 유지하고, 계측 → 행동 근거/메모리 → 동일 유효 예산의 AFS/Random 폐루프
→ 필요한 유형/회귀 범위 → 동결 비교 순으로 진행한다.
P0 [오프라인 측정기](FAILURE_DISCOVERY_MEASURES.md)와 최소 trace reader의 첫 구현을 반영했다.
P1 [시간별 행동 근거·failure memory](BEHAVIOR_FAILURE_MEMORY.md)도 추가했다.
성공 대조/실패/혼합 반복, 단일 축 관측 bracket, 선택 증거 bundle과 MP4 구간 참조를 제공한다.
P2 [로컬 AFS/Random 캠페인](BEHAVIOR_AFS_CAMPAIGN.md)의 첫 구현도 반영했다.
유효 예산·자기 seed의 행동 피드백·중단 재개는 합성 archive로 검증했으며 실제 GPU/API 비교는 아직 실행하지 않았다.
다음은 예산을 확인한 live pilot 및 P3 유형/회귀 범위다. 실패 유형 detector, 회귀 실행기,
core/media manifest 분리·최종화 순서 개선은 아직 미구현이다.

아래는 2026-09-06의 역사적 단계이며 현재 우선순위를 대체하지 않는다.

2026-09-06 UTC. [통합 감사](PROJECT_INTEGRATION_AUDIT.md)를 바탕으로 한 제안이다. 아래 미완료 항목은 이번 문서화 작업으로 구현된 것이 아니다.

목표: **실패 조건 제안 → 서버 실행 → 유효성/실패 평가 → 다음 후보 개선 → 재현 가능한 보고서**를 하나의 연구 워크플로로 완성한다. 보행 모델 개선 자체가 프로젝트의 최종 목표는 아니다.

| 순서 | 작업 | 완료 기준 |
|---|---|---|
| M0 | 실험 계약·자원 provenance 정비 | 실제 실행 자원/코드/설정 digest, 판정·지표 버전, 유효 평가 예산 및 오류 비용이 저장·보고됨 |
| M1 | 첫 적응형 G1 method와 대조 실험 | 관측에 따라 제안이 변하고 재개 시 동일해짐; Random/Sobol과 같은 프로토콜로 비교 가능 |
| M2 | 서비스 견고성 및 최소 장애물 장면 | 동시 실행 제한·취소 상태 테스트; versioned primitive obstacle이 실제 물리에 반영됨 |
| M3 | 원격 실험 보고서·대시보드 | Client 보유 데이터로 진행/실패/무효/비용/영상·재현 조건 조회 가능 |
| M4 | 장면·정책 조건부 실패 생성 확장 | SceneGraph→Server 변환 검증, LAM-guided 효과의 대조 실험, 실패 축소·회귀 suite |

## 바로 다음 구현: M0

1. candidate, submitted rollout, valid evaluated rollout, invalid/indeterminate, infra error, retry/repeat의 의미와 집계를 명시한다. 수치 폭주는 정상적인 실패 발견으로 세지 않는다. 유효 예산만 쓰면 무한 재시도할 수 있으므로 총 시도·시간 상한도 둔다.
2. 요청 resource revision과 worker가 실제 사용한 XML/종속 자산/ONNX/config/code를 연결한다. 변경된 파일에 오래된 manifest가 그대로 적용되지 않도록 검증한다.
3. 원 정책과 path_hold를 다른 controller 조건으로 명시하고, evaluator/metrics version·seed·episode 길이·초기 조건·물리 설정을 protocol에 고정한다.
4. 중단/재개·반복·무효·재시도 시 예산 중복 집계 방지, 자원 mismatch 거부, 과거 manifest 호환 경계 테스트를 추가한다.

산출물: versioned protocol, 집계/manifest 코드·테스트, 작은 E2E 확인과 작업 이력. 기존 저장 증거를 덮어쓰거나 재분류하지 않고 새 버전으로 보존한다.

## M1: 최소 연구 비교

- 우선 현재 서버가 지원하는 friction/external force를 사용한다. 장애물이나 실사 인식 구현을 선행 조건으로 만들지 않는다.
- 기존 method protocol에 surrogate 기반 plugin 하나를 추가한다. 초기 탐색, 학습 데이터, acquisition, RNG·모델 상태 checkpoint를 명시한다.
- Random과 Sobol을 대조군으로 두고 manual은 사전 고정된 sanity/reference로 사용한다. 같은 domain·seed 목록·유효 rollout 예산·반복 정책을 적용한다.
- 실패 발견 수뿐 아니라 최초 실패까지의 비용, 고유 실패 다양성, 재실행 재현율, 무효율, wall time을 보고한다. 발견된 실패의 확인 반복 비용도 별도 공개한다.
- 기준선 sweep 결과를 보고 domain을 선택했다면 탐색용 자료와 최종 평가용 seed/조건을 분리한다. 결과가 나쁘더라도 보고하며 적응형 방법의 우월성을 완료 조건으로 삼지 않는다.

완료는 학습·재개·공정 비교가 실제로 작동하고 증거가 남는 것이다. 기존 AFS의 Panda margin을 G1에 그대로 이식하거나 import adapter를 적응형 방법으로 부르지 않는다.

## M2–M4 범위 제한

M2의 첫 장면은 primitive obstacle 하나로 시작하고 지원 operation·query·resource revision·영상에서 일치 여부를 검증한다. 광고하는 실행 용량과 실제 admission을 일치시킨 뒤 부하 시험한다.

M3는 Client archive/artifact를 읽는 보고 계층을 만든다. 기존 로컬 AFS UI를 없애지 않고 실행 backend와 데이터 출처를 표시한다. 요약표·실패 곡선·대표 영상·재현 명령을 제공한다.

M4에서 기존 scene3d 자산과 SceneGraph를 서버 계약으로 변환하고 LAM-guided 대조군을 추가한다. full pick/place, 실사 RGB-D, 실제 OpenVLA 검증은 별도 embodiment 과제로 두며 G1 보행 검증으로 대체하지 않는다. `g1-local-nav`는 해당 프로젝트 지침에 따라 계속 독립 유지한다.

모든 단계는 `.workhistory`에 변경 이유, 검증 명령·결과, 실험 경로와 미검증 사항을 남긴다. runtime 산출물의 기본 위치는 기존 `/workspace/g1_failure/runtime`를 유지한다.
