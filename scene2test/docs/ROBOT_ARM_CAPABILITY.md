# 로봇팔 작업 경계·장애물 실험

공개 GR00T 정책과 LIBERO 성공 판정을 유지하는 별도 개발 실험입니다. 기존 실험과 결과는 보존합니다. 장애물을 AFS/Random으로 자동 선택하는 기능은 아직 연결하지 않았습니다.

준비한 6개 장면은 물체 시작 위치와 정책 seed를 고정합니다. 처음 3개는 접시 위치만 가까운 곳→중간→먼 곳으로 바꿉니다. 다음 3개는 가까운 목표에서 높이 5/10/15cm의 정적 상자를 각각 추가합니다. 좌표는 `config/robot_arm_capability_suite.json`에 있습니다. 총 6회, 회당 최대 300 control steps, AFS 요청 0회입니다.

## 실행

`scene2test`에서 준비된 suite를 실행합니다. init을 반복하지 않습니다.

```bash
.venv/bin/python tools/run_robot_arm_capability.py run --live --max-new-attempts 1
```

첫 정상 장면의 영상과 결과를 확인한 뒤 남은 5개를 실행합니다.

```bash
.venv/bin/python tools/run_robot_arm_capability.py run --live --max-new-attempts 5
.venv/bin/python tools/run_robot_arm_capability.py status
.venv/bin/python tools/run_robot_arm_capability.py report
```

결과는 `experiments/robot_arm_libero/capability_suite_v1/attempt_00000`부터 저장합니다. 진행 표시, 원래 실행기의 영상과 결과, `scene.xml`, `physics.jsonl`, `measurement.json`을 제공합니다. 완료 장면은 재실행하지 않으며 오류나 미완료 intent가 있으면 중단합니다. 자동 재시도나 예산 초기화는 없습니다.

## 해석

- PASS/FAIL은 원래 작업 성공 판정입니다. FAIL만으로 기구학적 도달 불가능을 확정하지 않습니다.
- 인접 목표의 PASS/FAIL이 달라지면 관측된 경계 구간과 다음 중간 위치 제안을 보고합니다. 제안은 자동 실행하지 않으며 새 예산이 필요합니다. 성공 경계의 단조성도 보장하지 않습니다.
- 물리 timestep마다 로봇–장애물과 물체–장애물 접촉, 힘과 지속 시간을 기록합니다. 접촉 부재만으로 회피 의도를 확정하지 않습니다.
- 물체 중심이 테이블 면보다 5cm 아래에서 0.1초 이상 유지되면 테이블 아래 낙하입니다. 테이블 위 놓침이나 잡기 실패를 모두 검출하지는 않습니다.
- 물리 기록이 누락·불완전하면 UNKNOWN입니다. 작업 실패와 측정 실패는 별개이며 실패 원인은 미확정입니다.

## 물건 추가

새 설정의 각 case에 `obstacles`를 지정할 수 있습니다. 정적 box/cylinder를 최대 4개 지원합니다.

```json
{"id":"blocker","shape":"box","xy_m":[-0.0075,0.10],"size_m":[0.05,0.06,0.10]}
```

크기는 전체 폭·깊이·높이(m), XY는 테이블 기준입니다. cylinder는 앞 두 크기를 같게 지정합니다. 실제 충돌 형상이며 초기 물체와 관통하면 제외합니다. 임의 mesh나 이동 가능한 추가 물체는 지원하지 않습니다. 변경한 설정은 새 output으로 plan→audit→init합니다. 기존 suite의 설정이나 동결 소스를 변경하지 않습니다.

## 검증 범위

실제 LIBERO의 CPU 초기 배치 검사에서 6개 장면 모두 유효했습니다. MuJoCo 구 낙하 시험에서 실제 충돌과 기록 전후 물리 상태 일치를 확인했습니다. 실제 LIBERO에서 정책·카메라를 시험 대체한 1 control step 연결 검사도 통과했습니다. 이는 모델 성능이나 실제 렌더 영상 검증을 의미하지 않습니다. 이번 준비에서 GPU/모델 추론이나 유료 API는 실행하지 않았습니다.

