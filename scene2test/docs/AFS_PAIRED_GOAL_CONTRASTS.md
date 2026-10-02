# 두 성공 행동을 이용한 AFS 목표 주변 배치 탐색

검토된 빈 목표·부분 점유 성공 기록을 AFS에 제공하고, LLM이 상자의 측면 위치 두 개를
제안한다. 부분 점유 성공 장면은 고정 기준이다. 기존 실행기로 **기준 반복 1회와 새 배치
2회**를 실행한다. 로봇의 행동·목표·평가·예산은 바꾸지 않는다.

이것은 외부 성공 이력을 사용하는 개발 탐색이다. 기존 AFS/Random 캠페인이나 중단한
통로 폭 실험을 재개하지 않는다. Gain, 실패 확률, 단조 경계 또는 원인을 입증하는 실험이 아니다.
이번 구현에서는 API나 로봇을 실행하지 않았으며, 아래 명령의 `--live`는 별도 유료 단계다.

## 입력과 후보 선택

입력은 다음 실제 성공 기록 두 개다. 마지막 `--run`이 기준 장면이며 LLM이 기준을 고른 것은 아니다.

| 근거 | 상자 측면 fraction | 실제 결과 | 실제 행동 |
|---|---:|---|---|
| 빈 목표 20261002T141132_394018Z | 1.0 | PASS, 4회 호출 | 최종 목표로 navigate_to |
| 부분 점유 20261002T143326_488034Z | 0.5 | PASS, 10회 호출 | 계획 거절, 중간 목표, 직접 move |

같은 로봇 조건·자산·목표·예산을 검증한 뒤 SceneGraph, 목표 계약, P1 행동 계측,
두 실행의 전체 행동 요약과 선택된 상세 구간을 전달한다. 요약은 전체 영상 전송이 아니다.
첫 계획 거절만 보고 후반 직접 이동 성공을 놓치지 않도록 행동 요약은 모두 보존한다.
두 실행에서 상자가 움직이지 않았다는 사실을 밀기 실패로 바꾸지 않는다.

새 진입점은 초기 성공 대조 전용이다. 같은 v4 조건의 서로 다른 성공 장면 2–8개를 받고,
상자 측면 위치 외 차이·중복 archive·FAIL/혼합 결과·불완전 근거를 거부한다. 이후 실제
성공/실패 결과를 이용한 반복과 경계 선택은 기존 `next` 경로에서 수행한다.

LLM은 다음 항목을 JSON으로 반환한다.

- 고정된 context hash, 기준 case ID, 변경 축 `box_lateral_fraction`.
- `relief`: 기준보다 큰 측면 fraction, 가설·예상 관측·반증 조건·실제 근거 ID.
- `challenge`: 기준보다 작은 측면 fraction, 같은 설명 항목.

현재 기준에서 `0 <= challenge < 0.5 < relief <= 1`이어야 하며, 이미 관측한 0.5와 1.0은
후보로 재사용하지 않는다. 같은 양의 Y 쪽에서 접근 공간을 줄이거나 늘리는 배치 대조다.
반대편 배치·질량·마찰 변경은 이번 고정 범위에 포함하지 않는다. 따라서 LLM이 쓸 수 있는
장면 도메인 전체 18축과 이번 요청에서 허용하는 한 축은 다르다.

`relief`와 `challenge`는 기하 배치 가설의 이름이지 성공·실패 라벨이 아니다. 실제 난이도가
단조라는 보장은 없다. 값은 코드에 고정하지 않고 LLM이 선택한다. 범위·방향·신규성·근거 ID·
컨텍스트를 호스트가 재검증하며, 잘못된 제안은 중단하고 보존한다. Random 대체는 없다.
정적 no_path를 이유로 장면을 제외하지 않고, 로봇에게 중간 목표나 밀기를 지시하지 않는다.

## 실행 단계와 비용

