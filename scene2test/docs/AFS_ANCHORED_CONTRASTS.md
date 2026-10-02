# 성공 기준 장면에서 시작하는 AFS 단일 축 대조

두 번 성공한 G1/Luna 조건을 그대로 두고 환경만 바꾸어 실패 조건과 성공 측면을 탐색한다.
`run_afs_contrast.py`는 기존 행동 메모리·단일 축 경계 선택·LLM 가설 선택과 고정 예산 실행기를
연결한다. 로봇의 목표·프롬프트·기술·보행 제어는 수정하지 않는다.

이 작업은 **외부 성공 기록을 사용하는 개발 탐색**이다. 기존 AFS/Random 캠페인을 재개하거나
그 결과에 표본을 추가하지 않는다. Random 대조군이 없으므로 Gain이나 AFS 우위를 계산하지 않는다.

2026-10-02 현재 통로 폭 실험은 사용자 요청으로 중단했다. 아래 폭 명령은 과거 실행 기록이며
지금 재개하지 않는다. 새로 승인된 작업은 [두 v4 성공 기록 기반 배치 제안](AFS_PAIRED_GOAL_CONTRASTS.md)이다.
`prepare-pair`와 `select-pair`로 별도 세션을 만들고 이 문서의 기존 실행·보고·후속 선택기를 재사용한다.

## 준비한 첫 실험

기준은 동일 조건에서 PASS인 두 사용자 실행이다. 새 실험 폴더는 다음과 같다.

`/workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002`

| 순서 | 통로 폭 | 목적 |
|---|---:|---|
| 1 | 4.0m | 기존 장면의 성공 대조 재실행 |
| 2 | 3.6m | 폭만 바꾸는 첫 대조 |
| 3 | 3.2m | 폭만 바꾸는 두 번째 대조 |

이 시작 값은 운영자가 정한 계획이며 LLM이 선택했다고 표시하지 않는다.
세 번 모두 실제 실행 전에는 성공/실패를 모른다. 좁은 통로가 반드시 실패한다는 가정도 없다.

장면 설정에서 `corridor_width_m`만 바꾼다. 다만 이 생성기는 물체의 Y 좌표를 폭과
`lateral_fraction`으로 계산한다. 따라서 벽뿐 아니라 상자·정적 장애물의 절대 Y 위치도
함께 변한다. **설정 한 축 대조**이지 여러 물체의 절대 좌표까지 고정한 인과 실험은 아니다.

모델 `gpt-6-luna`, 로봇 호출 10회/episode, `goal_outcome_v1`, `goal_dwell_v1`, push 허용,
HTTP read timeout 300초, simulation 무제한을 원본에서 상속한다. 최대 **3 rollout·로봇 API 30회**,
초기 장면 선택용 AFS 호출은 **0회**다. 과거 두 성공의 비용은 새 실행 비용과 별도로 표시한다.

`preview/index.html`은 실행 전 PNG 지도다. 그림의 선은 실제 궤적이나 로봇에게 주는 정답 경로가
아니다. 정적 경로 유무를 이유로 후보를 제외하거나 목표 결과를 판정하지 않는다.

## 실행 명령

API 키는 루트 README의 방법대로 현재 터미널에 설정한다. 키를 명령 인자나 문서에 쓰지 않는다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

준비된 실험에서 **다음 한 번만 실행**한다. 기본 상한도 1회이지만 아래에는 명시했다.

```bash
uv run --no-sync python tools/run_afs_contrast.py run --suite /workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002 --live --max-new-attempts 1
```

결과를 확인하고 같은 명령을 반복하면 다음 장면으로 넘어간다. 처음은 4.0m 대조,
그다음 3.6m, 마지막 3.2m다. 완료 후 반복해도 재실행하지 않는다.
`--max-new-attempts 3`은 남은 세 장면까지 연속 실행하므로 비용을 확인한 경우에만 사용한다.

상태와 보고서는 API 없이 확인한다.

```bash
uv run --no-sync python tools/run_afs_contrast.py status --suite /workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002
```

```bash
uv run --no-sync python tools/run_afs_contrast.py report --suite /workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002
```

`REPORT`의 장면별 실제 PASS/FAIL/제외 수, `behavior/index.html`의 반복 결과와 관측 경계,
각 `attempts/attempt_XXXXX/rollout/rollout.mp4`를 확인한다. GIF는 만들지 않는다.
`OBSERVED_FAIL`은 해당 환경에서의 목표 실패이며 로봇 코드가 퇴행했다는 뜻이 아니다.

## 결과로 다음 장면 선택

모든 계획 시도가 유효하게 완료된 후 다음 명령을 실행한다. 기본은 **유료 호출 없음**이다.

```bash
uv run --no-sync python tools/run_afs_contrast.py next --suite /workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002
```

선택 순서는 다음과 같다.

1. 같은 장면에서 PASS와 FAIL이 섞였으면 그 장면의 반복 1회를 준비한다. 혼합 결과를 경계로 단정하지 않는다.
2. 그 외에 같은 로봇 조건·한 축의 인접 PASS/FAIL 관측이 있으면 그 구간의 미측정 중점과 기준점 반복,
   총 2회를 준비한다. 예를 들어 3.2m FAIL / 3.6m PASS면 3.4m가 다음 후보가 된다.
