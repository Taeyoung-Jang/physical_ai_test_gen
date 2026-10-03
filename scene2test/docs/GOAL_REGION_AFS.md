# 목표 주변 물체 배치와 AFS 탐색

2026-10-02. `clear-path-goal-region-v4`는 기존 통로와 정적 블록 두 개를 유지하고,
같은 이동 가능한 상자를 목표 주변에 배치하는 새 18축 도메인이다. SceneGraph,
지도, 물리 XML, 로봇 관측과 AFS 장면 설정이 같은 배치를 사용한다.
상자 하나를 추가하거나 목표를 옮긴 것이 아니다. 로봇 행동과 목표 판정은 그대로다.

장면 생성·실제 G1 자산의 CPU 합성·합성 AFS 캠페인 연결을 검증했다.
사용자가 실행한 빈 목표 장면 한 회는 Luna/CUDA에서 VALID/PASS로 확인됐다.
4회 호출, 59.560 시뮬레이션 초, 최종 거리 0.115714m, 목표 반경 내 1초 체류다.
이후 부분 점유 한 회도 같은 로봇 조건에서 PASS였다. 목표 중심 경로가 거절된 뒤 GPT가
중간 지점과 직접 속도 이동을 선택해 10번째 호출 중 성공했다. 198.570초, 목표 거리
0.190542m, 1초 체류이며 상자는 움직이지 않았다. 두 성공은 밀기·복구 검증이 아니고,
실패 경계·일반 성공률·전체 점유·AFS 성능은 아직 검증하지 않았다.
[빈 목표 결과](../../.workhistory/2026-10-02_goal_region_clear_live_pass.md)와
[부분 점유 결과와 계획기 한계](../../.workhistory/2026-10-02_goal_region_partial_live_pass.md)를 참조한다.
네 번째 유형은 [작업자 근접 측정 설계](HUMAN_PROXIMITY_CONTRACT.md)로 별도 진행한다.
이 장면에는 사람이 없으며 공식 판정 규칙 수는 여전히 세 개다.

두 성공 후의 다음 개발 실험은 [행동 근거 기반 양쪽 배치 제안](AFS_PAIRED_GOAL_CONTRASTS.md)이다.
부분 점유를 기준으로 LLM이 상자의 측면 위치만 두 개 제안하고, 기준 반복과 함께 총 세 번
실행할 수 있도록 준비한다. 최대 AFS 1회 + 로봇 API 30회이며 유료 실행은 별도 명령이다.
18축 전체 AFS/Random 비교보다 작은 개발용 대조이고 실패 경계는 실제 결과 후에만 판단한다.

## 변경 가능한 환경과 유지되는 로봇 조건

기존 17축에 `box_goal_x_m` 한 축을 추가했다. 상자는 중앙의 X=4 대신
X=6.8–7.5m에서 시작하며, 나머지 도메인은 기존 v3의 범위를 유지한다.

| 항목 | 값 또는 의미 |
|---|---|
| 상자 X | `box_goal_x_m` 6.8–7.5m |
| 상자 Y | `box_lateral_fraction * (corridor_width_m / 2 - 0.55 - 0.05)` |
| 상자 | 같은 동적 상자 1개, 크기 0.8 × 1.1 × 0.7m |
| 정적 블록 | 기존 위치 범위의 블록 2개, 둘 다 상자보다 앞에 위치 |
| 로봇 시작 | `(1, 0)` |
| 최종 목표 | `(7, 0)`, 반지름 0.25m, 체류 1초 |
| 새 기술 | 없음. 기존 이동·계획·관측·선택적 밀기를 사용 |

통로 폭을 바꾸면 상자와 블록의 Y도 바뀔 수 있다. `box_goal_x_m`는 상자 위치이지
로봇의 중간 목표나 밀기 목표가 아니다. AFS는 scene만 제안하고 로봇이 방법을 선택한다.

두 번째 정적 블록의 최대 X 끝은 약 6.316m, 상자의 최소 X 끝은 6.4m다.
상자의 최대 X 끝은 7.9m이므로 X=8 벽과도 겹치지 않는다. Y는 기존 벽 여유 0.05m를
유지한다. 이 범위는 초기 객체 관통을 피하지만 접근·조작 성공을 보장하지는 않는다.
경로 없는 장면을 제거하거나 점유를 이유로 미리 FAIL을 붙이지 않는다.

## 세 가지 개발용 장면

아래 장면은 상자의 측면 배치만 다르다. 파일의 이름은 기하 상태이지 실험 결과가 아니다.

| 설정 파일 | 상자 중심 | 초기 목표 점유 | 정적 지도 예제 |
|---|---|---|---|
| `config/scenes/goal_region_clear.json` | `(7, 1.4)` | 없음 | 경로 있음 |
| `config/scenes/goal_region_partial.json` | `(7, 0.7)` | 일부 겹침 | 경로 없음 |
| `config/scenes/goal_region_covered.json` | `(7, 0)` | 목표 원 전체 점유 | 경로 없음 |

부분 점유에도 정적 경로가 없는 것은 로봇 발자국 여유가 필요하기 때문이다.
그러나 상자는 이동 가능하므로 정적 no_path가 전체 목표 불가능성을 증명하지는 않는다.
AFS가 점유를 완화하거나 질량·마찰·주변 장애물을 바꾸는 비교를 제안할 수 있다.
처음부터 로봇에게 상자를 특정 방향으로 밀도록 지시하지 않는다.

## API 없이 먼저 확인하기

