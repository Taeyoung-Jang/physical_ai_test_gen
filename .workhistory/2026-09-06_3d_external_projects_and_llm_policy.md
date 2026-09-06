# 3D 외부 프로젝트와 LLM 행동 정책 가능성 검토

2026-09-06 UTC. 사용자 질문에 대한 문서 기반 검토이며 설치·모델 다운로드·유료 API 호출·새 시뮬레이션은 하지 않았다.

## 3D 처리

객체별 변형에는 semantic segmentation뿐 아니라 instance segmentation과 mesh/point ownership 매핑이 필요하다. 분류 라벨만으로 객체별 실행 형상이 생기지는 않는다.

- ConceptGraphs: posed RGB-D → 2D masks/features → 객체별 3D map/graph. 시점·depth가 있는 입력의 1차 참고 후보. raw XYZ 파일만의 입력과 동일하지 않다.
- OpenMask3D: 3D instance masks와 다중 시점 이미지 특징으로 open-vocabulary 해석. 공식 single-scene 입력은 point cloud 외 RGB/depth/pose/intrinsics를 요구한다.
- Pointcept/PTv3: point-cloud perception 및 semantic segmentation 참고. backbone 자체가 완성된 instance/scene graph 생성기는 아니다. 데이터 도메인, checkpoint/코드 호환, CUDA 의존성 검증 필요.

도입 전 입력 데이터의 texture/RGB, instance annotation, camera pose/depth 유무부터 확인하고 한 프로젝트만 격리 환경에서 검증하는 것을 권고한다. 재분할 대상은 task 관련 객체로 제한할 수 있다. 동적 mesh 편집이 어려우면 원본 scene을 고정 배경으로 두고 개별 asset을 삽입하는 방법이 가능하나, 이는 기존 가구 이동 능력의 입증은 아니다.

## 범위 조절

임의 실측 3D 인식을 처음부터 완성해야만 AFS를 연구할 수 있는 것은 아니다. annotation/procedural ground-truth SceneGraph 경로로 탐색 코어를 검증하고, 자동 인식 경로를 같은 그래프 계약으로 비교한다. 인식 정확도와 실패 탐색 효과를 구분한다. 수동 보정은 기록하고 자동 인식으로 주장하지 않는다.

## GPT 기반 정책

OpenAI Docs 스킬과 공식 모델 페이지를 사용해 GPT-6 Astra의 image input, function calling, structured outputs 지원을 확인했다. API 기능 지원은 로봇 제어 성능 증거가 아니다.

GPT를 고수준 행동 선택기로 사용하고 action adapter/planner와 기존 locomotion controller로 실행하는 계층형 구조는 구현 후보이다. waypoint navigation이나 obstacle avoidance skill은 현 보행 컨트롤러에 이미 있다고 가정하지 않는다. 허용 action schema, 속도/시간 제한, timeout/invalid-action 처리, 관측 후 재계획이 필요하다.

테스트 생성자와 시험 대상 정책의 대화/데이터를 분리하고 AFS 가설·평가 정답을 정책에 노출하지 않는다. perceived graph와 simulator truth를 구분한다. 평가를 같은 LLM의 자체 판정에 맡기지 않는다. 외부 전송 범위와 호출 예산을 정한 뒤 실행해야 한다.

## 출처

- https://github.com/concept-graphs/concept-graphs
- https://github.com/OpenMask3D/openmask3d
- https://github.com/Pointcept/PointTransformerV3
- https://developers.openai.com/api/docs/models/gpt-6-astra

공식 README/API 문서 검토에 기반한 후보 비교이며 이 환경에서의 설치 가능성·성능·VRAM·실측 비용은 아직 검증하지 않았다. 전체 계획의 무단 변경이나 g1-local-nav 병합은 하지 않았다.
