# 새 로봇 조건의 완화 장면 실행 준비

## 요청과 현재 상태

사용자는 AFS의 목적을 확인한 뒤 다음 실험 진행을 승인했다. 직전 0.5 배치의 실패와 비교하기
위해 상자를 더 옆으로 옮긴 0.75 장면 한 회를 실행할 범위다. 로봇·목표·10회 호출 예산은
유지하며, 추가 기준 반복·도전 0.25·AFS 유료 제안까지 확대하지 않는다.

**오프라인 비교 검증은 통과했으나, 에이전트 프로세스에 OPENAI_API_KEY가 없어 live 실행은
시작하지 않았다.** API 요청 0회, 로봇 rollout 0회, 새 실험 폴더·suite·DB 생성 0건이다.
성공·실패 라벨이나 새로운 영상도 없다. 사용자가 별도 터미널에 설정한 키가 이 프로세스에도
전달된다고 가정하지 않았고, 다른 프로세스·인증 파일에서 키를 찾거나 출력하지 않았다.

## 검증한 조건

기준 archive는 `/workspace/g1_failure/runtime/robot_goal_agent/20261003T150653_133405Z`다.
read_goal_run으로 71개 artifact 해시를 다시 검증했고 VALID/FAIL이 유지됐다. condition ID는
`eb42efe331685d6e51813b38195d27a88f50b1da77b25bd15cd9c296b42b95aa`다.

대상은 기존 suite의 `attempt_00001/scene_config.json`이다. scene schema 검증과 기준 설정
비교 결과, 유일한 변화는 `box_lateral_fraction: 0.5 → 0.75`다. 목표와 다른 환경 파라미터는
유지한다. 대상 scene revision은
`efe5ac6c08f587885ca356884195e0ea987534b529b226f9171c9f42321d3e82`다.

environment_fingerprint를 읽기 전용으로 계산해 기준 protocol과 대조했다.

- 기록된 소스 해시 25개가 현재 소스에 모두 존재한다.
- 로봇 XML·YAML·mesh·ONNX 등 기록된 자원 해시 52개가 일치한다.
- 기준에 기록된 MuJoCo·NumPy·ONNX Runtime 버전이 일치한다.
- Luna, 10회 호출, push 허용, HTTP read 300초, goal_dwell_v1 및 목표 계약이 일치한다.
- 시뮬레이션 기본 상한과 client 출력 토큰 상한은 추가하지 않는다.

이는 파일·설정·설치 버전 비교이지 실제 CUDA 추론이나 EGL 렌더링 실행 검증은 아니다.
이번 준비에서 GPU 모델 로딩·물리 step·외부 API 호출은 수행하지 않았다. 로봇 API 경로는
httpx를 직접 사용하므로 openai Python SDK의 미설치를 실행 차단 원인으로 판단하지 않았다.
현재 확인된 live 시작 차단 조건은 에이전트 프로세스의 키 부재다.

## 사용자 터미널 실행 명령

OPENAI_API_KEY가 설정된 RunPod 터미널에서 아래 한 회를 실행한다. 키 자체를 채팅에 공유할
필요는 없다. 최대 로봇 API 10회이며 새 AFS 호출·자동 유료 재시도는 없다. 기존 suite의
run/next를 재개하지 않고, 원본 scene JSON만 읽어 새 timestamp 폴더에 결과를 저장한다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --navigation-completion goal_dwell_v1 --scene-config /workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002/suite/attempts/attempt_00001/scene_config.json
```

기본 결과 경로는 `/workspace/g1_failure/runtime/robot_goal_agent/<새 실행 시각>/`이며 report와
MP4가 생성된다. GIF는 생성하지 않는다. 실행 후 원본 무결성·반환된 전체 condition ID·목표
결과·행동·비용을 확인한 뒤 직전 새 코드의 0.5 FAIL과 비교한다. 과거 코드의 0.75 PASS를
새 조건의 성공으로 대신 사용하지 않는다. 반대 결과가 나오더라도 단일 관측 구간이며 인과나
단조 경계를 확정하지 않는다.

## 기록과 보존

write-page 스킬의 구분 원칙에 따라 완료된 오프라인 검증과 아직 수행하지 않은 live 실험을
분리해 기록했다. 기존 미커밋 검토 문서와 AGENTS.md 변경을 보존하고 이번 준비 내역만 추가했다.
실행 코드, 기존 FAIL/PASS, 원본 산출물, 동결 suite 예산은 변경하지 않았다. Commit/push는
하지 않았으며 통로 폭 실험도 재개하지 않았다.
