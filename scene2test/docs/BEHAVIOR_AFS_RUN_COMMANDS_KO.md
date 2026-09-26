# 행동 기반 AFS 실행 명령어

명령어를 한 줄씩 복사해서 **동일한 Bash 터미널**에서 순서대로 실행하세요.
`root@...#` 같은 프롬프트나 Markdown의 코드 블록 표시(` ``` `)는 복사하지 않습니다.
아래 명령어에는 줄 연결용 역슬래시가 없습니다.

## 1. 작업 디렉터리 이동

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

## 2. API 키 설정

먼저 다음 **한 줄만** 실행합니다.

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY
```

입력 대기 상태에서 실제 API 키를 붙여넣고 Enter를 누릅니다. 화면에 키가 보이지
않는 것이 정상입니다. 키 입력을 마친 뒤 아래 명령을 각각 실행합니다.

```bash
echo
```

```bash
export OPENAI_API_KEY
```

키 값을 출력하지 않고 설정 여부를 확인합니다. 이 검사는 키의 유효성이나 모델
접근 권한을 확인하는 검사가 아니라, 값이 들어 있는지만 확인합니다.

```bash
if [ -n "$OPENAI_API_KEY" ]; then echo "API 키 설정됨"; else echo "API 키 없음"; fi
```

새 터미널을 열면 다시 설정해야 할 수 있습니다. 키를 문서, 채팅, Git에 저장하거나
`echo "$OPENAI_API_KEY"`로 출력하지 마세요.

## 3. 직전 실험을 분석해 AFS 후보 생성

아래 명령은 GPT를 한 번 호출해 새 환경 후보를 생성합니다. **로봇은 아직 실행하지
않습니다.** 기존 실험 폴더가 현재 환경에 있어야 합니다.

```bash
uv run python tools/run_behavior_afs.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260921T155205_243359Z --live --model gpt-6-astra
```

정상 완료 시 `BEHAVIOR_AFS_RUN=...` 및 `SUITE=...; ready=...; origin=openai_api`가
출력됩니다. 오류가 발생하면 여기서 멈추고 출력 내용을 확인하세요. 폴더 경로만
출력됐다고 후보 생성까지 성공한 것은 아닙니다.

## 4. 생성된 AFS 폴더 경로 지정

다음 한 줄을 실행한 뒤, 입력 대기 상태에 **방금 출력된 BEHAVIOR_AFS_RUN의 값만**
붙여넣고 Enter를 누릅니다. `BEHAVIOR_AFS_RUN=` 접두어나 따옴표는 넣지 마세요.

```bash
read -rp "BEHAVIOR_AFS_RUN 경로: " AFS_RUN
```

예상 경로 형태는 `/workspace/g1_failure/runtime/behavior_afs/날짜_시간/`입니다.
출력된 정확한 경로를 사용하며, 이 예시 문자열을 그대로 입력하지 않습니다.

suite와 최초 두 후보 파일이 존재하는지 확인합니다.

```bash
ls "$AFS_RUN/suite.json" "$AFS_RUN/candidate_000.json" "$AFS_RUN/candidate_001.json"
```

파일이 없으면 로봇을 실행하지 말고 suite의 후보 상태와 오류를 먼저 확인하세요.
후보 번호는 무게/마찰 중 어느 변수에 해당하는지 고정돼 있지 않습니다.

```bash
uv run python -m json.tool "$AFS_RUN/suite.json"
```

## 5. 원본 환경에서 비교 기준 실행

`candidate_000.json`은 원본 환경의 반복 실행입니다. GPU와 로봇용 GPT 호출을
사용합니다. 먼저 이 명령이 완료될 때까지 기다리세요.

```bash
uv run python tools/run_robot_goal_agent.py --live --model gpt-6-astra --max-calls 10 --enable-push --response-timeout 300 --scene-config "$AFS_RUN/candidate_000.json"
```

출력된 `ROBOT_GOAL_AGENT_RUN` 경로를 기록합니다.

## 6. 첫 번째 변경 환경 실행

앞의 로봇 실행이 종료된 뒤 실행합니다. 모델과 호출 예산 등 다른 조건은 동일하게
유지합니다. 여러 로봇 실험을 동시에 실행하지 마세요.

```bash
uv run python tools/run_robot_goal_agent.py --live --model gpt-6-astra --max-calls 10 --enable-push --response-timeout 300 --scene-config "$AFS_RUN/candidate_001.json"
```

이 실행의 `ROBOT_GOAL_AGENT_RUN` 경로도 기록합니다. 결과는
`/workspace/g1_failure/runtime/robot_goal_agent/` 아래에 저장됩니다.
각 실행에는 report.html, rollout.mp4, rollout.gif 및 상세 로그가 생성됩니다.
초기 실행 오류가 발생한 경우에는 영상이 없을 수 있으므로 error.json을 확인합니다.

## 결과 전달

다음 세 경로와 종료 reason을 전달하면 비교 분석할 수 있습니다.

- AFS 후보 생성 폴더: `BEHAVIOR_AFS_RUN`
- 원본 환경 실행 폴더: 첫 번째 `ROBOT_GOAL_AGENT_RUN`
- 변경 환경 실행 폴더: 두 번째 `ROBOT_GOAL_AGENT_RUN`

`BUDGET_EXHAUSTED`는 GPT 호출 10회를 소진했다는 뜻이며, 그 자체가 API 오류나
넘어짐을 의미하지는 않습니다. 로봇 실행은 별도 시뮬레이션 시간 상한 없이
수행되지만 GPT 호출 수와 개별 응답 대기 제한은 유지됩니다.

설계와 한계는 [BEHAVIOR_AFS.md](BEHAVIOR_AFS.md)를 참고하세요.
