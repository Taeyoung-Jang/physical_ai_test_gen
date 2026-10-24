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

## 독립 장애물 2개 재설계: free_pair_comparison_v4

staged_v3의 중앙 통로·평행 배치 제약을 제거한 별도 개발 실험입니다. 로봇·목표 성공 판정·300steps/chunk8·고정 배경은 유지합니다. 기존 v2/v3 결과는 수정하거나 새 이력에 넣지 않습니다. 물체·목표 위치 범위는 v2 범위로 복원하고, 각 상자의 XY·전체폭·깊이·높이·yaw를 독립 선택하여 총16개 축을 탐색합니다. 배치별 고정 순서·공통 통로 간격은 없습니다.

| 요소 | 공통 범위(테이블 기준) |
|---|---|
| 그릇 X/Y | -10~-5cm / -1~1cm |
| 접시 X/Y | 6~10cm / 19~24cm |
| 상자1 X/Y | -24~-0.75cm / 10~12cm |
| 상자2 X/Y | -12~-7.5cm / 24~30cm |
| 각 상자 전체 폭/깊이 | 각각2~6cm |
| 각 상자 높이 | 3~20cm |
| 각 상자 방향 | 각각-90~90도(API/config는radians) |

상자1은 접근·이동 영역,상자2는 목표 왼쪽 영역의 사전 지정 사각형에서 독립 선택합니다. 전 테이블에서 무제한 배치하는 것은 아닙니다. 영역은 기존 배경 물체와 초기 관통을 줄이기 위해 정했으며 결과를 보고 Random 장면을 골라내지 않습니다. 실제 두 상자는 정적 충돌 형상이며 다른 크기·방향을 가질 수 있습니다. 회전된 사각형의 분리축 검사로 두 정적 상자의 초기 중첩을 검사합니다. 정적 상자끼리의 관통이 네이티브 접촉에서 생략될 가능성도 보완합니다. 초기 물체 관통·테이블 밖 배치·상자 중첩은 제외이며 작업FAIL이 아닙니다. 자동재샘플링·재시도·대체 없이 중단합니다.

새 seed727/733/739,방법별seed당4회:총24회(12/method),최대7200controlsteps/6AFS요청입니다. 처음2개/seed는 같은Uniform bootstrap을 각각실행합니다. 이후AFS는같은seed 자신의이력만 보고 선택하고 Random은16축 독립Uniform을 사용합니다. 두 방법의 범위·정책seed·성공/접촉 측정·예산이 같습니다. 과거 개발 결과를 성능평가 이력으로 가져오지 않습니다. 새 개발영역이므로 이전실험과 FDR을 단순비교해 알고리즘 개선을 확정하지 않습니다.

AFS에는 두 상자의 독립 규칙,현재범위,기존결과와 물체이동 관찰을 제공합니다. 새 환경을 선호하되 같은 환경의 재확인을 자동 거부/재요청하지 않습니다. 기존접촉PASS/FAIL,unique_environment_settings,unique_failing_environment_settings,recheck_failures,failure_motion_patterns를 기록합니다. 관찰패턴은 잡기·놓침·충돌 원인이나 새로운 실패유형 확정이 아닙니다. 몸체원점 기반 물체 이동·목표거리는 원래goal판정을 대체하지 않습니다.

예정Random/공통bootstrap12장면은 CPU초기배치에 모두통과했습니다. 미래AFS기하학적유효성·로봇성공·실패율향상을 보장하지 않습니다. 실제API/GPU/정책은 준비과정에서 실행하지 않았습니다.

새 output은 준비돼 있습니다. init을 반복하지 말고 터미널OPENROUTER_API_KEY를 설정한 상태에서 실행합니다. 첫2회는 동일초기장면의 양쪽실행으로 AFS호출이 없습니다.

```bash
.venv/bin/python tools/run_robot_arm_free_pair_search.py run --live \
  --output experiments/robot_arm_libero/free_pair_comparison_v4 \
  --max-new-attempts 2
.venv/bin/python tools/run_robot_arm_free_pair_search.py status \
  --output experiments/robot_arm_libero/free_pair_comparison_v4
```

