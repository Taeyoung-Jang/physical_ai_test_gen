# Slalom 회귀 첫 시도: EGL 시스템 라이브러리 누락으로 시작 전 종료

2026-09-29 UTC. 사용자는 회귀 실행 결과의 정상 여부를 문의했다.
로그/시스템 읽기 진단만 수행하고, 이 이력 외 코드·suite·시스템 패키지는 변경하지 않았다.
유료 API/GPU 로봇 실험을 재실행하지 않았다. 시작 시 git worktree는 clean이었다.

## 확인한 결과

- Suite: `/workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928`
- 사용자 report: `reports/20260929T150931_488657Z/report.html`
- `attempts/attempt_00000/receipt.json`: returncode 1, wall 3.890220679109916초, interrupted null.
- 상태 NEEDS_ATTENTION, pending null, attempted 1/2, excluded 1, valid PASS/FAIL 0.
- reader 결과 INCOMPLETE / INCONCLUSIVE, exclusion_reason `missing_manifest`.
- `rollout/` 자체가 만들어지지 않았다. MP4, 결과/manifest, API usage 자료도 없다.
- 보고서의 null은 미측정이다. 이를 0으로 소급 기록하거나 로봇 FAIL로 바꾸지 않았다.

## 직접 확인한 원인

`attempts/attempt_00000/process.log`:

```text
run_robot_goal_agent.py:77 → import robot_vlm.goal_runner
goal_runner.py:13 → import mujoco → mujoco.egl → OpenGL.EGL
AttributeError: 'NoneType' object has no attribute 'eglQueryString'
```

현재 환경에서:

- Ubuntu 24.04.3 LTS.
- `nvidia-smi -L`: NVIDIA RTX PRO 4500 Blackwell 인식.
- `ctypes.util.find_library("EGL")` → None.
- `ctypes.CDLL("libEGL.so.1")` → 파일 없음 OSError.
- dpkg: libglvnd0 1.7.0-1build1 설치, libegl1/libegl-mesa0 미설치.
- NVIDIA `libEGL_nvidia.so.0`, vendor 설정 `/usr/share/glvnd/egl_vendor.d/10_nvidia.json` 존재.
- vendor 라이브러리의 ldd 의존성은 해석된다. NVIDIA_DRIVER_CAPABILITIES=compute,utility이지만
  실제 vendor 파일은 있으므로 변수만으로 graphics 전체 미노출이라고 단정하지 않는다.
- 누락된 것은 현재 PyOpenGL이 로딩하려는 vendor-neutral EGL dispatch 라이브러리다.
  2026-09-28 첫 AFS pilot과 동일한 시작 오류 계열이다.

실행 코드 순서를 확인했다. 이 import는 run-dir 생성, policy 인스턴스 생성,
robot run 및 API 요청 전에 위치한다. 이번 자식 프로세스는 GPT 호출/물리 실행 전 종료했다.
따라서 API key 인증 오류, 추론 deadline, goal 미달성, AFS 발견 실패가 아니다.

## 사전 검사 한계

앞서 안내 전에 실행한 `_fresh()`는 source/dependencies/robot XML·mesh·YAML·ONNX 및
baseline archive 무결성을 검사했다. 시스템 libEGL 및 실제 렌더링 context는 검사하지 않았다.
그 검사를 통과했다고 런타임 전체가 준비됐다고 볼 수 없다. 421개 CPU/합성 검사도
새 컨테이너에서 live MuJoCo EGL 렌더러를 시작했다는 증거가 아니다.
후속 개선은 공통 live launcher의 무료 EGL context preflight와 명확한 시작 오류 노출이다.
현재 요청은 결과 확인이므로 코드 변경은 하지 않았다.

## 복구 제안 (이 진단에서 실행하지 않음)

root RunPod 터미널:

```bash
apt-get update
apt-get install -y --no-install-recommends libegl1
```

공식 Ubuntu noble 패키지는 EGL dispatch 지원을 제공한다:
[libegl1](https://packages.ubuntu.com/en/noble/amd64/libegl1).
컨테이너의 NVIDIA 호스트 드라이버 교체/재설치를 우선 권하지 않는다.

`scene2test`에서 API 없이 실제 EGL context 확인:

```bash
MUJOCO_GL=egl uv run --no-sync python -c 'import mujoco; from OpenGL import GL; ctx=mujoco.GLContext(64,64); ctx.make_current(); print("EGL_OK", GL.glGetString(GL.GL_RENDERER).decode()); ctx.free()'
```

EGL_OK 및 NVIDIA renderer를 확인하고, 다른 code/resource drift가 없을 때만 남은 한 시도를 명시적으로 허용한다:

```bash
uv run --no-sync python tools/run_behavior_regression.py run --suite /workspace/g1_failure/runtime/behavior_regression/slalom_luna_20260928 --live --max-new-attempts 1 --continue-after-exclusion
```

이 명령은 유료 API/GPU 실행이며 남은 시도 1회, 로봇 호출 최대10회다.
첫 제외 시도를 지우거나 슬롯을 복원하지 않는다. 두 번째가 VALID PASS라도 suite는
COMPLETE_WITH_EXCLUSIONS이고 엄격한 반복 비교는 INCONCLUSIVE일 수 있다.
이는 두 번째 실행 실패를 뜻하지 않는다. 유효 2회 비교가 필요하면 환경 복구 후 새 이름으로
별도 suite/budget을 초기화하고 이전 제외/비용도 보존한다.
코드 drift가 발생하면 강제로 우회하지 않는다. 패키지 복구만으로 성공을 보장하지 않으며
반드시 context 검사 후 다음 단계로 진행한다.
