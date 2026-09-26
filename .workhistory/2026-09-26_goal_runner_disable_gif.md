# Goal runner GIF 저장 및 전체 프레임 누적 비활성화

날짜: 2026-09-26 UTC.
사용자 요청: "GIF는 그냥 저장하지 마세요. 주석 처리 바랍니다. 그러면 되나요?"

## 원인과 변경 범위

직전 실험 `20260926T151327_858717Z`는 MP4/terminal_state까지 저장된 반면,
GIF/result/report/manifest 저장은 완료되지 않았다. 전체 RGB frames 약 8GiB를
보유한 상태의 일괄 GIF 변환과 컨테이너 OOM-kill 기록을 근거로 GIF 후처리의
메모리 한도 초과가 강하게 의심되었다. 대상 PID/시각 직접 확인은 하지 못했다.
세부 진단은 `2026-09-26_goal_outcome_run_151327_review.md`에 보존했다.

이번 변경은 격리된 `robot_vlm/goal_runner.py`에 한정한다.
다른 Panda/terrain/velocity-only 실행기의 GIF 기능을 일괄 변경하지 않는다.

## 구현

- `frames` 리스트 초기화, 매 프레임 `frames.append(arr)`, 마지막
  `imageio.mimsave(...rollout.gif...)` 호출을 모두 주석 처리했다.
- GIF 호출만 끄고 RGB 리스트를 계속 쌓으면 긴 실행에서 메모리 문제가 남으므로
  전체 프레임 누적도 함께 껐다. MP4의 `video.append_data(arr)`는 유지했다.
- report.html의 존재하지 않는 GIF 링크를 제거하고 MP4-only 안내를 넣었다.
- protocol에 video 파일/fps, gif_enabled=false, retain_frame_history=false를 기록한다.
- 목표 판정/모델/프롬프트/관측/제어/물리/호출 및 시간 예산은 바꾸지 않았다.
  source hash 및 기록 계약이 바뀌므로 이전 실행과 자동으로 동일 조건으로 합치지 않는다.
- 현재 사용 문서와 AGENTS의 영상 산출물 설명을 MP4-only로 맞췄다.

## 검증 방법

기존 CPU 실행 루프 테스트에서 GIF writer를 조용한 no-op으로 대체하던 부분을
호출되면 즉시 실패하는 검사로 변경했다. 정상/실패/오류 경로에서 result.json,
report.html, manifest 보존과 GIF 미생성을 확인한다.

별도 테스트는 실제 설치된 ffmpeg MP4 writer/reader를 사용한다. 물리/정책은
CPU MuJoCo와 가짜 제어기/정책이며, 실제 G1 CUDA/VLM 실험이 아니다.
프레임의 weak reference로 전체 프레임이 살아남아 누적되지 않는지 검사하고,
MP4 파일 생성/디코딩/12fps 및 result/report/manifest 수록 여부를 확인한다.

검증 명령 (`scene2test`):

```bash
.venv/bin/python -m pytest tests/test_goal_outcome_runner.py tests/test_goal_outcome.py -q
.venv/bin/ruff check src/robot_vlm/goal_runner.py tests/test_goal_outcome_runner.py
git diff --check
```

결과: **23 passed (14.21초)**. 실제 ffmpeg MP4 인코딩/디코딩과 프레임 참조
해제 검사 포함. Ruff `All checks passed!`, `git diff --check` 통과.

## 보존·제한

기존 실험 폴더/영상/GIF/실패 기록은 삭제하거나 변경하지 않았다.
직전 run의 누락된 결과를 복구한 것은 아니며 별도의 재실행도 하지 않았다.
새 실행에서는 GIF 후처리와 누적 메모리 경로가 없어지지만 다른 모든 원인의
메모리/디스크/인코더 장애까지 없어진다고 보장하지 않는다.
명령어 변경은 필요 없다. 유료 API/GPU 실행 0회, commit/push 없음.
