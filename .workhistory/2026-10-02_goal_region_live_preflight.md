# 목표 주변 첫 실동작 검증의 실행 준비 점검

2026-10-02 UTC. 사용자는 새 장면 한 개의 실제 로봇 실행을 진행하도록 요청했다.
목표가 비어 있는 `goal_region_clear.json`을 Luna 최대 10회 호출로 실행할 계획이었다.
현재 에이전트 실행 환경에는 `OPENAI_API_KEY`가 없어 유료 실행을 시작하지 않았다.
대신 새 장면의 자산 합성, EGL 렌더링, 실제 보행 모델의 CUDA 로딩과 단일 추론까지 확인했다.

## 확인한 상태

- 에이전트 프로세스의 `OPENAI_API_KEY`: MISSING. 키 값은 읽어 출력하거나 저장하지 않았다.
- GPU: NVIDIA RTX PRO 4500 Blackwell, 총 32623 MiB. 점검 직전 사용 2 MiB, 사용률 0%.
- ONNX Runtime: CUDAExecutionProvider가 있으며, 실제 세션의 첫 제공자도 CUDAExecutionProvider였다.
- EGL: 별도 최소 장면을 64 × 64 RGB로 렌더링했다. GPU 렌더링 초기화 오류는 재현되지 않았다.
- 새 목표영역 장면과 실제 G1 XML 합성: 관절 identity·보행 observation 보존, 구동기 29개.
- 실제 실행과 같은 `ArmGaitController`를 생성하고 GR00T Walk 모델을 GPU에 로드했다.
  초기 상태 observation을 사용한 입력 `[1,516]`에서 출력 `[1,15]`를 얻었고 모든 값이 유한했다.
- 이 과정에서 `mj_step`은 실행하지 않았다. 물리 스텝 0, 시뮬레이션 시각 0초,
  외부 API 호출 0, robot rollout 0, 목표 결과 NOT_EXECUTED다.

장면 schema는 `clear-path-goal-region-v4`, scene revision은
`6e2cae7c8db12c9f0434f8ab93565a3ddc2eb53cd41380f78c990cc96f07d7b6`다.
GPU에 모델을 올리고 한 번 추론한 사실은 보행·목표 도달 성공을 의미하지 않는다.
수치와 진단은 이번 도구 실행 출력에 근거하며 새 실험 archive가 생성된 것은 아니다.

## 중단 사유와 다음 실행

로컬 `run_robot_goal_agent.py`는 live 실행 전에 키가 없으면 종료한다.
`robot_vlm/api_transport.py`도 `OPENAI_API_KEY`를 인증에 사용한다.
사용자가 다른 터미널에 설정한 환경 변수가 에이전트의 별도 실행 환경에 전달되었다고
가정할 수 없다. 인증 파일이나 다른 프로세스에서 키를 탐색·추출하지 않았다.

키를 설정한 사용자의 RunPod 터미널에서 다음 한 회를 실행하면 된다.
키 설정은 [README](../README.md)의 기존 안내를 따른다. 키 자체는 채팅이나 Git에 남기지 않는다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --navigation-completion goal_dwell_v1 --scene-config config/scenes/goal_region_clear.json
```

실행되면 기존 기본 경로 `/workspace/g1_failure/runtime/robot_goal_agent/<새 시각>/` 아래
report와 MP4가 생성된다. 이번에는 rollout 자체가 없어 새 MP4·GIF·실패 표본도 없다.
부분/전체 점유 장면과 12회 AFS 캠페인은 자동 실행하지 않았다. 기존 실험·판정·예산은
보존했으며 robot/AFS 실행 코드를 바꾸지 않았다. Commit/push도 하지 않았다.

문서화에서는 실제로 확인한 GPU 추론과 아직 하지 못한 로봇 실동작을 구분했다.
실험 결과를 받은 뒤 goal 판정·행동·사용량·영상과 archive 무결성을 검토해야 한다.