첫결과 확인 후 같은명령에서 max-new-attempts22로 남은고정예산을 실행할 수 있습니다. 실행중 동결소스를 변경하면 중단되며 해시수정으로 우회하지 않습니다.

## v4 초기 로딩 취소 후 한 줄 이어가기

첫 AFS727/index0이 정책 생성 중 라이브러리 import에서 KeyboardInterrupt로 종료됐습니다. worker는 종료됐고 물리 초기상태·trace·영상·AFS요청이 없습니다. 원본 취소기록을 보존한 free_pair_continuation_v5를 별도로 준비했습니다. 이 한 슬롯은 행정적 INCONCLUSIVE로 소비하며 FAIL이나 새 실행으로 바꾸지 않습니다. 남은23회만 실행합니다. 같은 명령을 다시 사용해도 완료된 결과는 건너뜁니다.

```bash
bash tools/continue_robot_arm_free_pair.sh
```

init·파일삭제·복구명령을 직접 실행할 필요는 없습니다. 이 명령은 실제 로봇/모델 실행 및 이후 최대6AFS 요청을 시작합니다. 터미널의 OPENROUTER_API_KEY 설정은 유지해야 합니다. AFS최대11valid/Random12valid로 유효횟수가 달라 상대Gain은null입니다. 새로운 중단이 실제 동작 중에 발생하면 여전히 무조건 재실행하지 않고 기록을 보존합니다. 이 복구가 앞으로의 모든 취소를 안전하게 자동 재시도한다는 뜻은 아닙니다.

## 독립 두 장애물 실험 완료 분석 (2026-10-24)

### 보고 범위와 전체 시도 기준 발견률

대상은 `experiments/robot_arm_libero/free_pair_continuation_v5`입니다. 사용자 요청에 따라 취소된 슬롯까지 분모에 포함한 **배정된 시도당 작업 실패 발견률**을 본 절의 주 지표로 추가합니다. 정의는 `native FAIL 발견 수 / 배정·소비된 전체 시도 수`입니다. 취소 1회는 발견 수 0으로 기여하지만 작업 PASS 또는 FAIL로 재분류하지 않습니다. 이 지표는 운영상 예산당 발견 수율이며, 완료된 로봇 실행의 실패 확률과 구분합니다. 결과를 본 뒤 추가한 보고 지표임을 명시하며 사전 등록 지표라고 주장하지 않습니다.

| 지표 | AFS | Uniform Random |
|---|---:|---:|
| 전체 시도 (취소 포함) | 12 | 12 |
| 유효 실행 | 11 | 12 |
| native PASS | 4 | 9 |
| native FAIL | 7 | 3 |
| 취소·제외 | 1 | 0 |
| 전체 시도 기준 실패 발견률 | **7/12 = 58.33%** | **3/12 = 25.00%** |
| 유효 실행 기준 실패 발견률 (기존 FDR) | 7/11 = 63.64% | 3/12 = 25.00% |
| 정확히 서로 다른 실패 설정 | 7 | 3 |
| 유효 설정 중 정확한 중복 | 0 | 0 |
| 미완료 pending | 0 | 0 |

전체 시도 기준 차이는 **33.33%포인트**, 비율은 **2.33배**, 상대 증가는 **133.33%**입니다. 취소를 포함해도 AFS가 이 개발 표본에서 더 많은 실패를 발견했습니다. 이는 관측된 기술 통계이며 일반화된 우월성 증명이 아닙니다. 원본 JSON의 `relative_fdr_gain=null`은 유효 실행 수 일치를 요구하는 기존 계약의 결과이므로 유지합니다. 위 133.33%는 별도로 정의한 전체 시도 기준 상대 증가이며 기존 필드의 대체값이 아닙니다. `attempt_budget_complete=true`, `equal_valid_budget_complete=false`는 서로 모순되지 않습니다. 추가 실행·제외 슬롯 대체·Random 결과 삭제는 하지 않았습니다.

### 증거 검증과 탐색 단계 분해

