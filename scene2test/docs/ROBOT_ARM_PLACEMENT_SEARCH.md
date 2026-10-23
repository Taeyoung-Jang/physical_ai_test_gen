# 로봇팔의 직접 위치 지정과 AFS / Random 개발 비교

구현은 `src/robot_arm`과 `tools/run_robot_arm_search.py`에 있다. 기존 baseline_v2의
2 PASS와 소스·결과·예산은 보존했다. 새 실험은 같은 공개 GR00T 정책, 같은 bowl-to-plate
작업 및 LIBERO 성공 판정을 사용하지만 초기 배치 조건이 다르다.
아직 새로운 로봇 실행이나 AFS 호출은 수행하지 않았다.

## 위치 좌표와 기본 범위

위치는 **테이블 기준 미터**다. world XY = workspace_offset XY + 지정값이다.
원래 task BDDL의 두 초기 region 범위를 첫 개발 범위로 사용한다.

| 변수 | 범위(m) |
|---|---|
| bowl_x | -0.10 ~ -0.05 |
| bowl_y | -0.01 ~ 0.01 |
| plate_x | 0.05 ~ 0.07 |
| plate_y | 0.19 ~ 0.21 |

Z와 회전은 초기 sampler 값을 유지한다. 배치는 reset 직후 첫 행동 전에 한 번만
적용한다. 실행 중에는 물체 위치를 강제로 바꾸지 않는다. 새 위치를 반영한 관측을
생성해 원래 정책에 전달한다. 관측/행동 정규화·정책 가중치·성공 규칙은 바꾸지 않았다.

주변 배경은 seed 51000으로 고정한다. 기존 배경 sampler는 두 번째 방해 그릇을
목표 접시와 겹치게 놓을 수 있었다. 이를 실패 탐색으로 세지 않기 위해 해당 그릇
`akita_black_bowl_2`만 **(-0.25, 0.40)m**의 명시적 고정 위치로 배치한다.
다른 주변 물체는 그 seed의 위치를 유지한다. 이는 원래 LIBERO 배포 분포나 기존
두 baseline과 다른 **개발 조건**이다. 첫 가변 배경 감사 9/12, 고정 seed만 적용한
감사 0/12, 방해 그릇 위치까지 명시한 최종 감사 12/12이며, 모두 CPU 초기 기하만
검사했다. 이 기록들은 보존한다. 정책 결과를 보고 seed/범위를 골랐거나 Random을
재추출한 것이 아니다. 범위나 배경을 바꿀 때는 새 config와 새 출력 버전이 필요하다.

물체가 테이블 범위를 벗어나거나, 지원면 이외의 물체와 초기 관통하거나, 이미 목표를
달성한 장면이면 제외한다. 초기 geometry 유효성이 작업 도달 가능성을 증명하지는
않는다. Random도 동일 검사를 받으며 거절 후 재추출·대체하지 않는다.

## 준비된 실험

`experiments/robot_arm_libero/placement_comparison_v1`에 source/model 해시를 동결했다.
seed 51001/51002/51003 각각 AFS 4회 + Random 4회 = **총 24회 시도 상한**이다.
각 arm의 처음 2개는 같은 bootstrap 위치를 각각 실제 실행하며 비용에 포함한다.
이후 Random은 네 축을 독립 균등 추출하고 AFS는 **자기 method/seed의 새 기록만**
읽고 다음 네 위치를 제안한다. 배경과 정책 seed는 같은 seed/index에서 방법 간 동일하다.
과거 baseline PASS를 탐색 이력에 넣지 않는다.

- 로봇: 회당 최대 300 환경 step, action chunk 8; 총 최대 7200 step.
- AFS: Luna/default, seed당 최대 2개, 총 최대 **6 API 요청**. read timeout 300초.
- 로봇 정책은 로컬 GR00T이며 OpenAI API를 사용하지 않는다.
- 결과 오류/제외에서 중단한다. 대체·재시도·예산 초기화 없음.
- 요청은 전송 전 저장, 응답/usage는 받은 뒤 저장. 응답을 저장했으면 재전송 없이 처리.
- 응답이 없는 요청 intent나 결과가 없는 로봇 intent는 재실행하지 않음.
- worker receipt만 저장된 경우에는 재실행 없이 수집 가능.
- 매 실행은 source/model 동결을 확인. 완료된 기존 캠페인은 변경된 코드로 재개하지 않음.

