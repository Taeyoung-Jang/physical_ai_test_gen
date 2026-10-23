# 다양한 실패 발견을 위한 자동 AFS

2026-10-18: 축 변화보다 실패 가설을 우선하는 새 선택기
[failure-directed-v2](AFS_FAILURE_DIRECTED.md)를 추가했다. 아래는 기존 discovery-v1의
계약이며, 이미 만든 세션은 그 조건을 보존한다.

`discovery-v1`은 검토된 성공·실패 아카이브를 출발점으로 여러 환경 조건을 탐색한다.
기존 `alternating-v1`과 달리 자동 반복과 경계 중간값 슬롯 없이 매회 LLM에 새 가설을
요청한다. 외부 이력을 사용하는 개발 탐색이며 독립 AFS/Random 비교나 Gain 추정은 아니다.

## 선택과 측정

자율 탐색 제안은 구체적인 `axis + value`를 기본으로 사용한다. 기존 `axis + low + high`
범위도 지원하지만 `low < high`여야 한다. 두 형식을 섞거나 동일 끝점 범위를 일반
실행에서 자동 보정하지 않는다. 단일 값도 허용 범위·축 쿼터·최소 변화·중복·근거 검사를
동일하게 받는다. 환경은 회차 시작 전에 확정하고 실행 중에는 AFS가 개입하지 않는다.

출력 스키마는 두 객체 형식을 중첩 `anyOf`로 구분하고 모든 필드를 required,
추가 필드는 금지한다. 이는 [OpenAI 공식 Structured Outputs 규칙](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)에 따른다.
허용 축에 따른 수치 검사는 호스트에서도 별도로 수행한다.

현재 장면의 파라미터 하나만 변경한다. 쿼터와 직전 축 cooldown을 적용한 뒤,
가장 적게 시도한 축들을 제안 가능 목록으로 제한한다. 각 후보는 해당 축의 전체
허용 범위 대비 최소 10%를 변경해야 한다. 작은 후보는 선택 감사에 제외 사유를 남긴다.
LLM이 제시한 유효 후보 중 다른 메커니즘 가설을 우선하고, 제안 순서와 신규성으로
선택한다. 축 종류가 많다는 이유로 실패 유형을 발견했다고 세지 않는다.

로봇 모델·목표·호출 예산·밀기 가능 여부·완료 조건은 기준 아카이브에서 고정한다.
AFS는 로봇 명령을 지정하지 않는다. 목표 달성 여부와 근거 기반 유형 분류는 별도다.
사람 노출도 PASS를 FAIL로 바꾸지 않으며, 현재 사람 측정은 종료 직전 5초에 한정된다.
4종 규칙을 지원한다는 사실만으로 4종 발견을 보장하지 않는다.

## 유효 표본과 시도 예산

| 설정 | 유효 표본 목표 | 총 시도 상한 | AFS 호출 상한 | 기준 로봇이 10호출일 때 로봇 호출 상한 |
|---|---:|---:|---:|---:|
| `afs_discovery_smoke_luna.json` | 6 | 8 | 8 | 80 |
| `afs_discovery_20_luna.json` | 20 | 24 | 24 | 240 |

첫 설정은 축별 최대 1회, 두 번째는 최대 2회다. 유효 표본 목표를 달성하면 종료한다.
총 시도 상한에 먼저 도달하면 `TARGET_NOT_REACHED`를 표시한다. 제외 실행도 시도를
소비하며 자동 대체하지 않는다. 제외·모호한 호출·환경 변경·잘못된 제안은 진단과 함께
중단한다. 검토 후 명시적으로 제외 이후 진행할 수 있지만 고정 예산은 늘어나지 않는다.
토큰·암묵적 시뮬레이션 제한은 추가하지 않았으므로 호출 상한은 금액 상한이 아니다.

`summary.json`의 `new_only_discovery_metrics`는 새 실행만으로 실패율·실패 유형·공동
달성 여부를 계산한다. 출발점으로 제공한 아카이브는 이 분모에 포함하지 않는다.
20개에서 실패 6회 이상과 확인된 4종 이상을 함께 관찰하는 것이 목표다. 기준 달성이
일반화 성능이나 인과적 실패 원인의 입증은 아니며, 모르는 분류는 그대로 남긴다.

## 실행

프로젝트 `scene2test` 디렉터리에서 먼저 유료 호출 없는 사전 검사를 실행한다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py plan --config config/afs_discovery_smoke_luna.json --run /workspace/g1_failure/runtime/robot_goal_agent/20261018T004636_410637Z
```

API 키가 설정된 터미널에서 아래 명령 한 번으로 소규모 탐색 전체를 시작한다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --config config/afs_discovery_smoke_luna.json --run /workspace/g1_failure/runtime/robot_goal_agent/20261018T004636_410637Z
```

결과는 `runtime/afs_autonomous/<timestamp>`에 저장된다. 보고서와 MP4를 확인한 뒤
20유효 실험은 **새 세션**에서 `afs_discovery_20_luna.json`으로 실행한다. 소규모 실행과
합산한 성능으로 보고하지 않는다. 실행 중단 시 출력된 세션 경로를 사용해 재개한다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --session /workspace/g1_failure/runtime/afs_autonomous/실제_세션_폴더
```

기존 동결 세션을 새 코드로 우회 재개하지 않는다. 키를 설정 파일이나 작업 기록에
저장하지 않는다. MP4만 저장하며 GIF는 생성하지 않는다.

## 이번 동일 끝점 응답의 명시적 복구

20261018T014205_556509Z는 AFS 1회 응답에서 사람 측면 비율 low=high=0을 제안했고,
로봇은 한 번도 실행하지 않았다. 이때에 한해 동일 수치를 `value=0`으로 해석하는
별도 복구 세션을 만들 수 있다. 원본 request/context/response는 그대로 복사하고,
별도 normalized_proposal.json과 recovery.json에 변환·해시·코드 차이를 기록한다.
의미·근거·컨텍스트를 바꾸지 않고 사용한 AFS 1회와 비용·전체 예산을 유지한다.

일반적인 코드 변경 우회 기능이 아니다. 첫 제안 전용이며 실행 흔적·추가 제안·모호한
응답·다른 로봇/환경 변화·근거 오류·범위 초과 등은 복구하지 않는다. 복구 중에는
API 호출이나 로봇 실행이 없다. 먼저 dry-run으로 확인할 수 있다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py recover-point --session /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z --output-dir /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery
```

`--apply`를 추가하면 새 복구 세션을 생성한다. 이미 생성된 폴더는 덮어쓰지 않는다.
복구 세션이 준비된 뒤 유료 실험은 다음 명령으로 별도로 실행한다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --session /workspace/g1_failure/runtime/afs_autonomous/20261018T014205_556509Z_point_recovery
```

첫 회차는 저장된 단일 값 제안을 사용하므로 추가 AFS 요청 없이 로봇 실행을 시작한다.
이후에는 결과를 반영해 새 제안을 요청한다. 총 예산은 여전히 8시도/8AFS요청이며,
그 중 AFS 1회가 이미 사용되어 남은 새 요청은 최대 7회다. 이는 복구된 개발 탐색이지
미수정 독립 비교 실험은 아니다.
