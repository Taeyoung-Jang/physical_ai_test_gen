# 원 설계에 따른 SceneGraph 중심 계획 재검토

날짜: 2026-09-06 UTC. 사용자 요청: 최근 제안에 휘둘리지 말고 원래 SceneGraph 기반 AFS 계획을 다시 검토할 것.

## 근거와 판단

- `.blueprint/00_blueprint.md` §2/4.2: SceneGraph → 변형 공간 → 초기 실행 → robustness → surrogate/acquisition → 다음 장면 → 반례/보고서가 핵심이다.
- `.blueprint/01_blueprint.md` §2/5: LAM-guided는 행동 관측으로 후보를 생성해 기존 mutation/AFS 후보 풀로 재투입하는 확장이다. 별도의 대체 목적이 아니다.
- `.blueprint/CLIENT_ARCHITECTURE.md` §19 C2/C3 및 §21: 최소 snapshot/world model, generic intervention, G1 3m navigation의 primitive obstacle baseline을 명시한다. 알고리즘 교체 가능성을 유지하며 완전한 semantic graph/SDF는 선행 요구가 아니다.
- `scene_graph.py`에 객체·역할·관계·불확실 영역 표현이 이미 있다. `scene3d/sources.py`는 HM3D/mesh/JSON 경로가 있지만 raw mesh의 의미 분해는 제공하지 않는다.
- Client `world_model/projector.py`는 snapshot의 task 관련 객체 등을 투영한다. 실제 MuJoCo 장면과의 일치 또는 기존 SceneGraph 관계의 완전한 전달을 이것만으로 보장하지 않는다.
- Server worker/controller는 알려진 XML을 로드하며 현 operation은 spawn/friction/external force 중심이다. 기존 그래프의 장애물 변형을 실제 G1 물리에 반영하는 연결은 미완성이다.

이 근거에 따라, 직전 PROJECT_ROADMAP의 SceneGraph 연결을 M4로 미룬 순서와 대화상의 friction/force AFS 우선 제안을 수정 권고한다. 감사의 개별 구현 사실과 테스트 결과를 철회하는 것은 아니며, 계획의 우선순위 판단을 바로잡는다.

## 수정 권고 순서

1. 기존 SceneGraph/Client snapshot/실제 실행 장면의 대응을 정하고, 작은 장면 하나의 객체 ID·좌표계·크기·역할·변형 가능 범위를 일치시킨다. 기존 표현을 재사용하고 필요한 adapter만 만든다.
2. 장애물 하나의 위치 또는 크기를 바꾸어 graph mutation → server intervention → 실제 geometry → 결과/영상까지 수동 E2E로 확인한다. spawn 겹침 등 잘못된 장면을 실패 발견과 구분한다.
3. 같은 장면 표현·변형 공간·평가 기준으로 Random/Sobol 기준선과 AFS의 학습/선택/재평가 루프를 연결한다. G1 작업에 맞는 지표를 사용하며 Panda margin을 그대로 대입하지 않는다.
4. 실제 정책의 관측/action 계약을 확인하고 모델을 연결한 뒤 행동 로그 기반 guided 후보를 동일 장면/AFS 후보 흐름에 통합한다. 기존 G1 저수준 보행을 장면 인식·회피 정책으로 간주하지 않는다.

최소 seed/version/budget 기록은 각 단계와 함께 적용한다. 완전한 재현성 인프라, 실사 perception, 대시보드를 첫 장면 루프의 선행 조건으로 만들지 않는다. 마찰·외력 실험은 보조적인 dynamics 검증 자산으로 보존한다. G1 경로를 유지하고 Panda로 자동 회귀하거나 독립 g1-local-nav 프로젝트를 병합하지 않는다.

## 이번 작업 범위

설계·관련 코드 읽기 및 본 기록 작성만 수행했다. 로드맵 본문 교체, 실행 코드 수정, 새 실험은 수행하지 않았다. 앞선 감사의 55개 테스트 통과는 이전 검증이며 이번 검토에서 재실행하지 않았다.