AFS는 새 **위치 제안용 LLM 어댑터**다. 기존 휴머노이드용 breadth/trajectory
AFS 전체를 그대로 이식한 버전은 아니므로 기존 알고리즘과 같은 성능으로 주장하지
않는다. 위치/객체 초기·최종 상태와 중간 객체 궤적을 피드백한다. 가설은 원인 판정이 아니다.
최초의 작은 원래 region 범위에서 실패가 없을 수도 있으며 우위를 보장하지 않는다.

`scene2test` 디렉터리에서:

```bash
# 무료: 범위/예산/계획 확인, 현재 결과 읽기
.venv/bin/python tools/run_robot_arm_search.py plan
.venv/bin/python tools/run_robot_arm_search.py status

# 실제 실행: 우선 동일 seed bootstrap을 두 방법에서 한 번씩 수행 (AFS 호출 0개)
.venv/bin/python tools/run_robot_arm_search.py run --live --max-new-attempts 2
```

두 결과를 확인한 후 계속 실행하려면 같은 run 명령을 사용한다. 이미 끝난 결과는
보존하고 남은 고정 슬롯만 진행한다. 전체 남은 예산을 한 번에 진행하려면
`--max-new-attempts 24`를 사용할 수 있지만, 중간 제외/오류에서는 여전히 멈춘다.
24는 추가 예산이 아니라 invocation 상한이며 전체 동결 슬롯 수를 넘기지 않는다.
기존 준비 폴더에 init를 반복하지 않는다. 설정/코드를 바꾼 경우 새 버전으로 준비한다.

status는 method별 VALID/PASS/FAIL/제외/미완료, FDR와 AFS 요청 수를 출력한다.
양쪽 고정 유효 예산이 완성되기 전 Gain은 null이다. Random FDR=0이면 상대 Gain은
정의하지 않는다. 통계적 우위·원래 6종 다양성·공식 LIBERO 점수 달성을 주장하지 않는다.
사전 지정 seed지만 작은 개발 실험이며 별도의 최종 검증 표본이 아니다.

## 사용자가 위치를 직접 지정

준비된 수동 예제는 `experiments/robot_arm_libero/manual_placement_v1`이다.
그릇(-0.075,0.0), 접시(0.06,0.20)m를 지정했다. 수동 예제는 비교 예산/이력에
합치지 않으며 별도 1회 / 최대 300 step / AFS 0요청이다.

```bash
# 준비된 수동 예제를 한 번 실제 실행
.venv/bin/python tools/run_robot_arm_search.py manual-run --live \
  --output experiments/robot_arm_libero/manual_placement_v1

# 다른 위치를 지정한 새 예제 준비 (이 명령 자체는 GPU/API 실행 없음)
.venv/bin/python tools/run_robot_arm_search.py manual-init \
  --positions '{"bowl_x":-0.08,"bowl_y":0.005,"plate_x":0.055,"plate_y":0.205}' \
  --output experiments/robot_arm_libero/manual_placement_v2
```

현재 공통 범위 밖의 수동 값도 거절한다. 다른 범위를 원하면 config 복사본의
`bounds`를 수정하고 새 출력 폴더로 준비한다. host 안전 상한은 테이블 기준 ±0.4m이며
이 범위가 전부 물리적으로 유효하거나 로봇이 도달 가능한 것은 아니다.
새 장애물 생성 기능은 이번 구현에 포함하지 않았다.

각 시도 폴더의 candidate.json, initial_state.json, initial_sim_state.json,
trace.jsonl, receipt.json/result.json, run.log, videos/를 확인할 수 있다.
초기 상태에는 요청값과 실제 world pose, 고정 배경, 제외 이유를 기록한다.
예상치 못한 추가 episode 행동은 거절하고, Gym의 종료 후 자동 reset에는 마지막
관측을 반환하여 새 장면 생성이나 초기 증거 덮어쓰기를 막는다.