기존 `placement_wide_openrouter_v1`은 공유 provider.py 소스가 저장된 해시와 달라 직접 재개하면 안 됩니다. 기존 결과는 보존하고 새로 동결한 capability suite를 사용합니다.

## 추가 실패 탐색: followup_v2

기존 결과를 보고 설계한 개발 장면 11개입니다. 목표 이동선의 t=0/.125/.25/.375/.5(가까운 목표~기존 중간 목표), 가까운 목표에 상자 높이10/12/14/15/17cm, 높이15cm 상자를 왼쪽3cm 이동한 장면을 사용합니다. 물체 시작 위치·정책 seed·로봇·성공 판정은 유지합니다. 기존 PASS/FAIL 조건도 새로 실행하여 재현 여부를 함께 확인합니다. 실패를 보장하지 않으며 결과를 보고 조정한 자료이므로 독립적인 AFS/Random 평가에 합산하지 않습니다.

별도 설정 `config/robot_arm_capability_followup.json`, 최대11회/3300controlsteps/0AFS. 아래 명령은 초기화된 새 output의 남은 장면만 실행합니다.

```bash
.venv/bin/python tools/run_robot_arm_capability.py run --live \
  --output experiments/robot_arm_libero/capability_followup_v2 \
  --max-new-attempts 11
.venv/bin/python tools/run_robot_arm_capability.py status \
  --output experiments/robot_arm_libero/capability_followup_v2
```

실패 사례는 receipt.json의 task_outcome=FAIL인 attempt 폴더의 videos에 저장됩니다. 설정/소스 동결 검사는 기존대로 적용됩니다.

CPU 초기 검사에서 오른쪽 이동 장면은 기존 쿠키와 관통하여 제외했습니다. 초기 준비 v1은 실행하지 않으며 유효한 11개만 동결한 v2를 사용합니다.

## 장애물 AFS/Random 비교: obstacle_comparison_v1

`tools/run_robot_arm_obstacle_search.py`와 `config/robot_arm_obstacle_comparison.json`을 사용합니다. 기존 위치 비교기·완료된 capability suite는 변경하지 않습니다. 가까운 목표와 물체 시작 위치를 고정하고 정적 상자 하나의 X/Y/높이만 탐색합니다. 이 개발 실험에서는 이동 가능한 장애물·운반 중 회피 능력이나 로봇의 기구학적 한계를 평가한다고 주장하지 않습니다.

공통 범위: 테이블 기준 X=-.0375..-.0075m, Y=.09...11m, 높이=.08...17m. 상자 전체 폭·깊이=.05/.06m. 양 방법에 같은 범위·목표·로봇·판정·접촉 측정을 적용합니다. 범위는 이전 개발 관측으로 정했으며 독립적인 held-out 최종 평가가 아닙니다. Random이 너무 잘 실패를 찾거나 AFS가 지더라도 결과를 보존합니다.

seed641/647/653마다 방법별4회, 총24회(방법별12회), 최대7200controlsteps. 각 seed의 처음2개 장면은 동일한 Uniform bootstrap을 양 방법에서 별도 실행·과금합니다. 이후 Random은 세 축을 독립 Uniform으로 뽑고 AFS는 자신의 같은 seed 이력으로 다음 장면을 제안합니다. 양 방법의 index별 정책 seed도 동일합니다. 초기 이력은 비어 있으며 과거 개발 결과나 Random 결과·다른 seed 결과를 AFS에 넣지 않습니다. AFS 호출은 최대6회, OpenRouter `openai/gpt-6-luna-pro`, HTTP timeout300초, 자동 재시도·fallback 없음. 로봇 정책은 고정된 로컬 GR00T입니다.

준비된 output을 사용합니다. init을 반복하지 않습니다. 첫 명령은 동일한 초기 장면을 AFS/Random 각각1회 실행합니다. 이때 AFS API 요청은 없습니다. 실행 전 터미널에 OPENROUTER_API_KEY가 설정되어 있어야 합니다. 키를 채팅이나 설정 파일에 넣지 않습니다.

```bash
.venv/bin/python tools/run_robot_arm_obstacle_search.py run --live \
  --max-new-attempts 2
.venv/bin/python tools/run_robot_arm_obstacle_search.py status
```