3. 둘 다 없으면 실제 행동 요약·반복 횟수·SceneGraph·허용 축을 담은 `context.json`과
   `request.json`만 저장한다. 이 경우 다음 명령으로 **AFS LLM 최대 1회**를 요청할 수 있다.

```bash
uv run --no-sync python tools/run_afs_contrast.py next --suite /workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002 --live --model gpt-6-luna
```

경계/혼합 반복을 선택할 수 있으면 `--live`여도 LLM 호출은 하지 않는다. LLM 제안이 필요한 경우
기존 엄격한 schema·context hash·근거 ID 검사와 가설 우선 선택을 사용한다. 제안한 1–4개 공간의
양 끝점 중 **후보 하나**만 고르고 나머지 축은 기준 장면과 같게 유지한다. 이미 관측한 후보와
유사 실패 반복 주변은 기존 중복/cooldown 규칙으로 거른다. 모두 거절되면 오류로 멈추며
몰래 Random으로 대체하지 않는다. 실패가 계속되면 완화/다른 축 가설을 제안하도록 한다.

새 요청의 `anchored-contrast-endpoint-v1` 설명은 이 개발 절차에만 적용된다. 기존 비교 캠페인의
고정 exploration/repeat 순환이 이 도구에도 있다고 설명하지 않는다. 실제 역할·선택 절차를
명확히 하는 원칙은 [OpenAI 프롬프트 지침](https://developers.openai.com/api/docs/guides/prompt-engineering)을 참고했다.

`next`는 **새 로봇을 실행하지 않는다.** 출력된 `CONTRAST_SUITE` 경로에 대해 `run --live`를
별도로 실행해야 한다. 혼합 반복이면 최대 로봇 API 10회, 중점/LLM 후보+기준 반복이면 최대 20회다.
새 경계는 실제 실행 후에만 관측값으로 보고한다. 단조성·원인·최소 실패 조건의 증명은 아니다.

한 라운드씩 예산을 검토하는 도구이며 무제한 자동 탐색 루프는 아니다. 누적 이력은 최대 32개
입력 archive다. 범위를 넘으면 명시적으로 중단하며 오래된 근거를 몰래 버리지 않는다.

## 실패와 재개

- 코드·자원·의존성은 init 때 고정한다. 원본 로봇 소스/자원/runtime 해시도 실행 전에 검사한다.
  실행 후에는 원본과 전체 `condition_id`가 같은지 검사하므로 반환 모델 등의 차이는 제외한다.
- INCONCLUSIVE·불완전 실행·조건 변경은 목표 FAIL이 아니다. 제외도 계획 시도 예산을 소비한다.
  원인 확인 후 `run`에 `--continue-after-exclusion`을 명시하면 남은 계획만 실행한다. 대체 시도는 없다.
- 완료 여부가 불명인 pending은 자동 재전송하지 않는다. 완결된 archive가 있으면 재실행 없이 수집한다.
  프로세스가 끝났고 증거가 없음을 직접 확인한 경우에만 `resolve --note "확인 내용"`를 사용한다.
- 제외가 있는 계획에서는 `next`가 자동 후속 탐색을 하지 않는다. 제외 원인을 먼저 검토하고
  사용 가능한 근거로 새 계획을 명시적으로 만들어야 한다.
- LLM 실패 시 `intent.json`, `request.json`, 가능한 `response.json`/`usage.json`, `error.json`을 보존한다.
  자동 재시도는 없다. 저장된 응답이 있다면 `next --response 응답파일 --output-dir 새폴더`로
  **추가 호출 없이** 같은 근거에 다시 검증할 수 있다. 오류 파일은 검증 없이 수정하지 않는다.
- 토큰 누락은 0원이 아니다. 선택 요청 비용은 새 계획의 `selection_costs`에 별도로 남는다.
  실패해 새 계획으로 연결되지 못한 요청의 비용도 요청 폴더에 남으므로 전체 비용 점검 시 포함한다.
- 코드가 바뀐 뒤 기존 계획을 강제로 재개하지 않는다. 로봇 코드까지 바뀌면 동일 조건의 새 기준
  증거가 필요하다. 원본 캠페인·기존 FAIL·영상은 그대로 보존한다.

## 새 계획 만들기

아래는 위 계획을 다시 만드는 명령이다. 기존 출력 폴더가 있으면 덮어쓰지 않고 거부한다.
`init` 대신 `plan`을 쓰고 `--output-dir`을 빼면 파일 생성 없는 오프라인 검사다.

```bash
uv run --no-sync python tools/run_afs_contrast.py init --run /workspace/g1_failure/runtime/robot_goal_agent/20261002T060144_446312Z --run /workspace/g1_failure/runtime/robot_goal_agent/20261002T080932_214891Z --axis corridor_width_m --values 3.6 3.2 --output-dir /workspace/g1_failure/runtime/afs_contrast/navigation_v3_width_20261002
```

다른 축도 원본 장면 schema가 지원하면 지정할 수 있다. 예를 들어 장애물 측면 배치나 바닥 마찰을
한 번에 한 축씩 시험한다. 이번 범위에 점프·새 조작 기술·새 평가 규칙은 추가하지 않았다.
