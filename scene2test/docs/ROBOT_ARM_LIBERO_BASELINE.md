# 공개 로봇팔 정책 기준 실험

첫 작업은 LIBERO Spatial의 `pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate`다.
NVIDIA 공개 `nvidia/GR00T-N1.7-LIBERO`의 `libero_spatial` 체크포인트를 사용한다.
정책을 학습하거나 GPT로 동작을 보완하지 않고, 현재 로컬 Isaac-GR00T 평가기를 호출한다.
로컬 외부 코드의 해시를 기록하므로, upstream 원본과 완전히 동일하다는 주장은 하지 않는다.

## 현재 설정

- Panda 로봇팔; 검은 그릇을 집어 접시 위에 놓기.
- 원래 작업의 물체·카메라·물리·목표 조건 유지. 추가 장애물 없음.
- 개발 seed 41001, 41002 각각 한 에피소드. 순차 실행, 환경 1개.
- 에피소드당 최대 300 환경 step, action chunk 8. 최대 총 600 step.
- 성공 판정은 기존 LIBERO `check_success`; 실행 오류와 결과 누락은 로봇 FAIL로 만들지 않음.
- 각 시도에 intent, log, result.json, videos 폴더를 저장.
- 기본 실행은 없음. `run --live`만 모델을 로드하고 시뮬레이션을 수행.
- 전체 invocation과 각 worker는 독점 intent로 재실행을 거절함. 오류/중단 시 자동 재시도·대체 없음.

이는 기본 수행 가능성을 확인하는 **개발 기준 실험**이다. 아직 AFS/Random 비교가 아니다.
현재 외부 wrapper는 `seed`로 reset하며 공식 고정 init-state 목록을 사용하지 않는다.
따라서 논문/모델 카드의 공식 점수 재현으로 보고하지 않는다. seed도 모델 추론의
완전한 결정성을 보장하지 않는다. 현재 실행 계획은 선택된 주요 소스 해시를 기록하며
전체 종속 자산·환경 패키지까지 동결한 정식 연구 프로토콜은 아니다.

## 무료 명령

`scene2test`에서 실행한다. 시스템 Python으로 plan/check 가능하다.

```bash
python tools/run_robot_arm_baseline.py plan
python tools/run_robot_arm_baseline.py check
```

`experiments/robot_arm_libero/baseline_v1`에 준비본이 있다. init를 반복하지 않는다.
준비 상태는 `preflight.json`에 저장되며 현재 상태는 check로 다시 확인한다.

공개 체크포인트 revision `2ea293aa20ba7cf5bbf3ba17a5fbcb1a01cbfe21`의 추론 파일만
`experiments/robot_arm_libero/models/GR00T-N1.7-LIBERO/libero_spatial`에 다운로드했다.
학습 optimizer 파일은 받지 않았다. 약 6.9GB이며 Git에서 제외한다.
`.venv-arm`에 LIBERO/MuJoCo 의존성을 설치하고 기존 GR00T 가상환경의 패키지를
`.pth`로 읽기 전용 참조한다. 기존 패키지는 수정하지 않았다. 따라서 이 환경은
기존 GR00T 환경에 의존하며 완전히 독립적인 배포 패키지는 아니다.
LIBERO 설정은 `libero_config/config.yaml`에 격리했고 기존 `~/.libero`는 건드리지 않았다.
모델·필수 모듈 존재 검사는 통과했다. 이는 GPU 호환성이나 실제 작업 성공의 증명이 아니다.
설치 패키지 목록은 준비 폴더의 `environment_packages.json`에 기록한다.
원래 공식 setup script는 환경/홈 설정 삭제를 포함하므로 실행하지 않았다.

리소스가 설치되어 check를 통과한 뒤의 실행 명령:

```bash
python tools/run_robot_arm_baseline.py run --live
```

## AFS 연결 전 다음 단계

먼저 두 baseline 결과와 영상을 확인한다. 실패했다고 PASS가 나올 때까지 seed를 바꾸지 않는다.
그 다음 원래 작업 배치 공간에서 그릇/접시 위치를 명시적으로 제어하고 실제 초기 pose를
저장하는 adapter를 만든다. 작업 BDDL의 region 좌표는 테이블 기준이며 world 좌표로
오인하지 않는다. 현재는 그 adapter 및 AFS/Random sampler가 연결되지 않았다.
단순히 reset seed를 AFS가 고르게 하고 물체 위치 탐색이라고 부르지 않는다.
양쪽에 동일 범위·초기 조건·예산·성공 규칙을 적용하는 별도 새 비교 설계가 필요하다.
기존 휴머노이드 캠페인과 결과·예산·분류 체계를 합치지 않는다.

## 2026-10-22 첫 실행 중단

baseline_v1 첫 worker가 모델 로딩 중 Cosmos-Reason2-2B 접근 401로 중단됐다.
이것은 로봇 FAIL이 아니며 아직 모델 정책 생성 단계여서 rollout은 시작되지 않았다.
기존 execution_intent와 exclusion/log는 보존한다. 반복 run은 status를 출력하고 중단한다.
`python tools/run_robot_arm_baseline.py status`로 저장 원인을 읽을 수 있다.
check의 local_resources_present는 파일/모듈 존재만 뜻하며 backbone 접근은 UNVERIFIED다.

사용자가 Hugging Face 모델 페이지에서 접근 조건을 확인·승인하고 본인 터미널에서
`/workspace/g1_failure/src/Isaac-GR00T/.venv/bin/hf auth login`을 수행해야 한다.
토큰을 채팅에 보내지 않는다. 기존 intent 삭제나 같은 baseline 강제 재개를 하지 않는다.
권한 해결 후 새 코드로 별도 버전의 개발 실행을 준비하며 이전 제외/비용을 별도 보존한다.