다음 명령은 프로젝트의 기존 RunPod 환경을 전제로 한다. 키 설정은
[루트 README](../../README.md#openai-api-키-설정-및-afs-전체-실행-runpod--bash)를 따른다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

### 1 오프라인 준비

이 작업 환경에서는 아래 세션을 이미 준비했다. 그대로 사용할 때는 **2단계부터** 진행한다.

새 세션을 만들 때만 사용한다. 기존 폴더가 있으면 덮어쓰지 않고 거부한다.
API·GPU·물리 step 없이 원본과 현재 소스·외부 자산·의존성을 확인하고 요청을 저장한다.

```bash
uv run --no-sync python tools/run_afs_contrast.py prepare-pair --run /workspace/g1_failure/runtime/robot_goal_agent/20261002T141132_394018Z --run /workspace/g1_failure/runtime/robot_goal_agent/20261002T143326_488034Z --model gpt-6-luna --output-dir /workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002
```

### 2 AFS 제안 한 번

현재 터미널에 `OPENAI_API_KEY`를 설정한 후 실행한다. **Luna AFS 요청 최대 1회이며 로봇은
실행하지 않는다.** 성공하면 기준·완화·도전 장면의 JSON과 PNG 미리보기, 실행 대기 보고서를 만든다.

```bash
uv run --no-sync python tools/run_afs_contrast.py select-pair --session /workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002 --live
```

`CONTRAST_SUITE`는 위 세션 아래 `suite`, `PREVIEW`는 `suite/preview/index.html`이다.
준비 단계에는 아직 LLM이 선택한 값이나 새 장면이 없다. 임의의 예제 값을 실제 제안처럼 넣지 않는다.

### 3 로봇을 한 장면씩 실행

제안과 미리보기를 확인한 뒤 실행한다. 처음은 기존 부분 점유 반복, 두 번째는 relief,
세 번째는 challenge다. 같은 명령을 단계별로 반복하면 남은 다음 장면만 실행한다.

```bash
uv run --no-sync python tools/run_afs_contrast.py run --suite /workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002/suite --live --max-new-attempts 1
```

원본 조건인 Luna, 10회 호출/episode, push 허용, goal_outcome_v1, goal_dwell_v1,
HTTP read 300초를 상속한다. 세 장면 합계 **최대 로봇 API 30회 + AFS 1회**다.
호출 수는 금액 상한이 아니다. 기본 출력 토큰 상한·시뮬레이션 상한은 추가하지 않는다.
제외 실행도 3회 예산을 소비하며 자동 대체·재시도하지 않는다. 완료 후 같은 명령을 쳐도
추가 실행하지 않는다. 원본 성공 비용, AFS 제안 비용, 새 로봇 실행 비용은 구분한다.

## 결과 확인과 후속 선택

```bash
uv run --no-sync python tools/run_afs_contrast.py report --suite /workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002/suite
```

보고서는 배치별 목표 결과·호출 수·마지막 저장 표본의 목표 거리·행동 수·MP4를 비교한다.
`paired_comparison.json`에는 제안 가설·반증 조건과 각 실행의 전체 행동 요약을 연결한다.
가설 판정은 `NOT_ADJUDICATED`로 남긴다. 행동 차이만으로 인과를 자동 확정하지 않는다.
원본 마지막 표본의 거리/체류가 full-rate 최종 평가와 조금 다를 수 있으며 목표 판정은 유지한다.
MP4는 실제 실행 후에만 생긴다. GIF는 생성하지 않는다.

세 시도가 제외 없이 완료된 경우 다음 명령으로 후속 계획을 준비한다. 기본은 API 호출 없음이다.

```bash
uv run --no-sync python tools/run_afs_contrast.py next --suite /workspace/g1_failure/runtime/afs_contrast/goal_region_lateral_20261002/suite
```

같은 조건에서 결과가 섞이면 반복부터, 그렇지 않고 관측 PASS/FAIL 구간이 있으면 중점과
기준 반복을 제안한다. 전부 성공하면 다음 LLM 요청만 준비한다. 모두 기존 기능을 재사용한다.
어느 경우도 새 로봇 실행을 자동으로 시작하지 않는다. 각 후속 단계는 별도 예산 검토 대상이다.

## 오류와 보존 규칙

- 요청 직전에 SQLite intent를 기록하고 프로세스 잠금으로 동시 유료 요청을 막는다.
  응답을 기다리다 중단돼도 같은 세션에서 자동 재전송하지 않는다.
- 응답이 저장되어 있으면 `select-pair`는 재호출 없이 그 응답을 검증한다. 검증 실패 시
  `response.json`, `usage.json`, `error.json`을 보존한다. 완료된 suite도 다시 만들지 않는다.
- 명시적 `--response /path/to/response.json`으로 저장 응답을 가져올 수 있으나 정확히 같은
  컨텍스트여야 한다. 이미 저장된 응답을 다른 내용으로 덮어쓰지 않는다. 수동 반입 응답은
  제공자 서명이 아니며 외부 호출의 기존 비용을 0으로 간주하지 않는다.
- API timeout/미완료·스키마 거절은 로봇 FAIL이 아니다. 수신하지 못한 usage는 unknown이다.
- 코드·자산·의존성이나 근거가 바뀌면 유료 호출 전과 후 모두 거부한다. 기존 세션의 잠금을
  우회하지 않는다. 이번 코드 변경 후 옛 동결 suite를 재개하지 않는다.
- 키는 요청/문서에 저장하지 않는다. 기본 HTTP 호출은 재시도하지 않는 기존 provider를 쓴다.

요청 형식은 기존 Responses API의 strict JSON schema 경로를 재사용했다.
[OpenAI Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs)의
구조 제약 외에도 호스트에서 근거·수치·실험 설계 의미를 검증한다. 스키마 준수만으로 가설이
옳아지거나 실패 경계가 입증되는 것은 아니다.
