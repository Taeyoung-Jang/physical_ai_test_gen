# 밀기 거리 끝점의 수치 오류 수정과 회귀 검증

## 요청과 완료 범위

2026-10-03 사용자가 이전 검토에서 발견한 문제에 필요한 코드 수정을 승인했다. 밀기 거리
범위의 부동소수 끝점 오류를 수정하고 CPU·모의 회귀 검사 **233개 통과, GPU 검사 2개 제외**를
확인했다. 새 API 호출·GPU 추론·로봇 rollout은 실행하지 않았다. 물리 밀기나 목표 성공이
개선됐다는 실험 결과가 아니라, 잘못된 거리 거절을 제거한 코드 및 단위 검증 결과다.

이전 사용자 작업과 미커밋 검토 문서를 보존했다. 기존 성공·실패 archive, 동결 suite/예산,
평가 규칙, AFS 후보 선택, 로봇 행동 결정, 정렬 허용 범위, 출력 토큰·시뮬레이션 기본 상한,
no-GIF 정책과 폭 실험 중단 결정은 변경하지 않았다. 커밋·push도 하지 않았다.

## 문제와 수정

기존 `push_skill.preflight`와 `push_alignment.readiness`는 각각
`0.075 <= distance <= 0.20`으로 비교했다. 목표 X=7.2, 상자 X=7에서도 계산 결과는
`0.20000000000000018`이어서 20cm 끝점이 거절됐다. 검토된 실제 요청은
`0.20000000000010654`였다. 회전 좌표에서는 7.5cm 하한에도 같은 문제가 재현됐다.

수정 파일:

- `scene2test/src/robot_vlm/push_skill.py`: 명목 최소/최대 거리와 절대 오차 상수를 정의하고
  `supported_push_distance`를 사전 검사에서 사용한다.
- `scene2test/src/robot_vlm/push_alignment.py`: 같은 함수·상수를 사용하고 readiness의
  `limits.push_distance_abs_tolerance_m`에 허용 오차를 명시한다.

명목 범위는 여전히 0.075–0.20m이고 **절대 오차 1e-9m, 즉 1nm**만 양 끝에 적용한다.
세계 좌표나 요청 크기에 비례하는 상대 오차는 없다. 실제 측정 거리와 요청 목표를 반올림하거나
clamp하지 않으며, 비유한 값과 허용 오차 밖의 요청은 계속 거절한다. 정렬 14cm 진입 범위,
직접 밀기 6cm 측면 범위, 방향·거리·시간·접촉 가드도 유지한다.

기존 제어기 계열 VERSION 이름은 유지했다. 두 수정 모듈은 이미 goal protocol과 campaign
fingerprint의 소스 해시 대상이므로 실제 로봇 condition은 달라진다. 새 모듈을 만들어 출처
해시 목록에서 빠지는 문제는 만들지 않았다.

## 검증한 테스트

먼저 새 거리 회귀 검사를 기존 코드에 실행하여 **8 실패 / 20 통과**를 확인했다. 20cm
끝점, 회전된 7.5cm 끝점, 실제 저장된 실패 입력에서 거리 검사 거절을 재현한 뒤 수정했다.

새 `tests/test_robot_push_distance.py`는 다음을 검사한다.

- 7.5cm/20cm 끝점, 세계 X=0/4/7, 방향 0/0.7/-π/2에서 두 검사 일치.
- 1nm 안의 오차는 허용하지만 2nm 초과 및 1μm 초과 요청은 거절.
- 0/음수/NaN/무한대 등 지원하지 않는 값의 거절.
- GPT 목표와 측정 거리가 변경되지 않고 readiness에 명목 범위·절대 오차가 기록됨.
- 실제 첫 요청은 정렬로 넘어갈 수 있지만 직접 밀기로 건너뛰지는 않음.
- 실제 두 번째의 정렬 진입 범위 초과는 수정 후에도 유지됨.

기존 `test_robot_push_alignment.py`의 fake kinematics 분기 검사를 15cm와 20cm 모두에서
수행하도록 확장했다. 수렴/정체/안전 중단/예산/물체 이동의 다섯 경우다. Fake callback은
CPU 단위 검사일 뿐 실제 G1 제어·시뮬레이션 성공으로 취급하지 않는다.

