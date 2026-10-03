# 새 17축 obstacle AFS 캠페인 준비 — 유료 실행 전

2026-09-29 UTC. 사용자 요청: slalom 회귀 분석 이후 다음 단계 진행.
직전 회귀 suite는 시도 2회를 소진했고, 제외 1회 + 유효 목표 FAIL 1회로 완료됐다.
로봇 성능 수정이나 소진된 회귀 예산 복원이 아니라, 로봇 조건을 고정한 새 AFS 탐색을 준비했다.

## 수행 범위와 보존

- 기존 EGL 진단/회귀 분석 문서의 미커밋 변경을 보존했다.
- 기존 캠페인·회귀·원본 rollout을 수정하지 않았다. 로봇/AFS 실행 코드와 설정도 변경하지 않았다.
- 새 캠페인만 초기화하고 초기 보고서를 생성했다. 유료 API, 로봇 rollout, GR00T 추론은 실행하지 않았다.
- 문서에 복사 가능한 준비된 캠페인의 실행 명령을 추가했다. commit/push는 수행하지 않았다.

## 환경 사전 확인

- `.venv/bin/python`에서 `OPENAI_API_KEY`의 비어 있지 않은 등록 여부만 검사: `MISSING`.
  키 값이나 다른 셸/설정 파일의 비밀정보를 조회하지 않았다.
  이는 에이전트 프로세스 환경의 상태이며, 사용자 터미널에 키가 없거나 잘못되었다는 뜻이 아니다.
- `MUJOCO_GL=egl`로 `mujoco.GLContext(64,64)` 생성, `make_current()`,
  `GL.glGetString(GL.GL_RENDERER)` 확인 후 컨텍스트 해제:
  `EGL_OK NVIDIA RTX PRO 4500 Blackwell/PCIe/SSE2`.
  이전 libEGL 누락 증상이 현재 점검에서는 재현되지 않았다. 패키지 설치/환경 변경은 하지 않았다.
- GPU compute process 조회 당시 항목 없음. GPU 추론이나 시뮬레이션 검증 결과로 해석하지 않는다.
- 새 출력 경로가 존재하지 않음을 확인한 뒤 초기화했다.

## 고정한 연구 조건

Config: `scene2test/config/behavior_afs_obstacles_luna.json`.

- Scene schema: `clear-path-obstacles-v3`, 기존 5축 + 정적 장애물 2개 각각 6축 = 17축.
- Domain ID: `d45c8b222698d445450b6d82968113efdcf0c3808e4afa1e34c85ec0664323b0`.
- Seed 17, AFS/Random 각각 유효 목표 6회 / 최대 시도 6회. 전체 최대 시도 12회.
- Cold start 각 2회, 두 방법에서 동일 장면 표본을 독립 실행하고 각자 예산에서 차감.
- Robot/AFS 모두 `gpt-6-luna`. 로봇당 최대 10호출, push 사용 가능.
- HTTP read timeout 300초, 전체 시뮬레이션 시간 상한 없음, watchdog wall 상한 없음.
- 전체 상한: 로봇 120 API 호출 + AFS 2 요청. 금액 상한이 아니며 제외도 시도 슬롯을 소모한다.
- AFS `hypothesis-v2`, `goal-behavior-v1`, `llm/boundary/exploration/repeat` 슬롯.
- AFS 자신의 arm/seed에서 관측한 근거만 사용. 이전 slalom PASS/FAIL을 warm history에 넣지 않았다.
- 로봇 목표/정책/계획기/기술을 바꾸지 않는다. AFS가 우회/밀기 행동을 지시하지 않는다.
- 정적 경로 부재를 자동 목표 실패/해결 불가능 판정으로 사용하지 않는다.

목적은 계속 더 어려운 실패만 만드는 것이 아니라 새 관측을 바탕으로 성공 쪽 완화,
다른 축 대조, 관측된 성공/실패 경계, 독립 탐색과 반복을 실행하는 것이다.
관측 경계가 없다면 경계를 발견했다고 주장하지 않는다. 탐색이 경계를 반드시 발견하는 것도 아니다.

## 생성 및 검증

프로젝트 디렉터리에서 실행한 오프라인 명령:

```bash
.venv/bin/python tools/run_afs_benchmark.py init --config config/behavior_afs_obstacles_luna.json --output-dir /workspace/g1_failure/runtime/afs_benchmark/obstacles_luna_20260929
.venv/bin/python tools/run_afs_benchmark.py report --with-memory --campaign /workspace/g1_failure/runtime/afs_benchmark/obstacles_luna_20260929
.venv/bin/python tools/run_afs_pilot.py --campaign /workspace/g1_failure/runtime/afs_benchmark/obstacles_luna_20260929
```

모두 exit 0. 초기화는 코드/의존성/외부 로봇 자산 fingerprint를 계산한 뒤
`protocol.json`과 `campaign.sqlite3`를 생성했다. init 자체는 EGL 검사가 아니므로 별도 실제 컨텍스트
점검 결과와 구분한다. 모델/API의 접근 가능 여부는 키가 없는 상태에서 확인하지 않았다.

- Campaign: `/workspace/g1_failure/runtime/afs_benchmark/obstacles_luna_20260929`.
- 초기 report: `reports/20260929T154237_605882Z/report.html`.
- 상태 `READY`, reason/pending/recovery null.
- AFS와 Random 모두 valid 0 / attempts 0, excluded 0, AFS requests 0.
- 파일럿 plan-only 출력에서 Luna/Luna, 17축, 총 12회 시도, 상한 120+2 요청 확인.
- 준비 후 environment fingerprint를 다시 계산해 고정값과 일치함을 확인했다.
  attempts/proposals/checkpoints가 모두 비어 있고 pending이 없다는 assertion도 통과했다.
- `git diff --check` 통과. 문서의 attempts/proposals/rollout 경로를 소스와 대조했다.
- 초기 보고서의 토큰 관측값 null은 실행 전 상태이며 청구액 0이라는 측정값으로 바꾸지 않았다.
- 이 준비 작업은 실험 결과가 아니다. FDR/Gain/유형 coverage/통계적 우월성을 평가할 표본은 아직 없다.
- 실행 코드 변경이 없으므로 전체 테스트 재실행 대신 실제 init/report/plan 경로를 검증했다.

## 사용자가 키를 등록한 터미널에서 실행할 명령

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_afs_pilot.py --live --campaign /workspace/g1_failure/runtime/afs_benchmark/obstacles_luna_20260929
```

이미 초기화했으므로 새 config 실행이 아니라 이 캠페인을 지정한다.
첫 두 실행을 점검한 뒤 같은 예산의 나머지를 수행한다. 유효 목표 FAIL은 중단 사유가 아니다.
새 제외/운영 오류는 로그와 부분 report를 보존하고 중단하며, 모호한 호출을 자동 재전송하지 않는다.
중단 시 원인을 확인하기 전 무조건 재개하거나 예산/소스 검사를 우회하지 않는다.
코드/의존성/자산 변경 시 기존 캠페인 조건을 바꾸지 말고 별도 캠페인을 검토한다.

성공 여부, 목표 진척, 막힌 계획/회복 행동, 접촉/낙상, AFS 가설과 실제 결과, 관측 경계,
반복 패턴, 비용 누락을 보고 검토할 예정이다. 실패 유형 규칙은 제한된 운영상 연관성이며
원인 확정이나 6종 전체 측정이 아니다. 영상은 MP4만 기록하고 GIF는 만들지 않는다.