CPU 감사만 실행하려면 로봇팔 전용 Python을 사용한다. 정책/영상/모델 없이 reset과
forward로 초기 기하만 확인하며 결과 폴더는 새 이름이어야 한다.

```bash
experiments/robot_arm_libero/.venv-arm/bin/python tools/run_robot_arm_search.py audit \
  --output experiments/robot_arm_libero/new_geometry_audit
```

동결은 프로젝트/외부 Python 소스, 작업 BDDL, LIBERO 경로 설정과 로컬 finetuned
모델 파일을 포함한다. 전체 외부 자산·패키지·gated backbone 캐시까지 완결한
휴대 가능한 재현 패키지는 아니다. 기존 GR00T 환경의 패키지 참조도 유지한다.

## 넓은 위치 범위 개발 설정 (2026-10-23)

`config/robot_arm_placement_wide.json`은 기존 네 축 범위를 모두 포함하도록 넓힌
별도 개발 설정이다. 원래 비교 config와 기존 실행은 수정하지 않았다.

| 변수 | 새 범위(m) | 전체 이동 범위 |
|---|---|---|
| bowl_x | -0.18 ~ -0.04 | 14cm |
| bowl_y | -0.10 ~ 0.06 | 16cm |
| plate_x | 0.04 ~ 0.24 | 20cm |
| plate_y | 0.17 ~ 0.33 | 16cm |

새 seed는 52001/52002/52003이다. 로봇, 배경과 24회/최대7200step/6AFS요청 상한은
기존 개발 설계와 같다. 계획된 12개 Random/공통 초기 위치를 CPU reset/forward로
검사해 12개 모두 기하 검사를 통과했다. 추가 AFS 제안이나 로봇 작업 성공은 아직
검증하지 않았다. 범위는 새 정책 결과를 보기 전에 정했으며 Random 재추출은 없다.
초기 배치가 유효해도 실제 도달 가능성·작업 성공을 보장하지 않는다.

새 준비 폴더는 `experiments/robot_arm_libero/placement_wide_v1`이다.
기존 폴더에 init를 반복하거나 기존 비교를 이 설정으로 재개하지 않는다.

```bash
# 결과 확인만
.venv/bin/python tools/run_robot_arm_search.py status \
  --output experiments/robot_arm_libero/placement_wide_v1

# 실제 실행: 최대 로봇 24회 + 유료 AFS 6요청, 제외/오류에서 중단
.venv/bin/python tools/run_robot_arm_search.py run --live \
  --output experiments/robot_arm_libero/placement_wide_v1 \
  --max-new-attempts 24
```

실행 때는 동결된 manifest 설정을 사용하므로 --config를 다시 전달할 필요가 없다.
전체 첫 12회(3seed × 2bootstrap × 2방법)는 공통 초기 자료이며 AFS API 호출이 없다.
이후부터 AFS가 선택한 위치와 Random 위치가 달라진다. 같은 seed/bootstrap의 두
영상은 여전히 같도록 설계되어 있다. 서로 다른 seed/index의 배치는 더 크게 달라진다.

새 사물 추가는 현재 CLI에 구현되지 않았다. MuJoCo 장면에는 물체를 추가할 수 있지만
충돌 형태·크기·위치와 필요하면 질량/마찰을 정의하고 실제 physics·관측에 반영하는
adapter가 필요하다. 임의 mesh/사진을 그대로 추가할 수 있다는 뜻은 아니다.
AFS 비교에 추가 물체를 포함할 때는 양쪽의 물체 목록과 변경 범위를 새 설계로 동일하게
고정해야 하며, GR00T가 추가 장애물을 회피할 수 있다는 가정은 하지 않는다.

## 터미널 단계별 진행 표시 (2026-10-23)

