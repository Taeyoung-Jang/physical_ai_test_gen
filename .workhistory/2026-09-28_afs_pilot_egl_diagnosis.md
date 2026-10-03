# 첫 live AFS 파일럿 중단: EGL 시스템 라이브러리 누락

날짜: 2026-09-28 UTC.

## 사용자 제공 실행 및 판정

- 캠페인: `/workspace/g1_failure/runtime/afs_benchmark/20260928T033700_667656Z`
- 첫 `attempt_00000`은 AFS arm의 paired_uniform_cold_start였다.
- receipt: returncode 1, wall 4.25005941092968초, interrupted null.
- 유효 rollout: AFS 0 / Random 0. 제외 1, AFS 제안 요청 0.
- reader는 rollout manifest가 없으므로 INCOMPLETE / INCONCLUSIVE로 판정했다.
  최초 목표를 시도한 완결된 실행이 아니므로 로봇 FAIL 또는 AFS 실패 발견으로 세면 안 된다.
- wrapper는 exit 2로 추가 실행을 중단했다. 내부 READY/invocation_limit은 캠페인이
  재개 가능한 상태라는 뜻이지 실험 성공이나 16회 완료를 의미하지 않는다.

## 직접 확인한 원인

`attempts/attempt_00000/process.log`에서 다음 순서로 실패했다.

```text
run_robot_goal_agent.py: import robot_vlm.goal_runner
  → import mujoco → EGL backend → PyOpenGL
  → AttributeError: 'NoneType' object has no attribute 'eglQueryString'
```

환경 진단 결과:

- Ubuntu 24.04.3 LTS, NVIDIA RTX PRO 4500 Blackwell / driver 580.126.20은 nvidia-smi에서 인식됨.
- `ctypes.util.find_library("EGL")`는 None.
- `ctypes.CDLL("libEGL.so.1")`는 파일 없음 OSError.
- dpkg에서 libegl1은 설치된 것으로 확인되지 않았다. libglvnd0/libgl1/libglx0은 설치되어 있다.
- NVIDIA vendor library `libEGL_nvidia.so.0`와 `10_nvidia.json`은 존재하며 ldd 의존성은 해석된다.
- 환경 변수 NVIDIA_DRIVER_CAPABILITIES는 compute,utility지만 NVIDIA EGL vendor 자원은 실제로
  존재한다. 따라서 이 변수만 보고 드라이버 전체가 없다고 판단하거나 Pod 재생성을 먼저 권하지 않는다.
- PyOpenGL의 로더는 libEGL 로딩 실패 시 None을 반환한다. 그 후 eglQueryString 접근에서
  AttributeError가 발생하는 것이 현재 로그와 일치한다.
- `apt-get -s install --no-install-recommends libegl1`은 현재 패키지 목록에서 해당 패키지를
  찾지 못했다. 복구 시 apt-get update가 먼저 필요하다. 실제 설치/목록 갱신은 하지 않았다.

이 실패는 API 인증/응답 timeout이 아니라 MuJoCo import 시점의 환경 오류다.
코드상 policy 생성/모델 호출/로봇 loop 이전에 종료했다. 다만 기존 보고서의 미측정 API 사용량
null을 소급해서 0으로 변경하지 않았다.

## 제안한 복구 순서 — 아직 실행하지 않음

root RunPod 터미널에서 시스템 EGL dispatch 라이브러리를 설치한다.

```bash
apt-get update
apt-get install -y --no-install-recommends libegl1
```

실험 디렉터리에서 API 호출 없이 EGL context 및 NVIDIA renderer를 확인한다.

```bash
MUJOCO_GL=egl uv run --no-sync python -c 'import mujoco; from OpenGL import GL; ctx=mujoco.GLContext(64,64); ctx.make_current(); print("EGL_OK", GL.glGetString(GL.GL_RENDERER).decode()); ctx.free()'
```

이 검사가 정상이고 코드/모델/설정이 그대로라면, 키가 설정된 터미널에서 명시적으로 재개한다.
이미 제외된 시도와 원본 로그는 유지한다. 현재 시스템 EGL 라이브러리는 동결 해시의 대상이 아니므로
복구 내용을 환경 이력으로 별도 기록해야 한다. 재개에서 다른 drift 검사가 실패하면 강제 우회하지 않는다.

```bash
uv run --no-sync python tools/run_afs_pilot.py --live --campaign /workspace/g1_failure/runtime/afs_benchmark/20260928T033700_667656Z
```

추가 보완점: 현재 초기화는 Python 패키지/코드/자원을 확인하지만 실제 EGL context 생성까지
사전 검증하지 않는다. 유료 실행 전 렌더링 preflight가 있으면 이 오류를 rollout 시작 전에 찾을 수 있다.
이번 요청은 결과 확인이므로 실행 코드 변경이나 시스템 설치, 유료 재실행은 하지 않았다.

## 참고 및 보존

- [Ubuntu libegl1 파일 목록](https://packages.ubuntu.com/jammy/amd64/libegl1/filelist): EGL dispatch 파일 확인.
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html): graphics capability와 컨테이너 드라이버 노출의 구분.
- 로그/패키지/라이브러리 조회만 수행했다. 실제 키 값은 조회하지 않았으며 원본 캠페인·보고서·예산은 수정하지 않았다.
- 작업 이력 외에 새 코드 변경은 없다. 기존 미커밋 작업은 보존했다.