첫 결과 확인 후 남은 고정 예산을 실행합니다. 두 번째 명령의22는 새로 허용할 최대 실행 횟수이며 기존 완료2회는 건너뜁니다.

```bash
.venv/bin/python tools/run_robot_arm_obstacle_search.py run --live \
  --max-new-attempts 22
```

결과 폴더는 `experiments/robot_arm_libero/obstacle_comparison_v1/seed_641/afs/attempt_00000` 형태입니다. 영상·원래 성공 판정·고빈도 물리 기록·측정 결과·증거 해시를 보존하고 실행 중5초 간격으로 상태를 표시합니다. API 요청과 응답도 보존합니다. 응답 없는 API intent나 결과 없는 robot intent는 재전송·재실행하지 않습니다. 초기 관통이나 인프라 오류는 제외이며 FAIL이 아니고, 비교는 중단되어 예산을 새 장면으로 대체하지 않습니다. 접촉만으로 task FAIL을 만들지 않습니다. 측정 누락은 UNKNOWN으로 남깁니다.

요약에는 방법별 실패율, seed별 첫 실패까지 실행 횟수(null이면 아직 미발견), 접촉하며 성공/실패한 횟수, 알 수 없는 측정·API usage가 나옵니다. Bootstrap 실패도 전체 비용에 포함하므로 첫 실패까지 횟수가 같을 수 있습니다. 동일 valid 예산 완료 전 상대 Gain은 null이고, 예비 실험의 통계적 우수성 표시는 항상 false입니다. 서로 다른 원인 유형을 자동 확정하거나 임의로 family 수를 늘리지 않습니다.

## 소스 변경 중단 복구: obstacle_comparison_recovery_v2

기존 v1에서 완료9회(AFS5/Random4), 다음 Random647/index1은 provider 소스 동결 검사에서 worker_started 이전에 차단됐습니다. AFS 요청은0회였습니다. 공유 provider 전체를 되돌리지 않고 별도 버전을 동결했습니다. 복구 도구는 원본 manifest·9개 증거 seal·후보·intent·모델 해시와 차단 로그를 검사하고 원본 파일 해시를 새 manifest에 연결합니다. 원본 파일은 수정하지 않습니다.

차단 슬롯은 새 폴더에 행정적 INCONCLUSIVE 기록으로 보존하며 재실행·교체하지 않습니다. 총24회 슬롯 중 완료9+제외1을 소비했으므로 새 실행은14회, AFS 요청 최대6회입니다. 앞으로 발생하는 다른 제외는 기존처럼 중단합니다. 유효 횟수는 최대AFS12/Random11이므로 equal_valid_budget_complete는false, 상대Gain은null로 유지됩니다. 실패로 바꿔 집계하거나 유효 결과를 맞추려고 예산을 늘리지 않습니다.

복구 폴더는 이미 준비됐으므로 init이나 복구 도구를 다시 실행하지 않습니다. 기존 v1 명령 대신 명시적으로 새 output을 사용합니다.

```bash
.venv/bin/python tools/run_robot_arm_obstacle_search.py run --live \
  --output experiments/robot_arm_libero/obstacle_comparison_recovery_v2 \
  --max-new-attempts 14
```

공유 소스 변경이 다시 발생하면 새 동결 검사에서 중단됩니다. 실행하는 동안 해당 소스 변경을 피하고, 저장된 해시를 수정해 우회하지 않습니다.

## 환경 변수 확장: environment_comparison_v2

로봇 정책·목표 판정·행동 chunk8·300step 제한을 유지하고 실패 환경 생성 변수를 3개에서10개로 늘린 별도 개발 실험입니다. 기존 완료된 obstacle_comparison/recovery 및 측정 기록은 변경하지 않습니다. 새 실행기는 `tools/run_robot_arm_environment_search.py`, 설정은 `config/robot_arm_environment_comparison.json`입니다.