새 `tools/watch_robot_arm_search.py`는 기존 동결 실행기를 수정하지 않고 저장 기록을
읽는 진행 화면이다. tqdm를 추가 설치할 필요가 없다. 기본 5초마다 시간, 결과 기록
횟수, PASS/FAIL/제외, 현재 seed·방법·회차, 초기 공통 배치/AFS/Random 선택 단계,
모델 shard 로딩, 실제 기록된 step/최대300, 마지막 기록 이후 시간을 표시한다.
분모300은 성공 확률이나 남은 시간이 아닌 실행 상한이다. 성공하면 일찍 종료한다.
모델검사/AFS응답 등에 예상 ETA나 가짜 완료율은 표시하지 않는다.

**이미 실행 중이면 중단하지 말고 새 터미널에서 관찰만 시작한다.**

```bash
.venv/bin/python tools/watch_robot_arm_search.py --watch-only \
  --output experiments/robot_arm_libero/placement_wide_v1
```

이 모드는 파일을 읽을 뿐 모델/API/로봇을 시작하거나 기존 프로세스를 제어하지 않는다.
Ctrl+C로 감시만 종료한다. 저장된 pending 기록만으로 현재 프로세스가 살아 있는지는
확정할 수 없으므로 마지막 기록 시간도 함께 표시한다. 오래 갱신되지 않는다고
실험을 자동 재시도·중단하지 않는다.

한 번만 상태를 읽으려면 `--once`를 사용한다.

```bash
.venv/bin/python tools/watch_robot_arm_search.py --once \
  --output experiments/robot_arm_libero/placement_wide_v1
```

**다음 실행/남은 슬롯 진행부터** 원래 run 대신 아래 명령으로 시작할 수 있다.
같은 실험을 다른 터미널에서 동시에 실행하지 않는다.

```bash
.venv/bin/python tools/watch_robot_arm_search.py --live \
  --output experiments/robot_arm_libero/placement_wide_v1 \
  --max-new-attempts 24
```

원래 run 명령에 같은 output·상한을 전달하며 budget/seed/정책/API timeout/재시도는
변경하지 않는다. 원래 동결 검사와 중복 실행 방지도 그대로 실행한다. stdout/stderr와
정상/오류 종료 코드를 전달하고 추가 진행 화면은 stderr로 출력한다. 하위 Python 출력
버퍼링만 해제하여 기존 run.log 갱신이 잘 보이도록 한다. 원본 상세 로그는 그대로 남긴다.
수동 배치 출력 폴더를 지정하면 그 폴더의 manual-run을 감싼다.
이 감시기로 직접 시작한 실행에서 Ctrl+C를 누르면 자신이 만든 프로세스 그룹에만
중단 신호를 보내며, 저장된 intent를 삭제하거나 다시 보내지 않는다.

이 도구는 manifest/receipt를 수정하거나 pending 결과를 수집하지 않는 읽기 전용
observer다. 따라서 기존 동결 소스의 해시를 바꾸지 않고 사용 가능하다. 새로 init하는
실험도 기존 실행기 그대로 사용하며 감시 UI는 정책 조건의 일부로 주장하지 않는다.

## OpenRouter AFS 전환 (2026-10-23)

사용자가 선택한 모델은 `openai/gpt-6-luna-pro`다. 로봇 행동은 기존 로컬 GR00T가
담당하고, 다음 위치를 선택하는 AFS 요청만 OpenRouter로 보낸다.
`OPENROUTER_API_KEY`를 사용하고 OpenAI 키를 읽거나 대신 사용하지 않는다.
요청은 고정 `https://openrouter.ai/api/v1/chat/completions`로 보낸다.
JSON schema의 위치·필드 검증을 유지하고 allow_fallbacks=false,
require_parameters=true로 요청한다. 다른 모델 응답, refusal, 중단된 JSON,
tool call, HTTP/transport 오류에서는 중단하고 자동 재요청하지 않는다.
read timeout은 300초다. OpenAI direct의 service_tier=default는 보내지 않으며
직접 Standard와 동일한 서비스 조건이라고 주장하지 않는다.

