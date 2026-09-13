# 절차적 환경 생성 및 G1 내비게이션 구성 검토

2026-09-06 UTC. 질문에 대한 설계 제안이며 환경 생성기·내비게이션 구현이나 유료 API 실행은 하지 않았다.

## 환경 생성 제안

seed/config/generator version을 입력으로 방·통로 연결 topology를 먼저 생성하고, 벽/문/장애물의 metric geometry를 배치한다. 미로는 randomized DFS/Prim, 방 배치는 공간 분할과 연결 그래프를 후보 알고리즘으로 둔다. 최초 범위는 단층 평면 이동과 3D 벽/장애물이며 계단·복층·동적 장애물은 구분한다.

하나의 SceneSpec에서 MuJoCo 실행 장면, SceneGraph, navigation occupancy/cost map을 생성한다. SceneGraph와 navigation graph를 동일시하지 않는다. ID/좌표계/크기/revision을 교차 검증하고 그래프만 변경하는 상황을 방지한다. 기존 G1 robot/actuator/sensor 및 joint ordering은 유지한다.

통로 연결성, robot footprint와 여유를 고려한 경로, 시작/목표 겹침, 장애물 배치 유효성을 검증한다. 정적 경로 존재는 동역학 보행 성공 보장이 아니다. seed 외 최종 장면 자체도 저장한다. AFS에서는 고정 base scene/task에 대한 bounded mutation을 별도로 기록한다.

## 내비게이션 구성

현재 G1OnnxController._observation은 명령·자세·관절 상태·이전 action을 입력으로 사용하며 지도/목적지/장애물 입력이 없다. 현 정책은 GR00T-WholeBodyControl-Balance/Walk ONNX이며 Unitree의 완전한 자율주행 소프트웨어를 실행 중인 것이 아니다.

추가 구성: 기준선용 GT pose/map → global path planner → waypoint follower/local collision-aware velocity selection → 기존 gait controller. 처음에는 GT 기반 known-map navigation으로 계약을 검증하고, 이후 perception/localization 조건을 별도 실험으로 둔다. GPT는 선택 사항이며 semantic goal/waypoint 선택에 사용 가능하지만 관절 제어 대체물은 아니다. path_hold는 일반 waypoint follower가 아니다.

## 공식 제공 범위 확인

- Unitree SDK 및 MuJoCo 공개 프로젝트 존재: https://github.com/unitreerobotics/unitree_sdk2 , https://github.com/unitreerobotics/unitree_mujoco
- 사용 중인 계열 설명: https://github.com/NVlabs/GR00T-WholeBodyControl/blob/main/docs/source/references/decoupled_wbc.md
- OpenAI Docs 스킬을 읽고 GPT-6 Astra 공식 모델 문서 확인: https://developers.openai.com/api/docs/models/gpt-6-astra

이 출처만으로 Unitree 모든 제품/옵션의 자율 내비게이션 제공 여부를 단정하지 않는다. SDK/시뮬레이터 제공과 현 MuJoCo 환경에서 바로 실행 가능한 미로 내비게이션 제공은 다른 문제이다. 계정 권한·외부 모델 비용·새 환경 성능은 미검증이다.