| 환경 축 | 공통 범위 |
|---|---|
| 집을 그릇 X / Y | -10~-5cm / -1~1cm |
| 목표 접시 X / Y | 6~10cm / 19~24cm |
| 장애물 X / Y | -24~-0.75cm / 9~12cm |
| 장애물 전체 폭 / 깊이 | 각각2~6cm |
| 장애물 높이 | 2~17cm |
| 장애물 방향 | -90~90도(설정/API 단위 radians) |

XY는 테이블 기준입니다. 장애물은 정적 box1개이며 회전은 테이블 Z축 기준입니다. 폭·깊이는 전체 길이이며 MuJoCo에는 반길이로 변환됩니다. 회전된 모서리까지 테이블 내부인지 검사하고 실제 회전 행렬과 XML을 기록합니다. 기존 좁은 장애물 범위와 고정 물체·목표·크기·방향도 새 범위에 포함됩니다. 그릇·접시의 회전, 물체 질량·마찰, 장애물 개수는 이번 탐색 축에 포함하지 않았습니다.

새 seed661/673/677, 각 방법/seed4회로 총24회(12/method), 최대7200controlsteps/6AFS requests입니다. 처음2개/seed는 양쪽에서 동일한 Uniform bootstrap을 독립 실행하며, 이후AFS는 같은seed 자신의 이력만 보고 선택하고 Random은10개 축을 독립Uniform으로 뽑습니다. 과거 개발 결과를 새 이력에 넣거나 결과에 따라 seed·후보를 선택하지 않습니다. 범위는 개발 관측에 기반한 새 탐색 영역으로, 공식LIBERO/heldout점수나 새로운 실패 유형 발견을 보장하지 않습니다.

준비된 새 output을 사용합니다. 터미널에 OPENROUTER_API_KEY가 필요하며 키를 파일·채팅에 넣지 않습니다. init을 다시 실행하지 않습니다.

```bash
.venv/bin/python tools/run_robot_arm_environment_search.py run --live \
  --output experiments/robot_arm_libero/environment_comparison_v2 \
  --max-new-attempts 2
.venv/bin/python tools/run_robot_arm_environment_search.py status \
  --output experiments/robot_arm_libero/environment_comparison_v2
```

첫2회는 같은 초기 장면을 양쪽에서 실행하며 AFS API를 호출하지 않습니다. 확인 후 남은22회는 동일명령의 max-new-attempts를22로 지정합니다. 이전 obstacle 실행기와 output을 사용하지 않습니다. 초기 관통·인프라 오류·미완료 intent가 있으면 중단하며 재샘플링/자동재시도/교체는 없습니다. 예정Random/공통bootstrap의 초기 배치 검사는 미래AFS 제안의 기하학적 유효성이나 정책 성공을 보장하지 않습니다.

기존FDR·접촉PASS/FAIL·측정UNKNOWN과 별도로 `unique_environment_settings`와 `repeated_environment_settings`를 표시합니다. 이는 각 방법에서 VALID 실행의 정확히 같은10개수치설정(정책seed 제외)을 비교한 집계이며 근접도·물리적등가·실패원인유형 분류가 아닙니다. 반복 설정은 여전히 허용하고 원래FDR에 포함하므로 변수 확대만으로 반복제안/실패율포화가 해결됐다고 주장하지 않습니다. 반복 금지나 새로운 탐색 목표는 별도 개발 조건입니다.

## 단계별 두 장애물 탐색: staged_comparison_v3

접근 차단만 반복되는 문제를 살펴보기 위한 별도 개발 실험입니다. 로봇·공개 모델·성공 판정·300step/chunk8·배경은 유지합니다. 상자2개를 그릇→접시 방향으로 평행하게 놓고, 두 상자 안쪽 면 사이의 간격을 조절합니다. 기존 environment_comparison_v2 결과나 이력을 가져오지 않습니다.

각 방법은 seed701/709/719마다6회, 총18회이며 전체36회/10800controlsteps/최대12AFS요청입니다. 슬롯순서는 접근→운반→놓기→접근→운반→놓기이고 양쪽에 같은 순서를 적용합니다. 방법별 각 배치는6회씩 평가합니다. 첫2슬롯/seed는 공통Uniform bootstrap을 양쪽에서 별도 실행합니다. 이후AFS는 같은seed 자신의 결과로 선택하고 Random은 해당 배치의10개 축을 독립Uniform으로 뽑습니다. 놓기 배치2회는 모두 탐색 단계이고, 접근·운반은 초기1회+탐색1회/seed입니다. 따라서 배치별 차이를 순수한 기구학적 효과로 해석하지 않습니다.

