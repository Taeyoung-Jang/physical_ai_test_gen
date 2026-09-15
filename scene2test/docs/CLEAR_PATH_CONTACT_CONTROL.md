# 접촉 피드백 밀기·손 회수 단위 시험

2026-09-15. 기존 `push_probe.py`의 v4 실행기는 그대로 보존한다.
새 실행기는 `contact_probe.py`, 상위 제어는 `contact_control.py`이며,
기존 `ArmGaitController`의 CUDA Walk.onnx 및 scratch IK/관절 제어를 재사용한다.

## 실행

`scene2test` 디렉터리, 기존 CUDA/GR00T 설치 환경:

```bash
uv run python tools/run_clear_path_contact.py
uv run python tools/run_clear_path_contact.py --initial-y 0.02
uv run python tools/run_clear_path_contact.py --initial-y -0.02
```

기본 결과 위치는 `/workspace/g1_failure/runtime/clear_path_probes/<UTC>/`.
`report.html`에서 실제 물리 실행 MP4/GIF, 접촉·상태 기록, 결과와 실행 조건을 조회한다.
기본 실행은 18초이며 `--duration`은 16~20초 범위의 총 실행 제한이다.
GPU가 없으면 CPU로 조용히 대체하지 않고 실패한다. GPT/API 호출은 없다.

## 고정된 조건과 제어

- 같은 2kg 상자, 마찰 설정, 원래 로봇/벽 형상. 초기 로봇 x=3.2m인 근접 시험.
- GT 상자 위치와 로봇 위치를 이용한다. 영상은 기록용이지 제어 입력이 아니다.
- 0~2초 정착 → 2~5초 손 뻗기 → 최대 13초까지 전방 밀기.
- 손 x 목표는 상자 서쪽 면+2cm를 참고하되, 로봇 base 기준 24~30cm로 제한한다.
- 전진 명령 상한 0.22m/s. 직전 step의 손 접촉별 최대 법선력이 40N을 넘으면
  감속하고 80N 이상이면 전진 명령을 0으로 한다. 힘 목표 추종 제어는 아니다.
- 상자 x 이동이 12cm 이상이거나 13초가 되면 2초간 손 목표를 몸 쪽/위로 회수하고
  base 목표를 당시 위치보다 12cm 뒤로 둔다. 이후 회수 자세를 유지한다.
- 손 회수 완료는 마지막 상태에서 연속 0.5초 이상 손/상자 접촉 없음으로 판정한다.
  이는 접촉 해제 기준이지 특정 관절 홈 자세 도달 보증은 아니다.
- 기존 120N 접촉별 힘 제한, 넘어짐, 금지 robot/world 접촉, 수치 이상,
  외력 주입 검사 유지. 자기충돌 분류는 아직 미구현이다.

합격은 최종 상자 x 이동 **>8cm**, 실제 손 접촉, 손 회수 완료, 유효 실행,
넘어짐·금지 접촉 없음, 정상 시간 종료를 모두 요구한다. 12cm는 제어 종료 목표이고
8cm는 이전부터 고정된 단위 시험 합격 기준이다. 둘을 혼동하지 않는다.
완료된 FAIL 실행도 종료코드 0일 수 있으므로 `result.json`을 확인한다.

## 해석 경계

이전 v4는 밀기 4초, 이번 조건은 최대 8초이다. 손 목표/속도/실행 시간도 바뀌므로
개선량을 접촉 피드백 하나의 효과로 해석할 수 없다. 인과 비교에는 동일 예산의
ablation이 필요하다. +/-2cm 초기 위치 시험은 민감도 점검이며 일반 성공률이 아니다.

앞으로 접근 → 옆 공간으로 치우기 → 지도 갱신 → 통과까지 별도 검증해야 한다.
이번 전방 밀기는 통로 개방 자체를 보장하지 않는다. `clear_path_success=null`을
유지하며 아직 GPT의 실행 가능한 일반 `push_object` 행동으로 등록하지 않는다.
상세 실행 수치는 `.workhistory/2026-09-15_clear_path_contact_control.md`에 기록한다.