읽기 전용으로 동결 소스·모델·상속된 취소 기록, 24개 슬롯의 증거 해시를 확인했습니다. 23개 유효 실행의 전체 `physics.jsonl`에서 접촉 및 움직임 측정을 재계산해 저장된 measurement와 정확히 일치함을 확인했습니다. 6개 AFS 요청이 당시의 자기 시드 이전 AFS 이력으로 재구성되는지, 저장 응답이 실행 후보와 연결되는지, 나머지 후보가 동결 Uniform 규칙과 일치하는지 확인했습니다. 원본 실행 결과와 실행 코드는 변경하지 않았으며 새로운 API·로봇 실행은 없습니다.

| 구간 | AFS 실패 / 전체 슬롯 (유효 수) | Random 실패 / 전체 슬롯 (유효 수) |
|---|---:|---:|
| 공통 Uniform bootstrap | 1/6 (5) | 1/6 (6) |
| 이후 선택 단계 | **6/6 (6)** | **2/6 (6)** |

AFS 선택 단계에서 증가가 관측되며, bootstrap 자체를 AFS 추론의 성과로 계산하지 않습니다. 전체 시도 기준 비교에는 취소된 bootstrap도 그대로 포함합니다.

| 탐색 시드 | AFS FAIL / 4슬롯 | Random FAIL / 4슬롯 |
|---|---:|---:|
| 727 | 2 (추가로 취소 1) | 0 |
| 733 | 3 | 2 |
| 739 | 2 | 1 |

세 시드 모두 AFS의 실패 발견 수가 많았습니다. 다만 탐색 시드가 3개뿐이고 각 시드 안의 AFS 선택은 이전 결과에 의존하므로, 24개 슬롯을 독립 동일분포 표본으로 간주한 통계적 우월성을 선언하지 않습니다. 727의 첫 실패 슬롯 AFS3/Random미발견, 733은 양쪽1, 739는 AFS3/Random4입니다. 미발견은 정해진 예산 내 미발견이며 영구적 실패 불가능을 뜻하지 않습니다.

### 환경 다양성: 중복은 없지만 큰 장애물에 집중

유효 환경 11개 AFS와 12개 Random은 각 방법 내에서 16개 수치의 정확한 중복이 없습니다. AFS 실패 7개는 bootstrap 1개와 새 선택 6개이며 재확인 실패는 0개입니다. Random 실패 3개는 bootstrap 1개와 새 선택 2개입니다. 공통 bootstrap 실패가 양쪽에 포함되므로 방법 간 실패 환경 수를 단순 합산해 총 10개 고유 환경이라고 하지 않습니다.

AFS 선택 6개는 box1 폭을 모두 상한 6cm로 골랐습니다. box1 깊이와 box2 폭은 각각 5/6개가 상한 6cm, box2 깊이는 6/6개가 상한 6cm입니다. 두 상자 높이는 5개 환경에서 모두 상한 20cm, 나머지 1개에서 모두 19cm였습니다. 위치와 각도가 달라 정확한 설정은 서로 다르지만, **큰 단면적·높은 장애물을 선택하는 공통 전략**이 강합니다. 따라서 LLM 고유 추론의 효과와 단순 최대 크기 휴리스틱 효과를 현재 비교만으로 분리할 수 없습니다. 두 장애물 각각의 기여나 상호작용도 제거 대조 실험 없이 확정하지 않습니다.

### 실제 실패 행동과 접촉

| 움직임 관찰 분류 | AFS FAIL | Random FAIL |
|---|---:|---:|
| 물체 움직임이 거의 없음 | 6 | 3 |
| 목표 근처까지 이동했으나 native 작업 미완료 | 1 | 0 |

물체 정체 9개 실행 모두 1초 안정화 이후 bowl 몸체 원점의 상승·XY 이동이 1mm 미만입니다. 장애물과 로봇의 접촉 누적 시간은 13.354~13.860초이며 bowl-장애물 접촉은 0초였습니다. 접근 과정의 장시간 로봇 접촉과 물체 정체가 함께 관측됩니다. 이것만으로 파지 불능, 특정 관절 제한, 충돌의 인과성 또는 시각 인식 문제를 확정하지 않습니다.