10개 축은 그릇XY·접시XY·안쪽통로간격·상자길이·두께·높이·경로상진행비율·통로가로이동입니다. 두 상자는 같은 크기·방향이며 방향은 시작→목표 선에서 유도합니다. 장애물 개수는2개로 고정합니다. 질량·마찰·임의 개수·물체 회전은 이번 축에 포함하지 않습니다.

- 접근: 상자 쌍 중심을 시작물체 근처(경로0~5%)에 배치, 간격12~18cm.
- 운반: 시작에서 경로66~72% 위치에 배치, 간격9~12cm.
- 놓기: 목표 근처(경로98~102%)에 배치, 간격16~20cm.

상자 전체길이2.5~5cm,두께1.5~2.5cm,높이4~16cm,통로가로이동±.5cm. 그릇XY -8.5~-6.5cm/±.5cm,접시XY6.5~8.5cm/20.5~22.5cm. 모두 테이블 기준이며 상세범위는 config/robot_arm_staged_comparison.json에 있습니다. 생성식은 중심=start+progress*(goal-start)+lateral*normal, 상자중심 간격=gap+thickness입니다. 이동 전부터 존재하는 정적 장애물이며 접근 통과를 보장하거나 잡은 뒤에만 등장하는 장애물이 아닙니다. 배치 이름은 설계 의도이고 실제 실패 단계 판정이 아닙니다.

`measurement.json`에 원래 접촉·낙하 지표와 별도로 `motion_observations`를 기록합니다. 초기1초 이후 물체 중심 상승·수평이동·목표중심XY거리 및 접촉 시작 시점을 제공하며, 상승3cm/이동5cm/목표중심5cm 기준은 설명용 휴리스틱입니다. 물체를 밀거나 기울여도 상승·이동할 수 있습니다. native FAIL의 관찰 패턴은 little_object_motion, object_moved_native_task_incomplete, object_near_goal_native_task_incomplete로 나누되, 잡기·놓침·실패원인을 확정하거나 기존goal판정을 바꾸지 않습니다. 불완전기록은UNKNOWN입니다. AFS에는 이 관찰과 기존trace/성공결과를 함께 전달합니다.

요약은 `by_layout_stage`(배치별PASS/FAIL), `failure_motion_patterns`(nativeFAIL에서 관찰한 양상), `unique_failing_environment_settings`와 `recheck_failures`를 제공합니다. 같은 수치환경을 반복한 검증은 허용하되 새 환경 발견과 구분합니다. 배치 이름과10개 정확한 수치 기준이며 물리적등가·원인유형·근접중복을 판정하지 않습니다. 새로운 환경을 선호하도록 AFS에 안내했으나 중복 제안을 자동 거부/재요청하지 않습니다. AFS 실패율 개선이나 새로운 실패 유형 발견은 보장하지 않습니다.

새 output은 준비돼 있으며 init을 다시 실행하지 않습니다. 터미널 OPENROUTER_API_KEY가 필요합니다. 첫2회는 같은 접근장면을 양쪽에서 실행하며 AFS 요청은 없습니다.

```bash
.venv/bin/python tools/run_robot_arm_staged_search.py run --live \
  --output experiments/robot_arm_libero/staged_comparison_v3 \
  --max-new-attempts 2
.venv/bin/python tools/run_robot_arm_staged_search.py status \
  --output experiments/robot_arm_libero/staged_comparison_v3
```

첫 결과 확인 후 동일 명령에서 max-new-attempts34로 남은 고정 예산을 실행할 수 있습니다. 완료한2회는 건너뛰며 추가34회를 넘지 않습니다. 제외·미완료·소스변경이 있으면 자동재시도/교체 없이 중단합니다. CPU검사는 예정Random/공통bootstrap18개 초기 배치만 확인하며 미래AFS배치·로봇동작의 성공을 보장하지 않습니다.