| 검증 | 결과 |
|---|---|
| 밀기 거리·skill·alignment·dispatch·integration | 69 통과, 실제 GPU opt-in 2개 제외 |
| AFS contrast·paired contrast·regression·memory·goal outcome·runner·budget | 164 통과 |
| 수정 Python 4개 파일 Ruff check / format check | 통과 |
| git diff --check | 통과 |

실행 명령은 scene2test 디렉터리 기준이다. 첫 명령은 GPU opt-in 환경 변수를 제거한다.

```bash
env -u RUN_ROBOT_PUSH_GPU .venv/bin/python -m pytest -q tests/test_robot_push_distance.py tests/test_robot_push_skill.py tests/test_robot_push_alignment.py tests/test_robot_push_dispatch.py tests/test_robot_push_integration.py
.venv/bin/python -m pytest -q tests/client/test_afs_contrast.py tests/client/test_afs_paired_contrast.py tests/client/test_behavior_regression.py tests/client/test_behavior_memory.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py tests/test_robot_simulation_budget.py
.venv/bin/ruff check src/robot_vlm/push_skill.py src/robot_vlm/push_alignment.py tests/test_robot_push_distance.py tests/test_robot_push_alignment.py
.venv/bin/ruff format --check src/robot_vlm/push_skill.py src/robot_vlm/push_alignment.py tests/test_robot_push_distance.py tests/test_robot_push_alignment.py
```

## 저장 입력과 원본 보존 확인

`goal_region_lateral_20261002/suite/attempts/attempt_00002/rollout`의 skill 측정값에서
자세를 재구성해 새 순수 검사 함수에 넣었다. 원본 파일을 덮어쓰지 않았다.

| 원래 호출 | 거리 검사 | 수정 후 preflight | 정렬 가능 여부 |
|---|---|---|---|
| 8번째 20cm 요청 | 기존 거절 → 통과 | near_aligned_approach_required | true, 직접 밀기 ready는 false |
| 10번째 15cm 요청 | 기존 통과 → 통과 | near_aligned_approach_required | false, 측면 약 14.54cm > 14cm |

첫 요청에서 정렬 기회가 복원된다는 뜻이지 정렬 수렴 또는 밀기 성공을 보장하지 않는다.
두 번째는 현재 alignment 진입 검사가 그대로 거절하며 이를 맞추려고 범위를 확대하지 않았다.

read_goal_run으로 원본 세 archive를 다시 검증했다. 순서대로 VALID/PASS 66개 artifact,
VALID/PASS 48개, VALID/FAIL 77개가 해시 일치했고 기존 evidence ID도 유지됐다. 원래
0.25 FAIL은 당시 로봇 구현·예산의 결과로 남는다. 새 소스의 push_skill/push_alignment 해시가
원본 protocol과 다른 것도 확인했다. 동결 소스 검사 우회나 기존 FAIL 재분류는 하지 않았다.

## 문서 및 후속 실험

`docs/ROBOT_PUSH_ALIGNMENT.md`에 수치 계약과 한계를, `docs/AFS_PAIRED_GOAL_CONTRASTS.md`에
새 코드 조건에서 기준 0.5와 도전 0.25를 각각 재확인할 실행 명령을 기록했다. write-page
스킬의 구분 원칙에 따라 코드 검증과 아직 수행하지 않은 실제 로봇 성공을 나눠 기술했다.

사용자가 실행할 경우 원본 scene_config만 읽고 새 timestamp 출력 폴더를 사용한다. 기준
0.5의 새 결과부터 검토하고, 이어 도전 0.25를 별도로 실행한다. 각각 최대 10회 로봇 API,
둘 다 실행하면 최대 20회이며 새 AFS 제안은 없다. 이번 수정 작업에서는 실행하지 않았다.

기존 suite의 run/next로 새 소스를 이어 붙이지 않는다. 새 코드의 두 장면 결과를 검증한 뒤
같은 조건의 실패 구간과 0.375 중간값 탐색을 검토한다. 기존 FAIL과 새 코드 PASS만 묶어
환경의 같은 조건 경계로 보고하거나, 아직 실행 전인 장면에 성공 라벨을 부여하지 않는다.