AFS `seed_727/afs/attempt_00003`은 다른 움직임을 보입니다. bowl 몸체 원점은 안정화 이후 최대 **22.65cm 상승**, XY 최대 **26.70cm 이동**, plate 몸체 원점과 최소 XY 간격 **3.20cm**, 최종 간격 **3.22cm**입니다. 로봇-장애물 접촉 7.614초, bowl-장애물 접촉 1.146초가 기록됐고, 300 step에서 native FAIL입니다. 저장 영상의 1fps 모음을 직접 검토해 물체가 목표 접시 근처로 이동한 것을 확인했습니다. 영상 전체 프레임의 정밀 파지 판독은 수행하지 않았습니다. XY 근접은 원래 성공 조건을 대체하지 않으며, 파지 해제 실패·놓침·배치 방해의 확정 판정은 보류합니다. 프레임 시간은 영상 시간이며 시뮬레이션 시간과 동일하다고 가정하지 않습니다.

모든 실패에 로봇 접촉이 있었지만, 성공에도 AFS1/4, Random3/9에서 접촉이 있었습니다. 접촉만으로 실패를 판정할 수 없습니다. 유효 실행 모두 테이블 아래 낙하 관측은 없었으며 이것은 전체 안전성 보증이 아닙니다. 취소 슬롯에는 물리 측정이 없어 안전 사건 0으로 해석하지 않습니다.

### 비용, 이전 실험과의 관계 및 결론

AFS는 제어 step 합계 2,493, Random은 1,801이었고 AFS 요청 6회에 알려진 입력 160,298 / 출력 17,936 토큰을 사용했습니다. 전체 슬롯 수가 같아도 계산·API·시간 비용이 같지는 않습니다. 토큰 가격이나 통화 비용은 산정하지 않았습니다.

이전 단계별 통로 실험(v3)의 AFS 실패 2개보다 이번 실패 7개가 많고, 이전 10축 실험(v2)의 실패 7개와 총수는 같지만 방법 내 정확히 다른 실패 설정은 v2의 4개에서 이번 7개로 늘었습니다. 그러나 도메인·시드·장애물 크기·예산이 달라 통제된 알고리즘 개선율로 제시하지 않습니다. 특히 정체 양상은 이전에도 관측됐으므로 이번 목표 근처 미완료 1개를 새로운 인과적 실패 계열의 발견이라고 주장하지 않습니다.

**보고서 결론:** 이 16축·두 독립 정적 장애물 개발 실험에서, 취소를 포함해 동일하게 12개 슬롯을 배정했을 때 AFS는 7개, Random은 3개의 작업 실패를 발견했다. 전체 시도당 발견률은 58.33% 대 25.00%였다. AFS의 정확히 다른 실패 설정 7개를 확인했지만 실패 대부분은 물체 정체 양상이며 큰 장애물 선택 편향이 있다. 이는 개발 환경에서의 실패 발견 수율 이점을 지지하며, 일반적·통계적 우월성이나 7개 서로 다른 원인의 증명은 아니다.

추가 유료 실행 없이 개발 실험 보고서를 작성하는 데 필요한 집계·증거·움직임 분석을 완료했습니다. 후속 우월성 검증에는 새로 고정한 시드와 동일 예산, 최대 크기 장애물 휴리스틱 기준선이 적절합니다. 원인 검증은 선택 실패 환경의 장애물 제거/개별 제거 및 같은 설정 반복을 별도 설계해야 하며 현재 결과에 사후로 합산하지 않습니다.

분석 산출물: [전체 검증·분석 JSON](../development/robot_arm_free_pair_analysis_20261024/analysis.json), [실행별 CSV](../development/robot_arm_free_pair_analysis_20261024/episodes.csv), [목표 근처 미완료 영상 모음](../development/robot_arm_free_pair_analysis_20261024/near_goal_frames.jpg). 재현용 `analyze.py`는 같은 폴더에 있으며 scene2test에서 `PYTHONPATH=src .venv/bin/python development/robot_arm_free_pair_analysis_20261024/analyze.py`로 읽기 전용 재검증할 수 있습니다.