원본 `placement_wide_v1`은 초기 12회 로봇 결과까지 완료했고 첫 AFS는
`OPENAI_API_KEY` 누락으로 HTTP 전송 전 중단됐다. 이 사실은 사용자가 제공한
traceback과 해당 provider 코드 순서에 근거한다. 응답 파일이 없다는 사실만으로
미전송을 추정하지 않는다. 옛 request.json은 원본에 그대로 보존하고 새 공급자로
재전송하지 않는다. 별도의 새 OpenRouter request를 만들도록 전환한다.

새 `placement_wide_openrouter_v1`은 명시적인 공급자/모델 변경 개발 버전이다.
12개 bootstrap 후보·seed·유효 result/receipt·초기 위치·trace를 확인한 뒤 파일을
복사하고 source/copy hash를 대조했다. 로컬 모델 해시는 기존 동결값과 대조했다.
변경 전 source 감사와 원본 manifest digest, 원본 요청 digest, 복사본 hash를
transition.json/manifest에 기록한다. 새로운 freeze는 변경 소스와 공급자 adapter도
포함한다. 기존 소스 hash를 제자리 갱신하거나 원본 캠페인을 재개하지 않는다.

- **이미 수행한 12회는 다시 실행하지 않으며** 새 전환본 집계에 inherited 결과로 포함한다.
- 남은 로봇 상한은 12회, 새 OpenRouter 요청 상한은 6회다.
- 원본의 미전송 API intent 1개는 별도 기록한다. 6회는 새 HTTP 요청 상한이며
  원본 journal의 intent 개수를 지우거나 0으로 바꾸는 의미가 아니다.
- 원본+새 폴더를 독립적인 두 표본으로 합산하지 않는다. 기존 수행 비용도 보존한다.
- 위치 범위·배경·seed·로봇·Random·목표·판정·전체24회 슬롯은 유지한다.
- 모델/공급자를 바꾼 개발 전환이므로 원래 OpenAI Luna 실험의 연속 동일 조건이라고
  부르지 않는다. 별도 독립 평가나 AFS 우위를 입증한 결과도 아니다.

모든 준비/CPU 시험은 실제 키 조회나 API/GPU/로봇 실행 없이 수행했다.
모델 등록은 공식 OpenRouter 페이지에서 확인했지만 실제 API 호환·권한·잔액은 아직
검증하지 않았다. raw 응답에는 generation ID, model/provider, usage/cost가 보존되며
사용량 일부가 없으면 unknown으로 남긴다. status의 token 합계는 알려진 항목만 집계한다.

현재 shell에 키가 없다면 사용자 터미널에서 입력한다. 키를 채팅이나 config에 넣지 않는다.

```bash
read -rsp 'OpenRouter API key: ' OPENROUTER_API_KEY
export OPENROUTER_API_KEY
printf '\n'
```

우선 OpenRouter AFS 1요청과 로봇 최대1회로 연결을 확인한다. 기존 초기12회는 건너뛴다.

```bash
.venv/bin/python tools/watch_robot_arm_search.py --live \
  --output experiments/robot_arm_libero/placement_wide_openrouter_v1 \
  --max-new-attempts 1
```

이후 같은 출력 폴더로 `--max-new-attempts 12`를 사용하면 남은 고정 슬롯만 진행한다.
이미 종료한 슬롯은 재실행하지 않는다. 응답 없는 ambiguous API intent나 pending robot
intent에서는 여전히 중단하며 자동 retry/resend/교체를 하지 않는다.

무료 결과 확인:

```bash
.venv/bin/python tools/run_robot_arm_search.py status \
  --output experiments/robot_arm_libero/placement_wide_openrouter_v1
```

전환 도구 `tools/migrate_robot_arm_openrouter.py`는 준비 전용이다. 변경 전 감사 파일과
명시적인 pre-send missing-key 근거가 필요하며 adaptive 응답/후보/로봇 intent가 이미
있으면 이 제한적인 bootstrap 이관을 거절한다. 준비된 폴더에 반복 실행하지 않는다.