모든 명령은 다음 경로에서 실행한다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
```

세 장면의 PNG·HTML·SceneGraph·지도·XML을 생성하고 실제 G1 XML의 관절·구동기
보존을 CPU에서 확인한다. `--audit-robot`은 보행 모델 실행이나 GPU 추론이 아니다.

```bash
uv run --no-sync python tools/preview_corridor_scenes.py --preset goal_region --audit-robot --output-root /workspace/g1_failure/runtime/goal_region_previews
```

외부 G1 자산이 없다면 `--audit-robot`을 빼고 생성기만 확인할 수 있다.
`REPORT`에 HTML 경로가 출력된다. PNG의 점선은 참고 지도 경로이며 로봇 궤적이 아니다.
정적 미리보기이므로 MP4/GIF를 생성하지 않는다. 실제 rollout은 기존처럼 MP4만 기록한다.

새 장면의 지원 감사를 실행한다.

```bash
uv run --no-sync python tools/audit_failure_domain.py --schema clear-path-goal-region-v4
```

이제 초기 목표 점유는 `CONSTRUCTIVE_INITIAL_OCCUPANCY`로 확인되지만, 실제 실패
유형 측정은 없으므로 Coverage는 null이다. 규칙 수가 세 개라 READINESS는 계속
`INSUFFICIENT_RULE_SUPPORT`다. 기존 기본 v3 감사의 결과가 바뀌어야 한다는 뜻은 아니다.

AFS 캠페인 계획만 확인한다. 파일·로봇·API를 생성하거나 실행하지 않는다.

```bash
uv run --no-sync python tools/run_afs_pilot.py --config config/behavior_afs_goal_region_luna.json
```

## 실제 실행 명령과 예산

아래부터는 사용자가 API 키를 설정하고 명시적으로 실행하는 유료 실험이다.
기존 runtime 캠페인에 새 코드를 섞어 재개하지 않는다. 폭 3.2m 실험도 재시도하지 않는다.
새 장면에서의 로봇 동작 확인은 먼저 빈 목표 한 회로 시작할 수 있다.

```bash
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --navigation-completion goal_dwell_v1 --scene-config config/scenes/goal_region_clear.json
```

부분/전체 점유는 파일 이름만 각각 `goal_region_partial.json`, `goal_region_covered.json`으로
바꾼 별도 실행이다. 각 실행은 최대 로봇 API 10회이며 호출 수 제한이 금액 제한은 아니다.
실패하더라도 임의로 목표나 호출 예산을 늘려 이전 결과와 합치지 않는다.

빈 목표 PASS 다음의 **부분 점유 한 회** 실행 명령:

```bash
uv run --no-sync python tools/run_robot_goal_agent.py --live --model gpt-6-luna --max-calls 10 --enable-push --response-timeout 300 --evaluation-profile goal_outcome_v1 --navigation-completion goal_dwell_v1 --scene-config config/scenes/goal_region_partial.json
```

상자의 측면 fraction만 1.0에서 0.5로 바뀐다. 로봇의 방법 선택에는 개입하지 않는다.
2026-10-02 준비 점검에서 기준 PASS와 현재 소스·자산·런타임의 일치를 확인했다.
준비 당시 에이전트 환경에는 키가 없었지만 이후 사용자 실행에서 PASS를 확인했고,
실행 후 조건도 같은 것으로 검증했다. 이것은 운영자 선택 대조이지 LLM 제안 표본이 아니다.
재실행은 새로운 비용이며 자동으로 수행하지 않는다.

전체 18축 AFS/Random을 실행하려면 다음 명령을 사용한다.

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --config config/behavior_afs_goal_region_luna.json
```

설정은 Luna/Luna, seed 17, 방법별 유효 목표 6회/최대 시도 6회다. 합계 최대 12회,
로봇 API 최대 120회, AFS 제안 최대 2회다. 제외 시도도 소모하며 자동 대체·재시도하지 않는다.
시간 상한과 기본 출력 토큰 상한은 추가하지 않았다. 초기 2개 장면은 양쪽이 같은 값으로
별도 실행하고 각각 비용을 부담한다. Random은 18축 전체 독립 균등 분포다.
세 개발용 장면을 캠페인의 성공/실패 이력에 미리 주입하지 않는다.

## AFS가 새 배치를 사용하는 방식

요청 스키마와 호스트 검증이 새 축을 v4에서만 허용한다. LLM은 SceneGraph의 초기
점유 기하와 실제 이전 행동 근거를 보고 완화·대체 설명·경계 가설을 제안할 수 있다.
초기 점유 설명을 실제 실행 중에도 유지된 사실로 해석하지 않으며, 물체 이동은 기존
행동 계측 기록으로 확인한다. LLM의 설명 자체를 원인이나 실패 라벨로 쓰지 않는다.

기존 `hypothesis-v2` 선택, 반복 실패 근방 억제, 독립 탐색과 반복 슬롯을 재사용한다.
같은 조건의 PASS/FAIL이 있어야 관측 bracket을 만들며, 그렇지 않으면 탐색 후보다.
기존 단일 축 대조와 회귀 실행기도 새 축을 지원하지만 v3 이력을 v4 장면으로 바꾸어
동일 조건 반복이라고 부르지 않는다. CLI의 standalone `run_behavior_afs.py`는 여전히
기존 3축 경로이며 새 18축 실행은 위 campaign 경로를 사용한다.

## 검증 범위

초기 비관통 범위, SceneGraph/지도/XML 일치, CPU G1 자산, 새 축 출력 제한,
완화 제안의 실제 후보 선택, 합성 6+6 폐루프·재개·예산, 관측 bracket과 XML 변조
거부를 검사했다. 실제 로봇의 물체 제거 성공, 네 번째 유형 발견, 최종 4/6 Coverage
또는 AFS 우월성을 검증한 것은 아니다. 자세한 결과는
[작업 이력](../../.workhistory/2026-10-02_goal_region_afs_and_human_contract.md)에 기록한다.