## 동일 환경 총 3회 재현 측정 스크립트 (2026-10-24)

사용자 선택은 탐색 전체를 새로 3회 반복하는 것이 아니라 **각 환경 총 3회 실행**입니다. 원본 `free_pair_continuation_v5`의 모든 유효 환경 23개(AFS11/Random12)를 원래 1회차로 사용하고, 동일한 환경·scene_seed·background_seed·정책·300 step 계약으로 2·3회차를 별도 worker에서 실행합니다. 성공 환경도 포함해 실패 사례만 선별하는 편향을 피합니다. 취소 1슬롯은 원본 INCONCLUSIVE로 남기며 재실행·대체하지 않습니다.

scene2test에서 다음 한 줄로 초기 준비와 최대 46회 추가 실행을 진행합니다. API 키나 별도 init 명령은 필요 없습니다.

```bash
bash tools/repeat_robot_arm_three_times.sh
```

46회는 AFS 환경 22회 + Random 환경 24회이며, 최대 추가 제어 step은 13,800입니다. AFS 재제안/API 요청은 0회입니다. 로컬 모델·GPU는 각 worker에서 사용하며 기존 실행의 로딩 비용도 반복될 수 있습니다. 이 준비 작업에서 실제 모델·GPU·로봇 실행은 하지 않았습니다.

독립 결과 폴더는 `experiments/robot_arm_libero/free_pair_reproducibility_3x_v1`입니다. 기존 결과 파일을 복사해 새 실행으로 세지 않고, 원본 후보·receipt·전체 evidence seal 및 동결 소스·모델 해시를 결속합니다. 추가 결과는 `round_2/seed_*/{afs,random}/attempt_*`와 `round_3/...`에 기록합니다. 실행 중 5초 진행 표시와 완료 판정이 출력됩니다. 요약은 `summary.json`으로 저장하며 아래 명령으로 조회합니다.

```bash
.venv/bin/python tools/run_robot_arm_reproducibility.py status
```

환경별 `outcomes`에는 원본·2회차·3회차 판정이 순서대로 들어갑니다. `three_fail`은 3/3 FAIL, `three_pass`는 3/3 PASS, `mixed`는 판정 혼합 환경 수이며, `original_fail_three_fail`로 기존 실패 중 3/3 재현 수를 확인합니다. 미실행·pending·INCONCLUSIVE는 별도로 표시하고 3회 완료에 포함하지 않습니다. 실행할 때마다 완료된 receipt는 건너뛰므로 정상적으로 완료된 구간 뒤에서 이어갈 수 있습니다. 실행 도중 취소·비정상 종료로 intent만 남거나 제외가 발생하면 자동 재시도·대체하지 않고 중단합니다. 동시에 같은 폴더로 실행하는 것은 잠금으로 차단합니다.

같은 seed로 반복하므로 실행·정책의 같은 조건 재현성 측정입니다. 매회 별도 프로세스여도 독립 환경 표본이 아니며 69개 관측을 독립적인 탐색 결과로 합산하거나 재현 FAIL에 고유 실패 환경 credit을 새로 주지 않습니다. 3/3도 실제 실패 확률 100%의 증명은 아닙니다. 기존 58.33% 대 25.00%의 전체 시도 지표는 원본 결과로 유지하고 반복 결과는 별도 신뢰성 분석으로 보고합니다.

## 새 seed 기반 독립 탐색 3세트 (2026-10-24)

동일 환경 총 3회 실행과 별도로, 사용자는 새로운 seed로 AFS·Random 탐색 전체를 3회 수행하는 평가를 승인했습니다. 준비된 root는 `experiments/robot_arm_libero/free_pair_search_repetitions3_v1`입니다. 기존 16축 도메인, 정책·모델, background_seed51000, native 성공 조건, 최대300step/chunk8, 방법별 샘플링 규칙을 유지합니다. 세트마다 방법당12슬롯(총24), 내부 탐색 seed3개×방법당4슬롯, seed별 처음2개 공통 Uniform bootstrap + 이후2개를 유지합니다. 기존 실험과 동일한 AFS 예산을 위해 seed 하나에12슬롯을 몰아 bootstrap/적응형 비중을 바꾸지 않습니다.

