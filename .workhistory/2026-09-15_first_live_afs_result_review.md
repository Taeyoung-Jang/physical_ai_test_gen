# 최초 live AFS 결과 검토

검토일: 2026-09-15 UTC.
사용자가 실행한 결과:
`/workspace/g1_failure/runtime/llm_afs_expanded/20260915T142433_169376Z`.
명령: `uv run python tools/run_expanded_afs_checked.py --live --samples 4 --seed 17`.

## 저장된 결과

- origin=openai_api, API response status=completed, model=gpt-6-astra.
- 호출 1회, 후보 생성 시도 4회, READY 3개, INVALID_SCENE 1개.
- valid_robot_rollouts=0: 로봇 실행 결과가 아님.
- 응답 usage: input_tokens=19454, output_tokens=1321, total_tokens=20775.
  output reasoning_tokens=140. 비용은 계산하지 않음.
- 전달된 observations=0. 이번 제안은 과거 실제 rollout feedback에 적응한 결과가 아님.

## LLM 제안

1. ramp_then_obstacles: 경사 8–12도, 마찰 .15–.30, 장애물 3–4개,
   random 배치, 장애물 x/y 최대 치수 .4–.6m.
2. obstacles_then_ramp: 장애물 3–4개 random 배치 뒤 경사 8–12도/마찰 .15–.30.
3. stairs_then_bottleneck: 계단 3–4개, 높이 .12–.18m, 디딤판 .30–.45m,
   통로 폭 1.10–1.35m, 통로 마찰 .15–.30.
4. rough_then_friction: 폭 1.6–2.0m, 요철 진폭 .08–.12m,
   셀 길이 .35–.50m, 후속 구간 마찰 .10–.22.

모델은 각 가설을 untested로 표기하고 GT 지도/위치와 카메라 미사용 조건을 인지함.
출력 설명은 가설이며 원인/실패의 사실 판정이 아님.

## 실제 추출된 후보

| 후보 | 추출 방식 | 조건 요약 | 상태 |
| --- | --- | --- | --- |
| 0000 | new_space | ramp→obstacles, 경사 1.93도, 마찰 .513, 장애물 1개 | READY |
| 0001 | new_space | obstacles→ramp, 경사 7.25도, 마찰 .204, 장애물 0개 | READY |
| 0002 | llm_joint_space | ramp→obstacles, 경사 11.33도, 마찰 .156, random 장애물 4개 | INVALID |
| 0003 | new_space | stairs→bottleneck, 계단 3개/높이 .0923m, 통로 1.833m | READY |

0002 reason: `refusing to export a disconnected world`.
이 기록만으로 어느 요소가 지도 단절을 일으켰는지 단정하지 않음. 로봇 실패가 아님.
모델이 제안한 공간은 4개지만 4-attempt 스케줄에서 LLM 슬롯은 하나뿐이므로
첫 번째 제안만 실제 추출됨. 유효한 3개 모두 전역 탐색 후보라는 점이 중요함.

## 해석과 검증 범위

실제 API→구조화 제안→호스트 검증/후보 생성 경로의 성공 증거다. 아직 LLM이
유효한 실패 장면을 발견했다는 증거도, Random/Sobol보다 우수하다는 증거도 아님.
다음 로봇 실행을 하더라도 이 세 후보만으로 LLM 제안의 효과를 평가할 수 없음.

검토에서는 설정/문맥/요청/proposal/suite 저장 해시와 제안 범위를 대조하고 READY
번들의 revision·산출물·재생성 graph/map 검사를 수행한다. 새 API 호출, GPU 실행,
코드 변경은 하지 않으며 기존 결과를 보존한다. PNG는 장면 미리보기이며 rollout
영상이 아니다. 런타임 산출물은 원래 경로에 유지한다.