독립 세트의 master seed3개를 SystemRandom으로 한 번 추출하고, master별로 새 내부 탐색 seed3개를 결정해 모두 결과 전에 동결했습니다. 세트 간9개 내부 seed는 겹치지 않습니다. 기하학적 유효성이나 성공/실패를 본 후 seed를 골라내지 않았습니다. master는 세트 표본 추출용이며 실제 정책 seed는 기존 `scene_seed=search_seed*100+index` 규칙을 따릅니다. 세트·seed·방법별 이력은 새로 시작하고, 과거23환경·69회 재현 결과나 과거 AFS 응답은 가져오지 않습니다. 공통 bootstrap도 양쪽에서 새로 실행합니다.

scene2test에서 실행:

```bash
bash tools/run_robot_arm_search_repetitions.sh --live
```

상태 조회(모델/로봇/API 실행 없음):

```bash
bash tools/run_robot_arm_search_repetitions.sh --status
```

옵션 없이 실행하면 고정 계획만 표시합니다. 별도 init·폴더 삭제는 필요 없습니다. 총72개 새 슬롯(AFS36/Random36), 제어 최대21,600step, AFS 요청 최대18회(세트당6)입니다. 로봇은 로컬 GPU GR00T, AFS는 기존 OpenRouter `openai/gpt-6-luna-pro`이며 사용자의 터미널 OPENROUTER_API_KEY가 필요합니다. 준비 중에는 실제 API·GPU추론·로봇을 실행하지 않았습니다.

`set_1`, `set_2`, `set_3`는 각자 별도 manifest·후보·요청·원본 응답·영상·측정을 기록합니다. root의 `repetitions.json`과 `repetitions.sha256`에 seed·설계·각 manifest 해시가 고정돼 있습니다. 루트 잠금으로 중복 배치를 방지하고, 완료 슬롯은 기존 실행기 규칙대로 건너뜁니다. intent만 남은 중단·애매한 API·초기 기하 오류·제외는 재시도·대체·예산 초기화하지 않고 정지합니다. 실패한 세트를 숨겨 남은 세트만으로 평균을 내지 않습니다. 전체 3세트 완료 후에만 평균·표준편차를 공개합니다. 새 seed가 실패 종류를 다양하게 만들거나 기하학적으로 모두 유효할 것을 보장하지 않습니다.

집계는 root의 `replication_summary.json` 및 `replication_summary.txt`입니다. 주 지표는 **각 세트 native FAIL 수 / 방법별 배정12슬롯**이며 제외는 FAIL이 아니고 발견 수0으로 분모만 소비합니다. 유효 실행 기준 FDR과 제외/pending도 각 세트 원본 summary에 별도로 기록합니다. 3개 세트 발견률의 산술평균과 **표본 표준편차(ddof=1)**, 세트별 AFS−Random 차이의 평균·표본 표준편차를 계산합니다. 비율 평균은 %, 표준편차와 차이는 %포인트로 표시합니다. 단순히72실행을 독립표본으로 묶어 표준편차를 계산하지 않습니다. 3세트뿐인 개발 평가이며 통계적 우월성은 자동 선언하지 않습니다.

실패 다양성은 고유 실패 설정·정확한 반복·움직임 패턴과 함께 검토합니다. 설정이 달라도 같은 물체 정체 양상일 수 있고, 현재 실패 목적함수는 큰 상자·기존 실패 재확인 선택을 금지하지 않습니다. 단순 최대 크기 휴리스틱 대조나 인과적 실패 유형 검증은 이번 고정 프로토콜에 포함되지 않습니다. 이후 측정 결과는 기존 동일 seed 3회 재현성 실험과 분리해 보고합니다.
