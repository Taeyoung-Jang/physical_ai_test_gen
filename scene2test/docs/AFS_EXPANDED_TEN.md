# 10종 측정 결과와 AFS 환경 선택 연결

새 설정 `config/afs_expanded_ten_luna.json`은 입력 이력과 새 실험 결과를 같은10종
프로필로 측정하고 그 근거를 다음 환경 선택에 전달한다. 기존6종 모드와 과거 결과는
유지한다. 로봇·목표·완료 조건은 변경하지 않는다.

## 전달하는 정보와 선택

- 실제 대표 유형, 보조 진단, 유형별 측정 상태와 실제 에피소드 ID.
- 목표 체류, 넘어짐, 실제 이동 실행, 조작 결과의 기록.
- 관측한 유형과 아직 관측하지 못한 지원 유형, 해당 유형을 겨냥한 신규 시도 수.

기존 실패 지향 순위에서 같은 의도라면 미발견 지원 유형을 관측한 유형보다 우선하고,
그다음 해당 유형의 시도 수 등을 고려한다. 예측 유형은 측정 라벨이 아니다. 한 실험당
대표1개만 세며 보조 진단을 추가 발견으로 집계하지 않는다. 다른 축을 골랐다는 이유만으로
다른 유형으로 세지 않는다. 강제 유형 할당이나4종 달성 보장은 추가하지 않았다.

응답 스키마와 호스트 모두 신규4종을 받는다. 도달 불가·인식 오류는 현재 미지원이므로
제안 목표로 허용하지 않는다. unclassified는 가능하다. 지원 규칙8개가 실제8종 발견이나
해당 환경에서의 실패 가능성을 보증하지는 않는다.

## 고정 계약

`SearchBudget.taxonomy_profile` 기본값은 `scene-default`다. 새10종은
`expanded-ten-v1`을 명시하며 현재 failure-branch-v3에서만 허용한다. 새 설정은 이를
활성화하고 기존 `afs_failure_branch_luna.json`은6종 계약을 유지한다.
입력 이력 분류, 실행 후 분류, 다음 요청, 신규 지표 모두 같은 측정 프로필을 사용한다.
저장 응답·후보 재검증, PASS 기준 분기, 중복·최소 변화·쿼터·cooldown·제한된 재제안은 유지한다.

예산은 유효6개 목표/최대8시도/AFS8요청이며 현재 로봇에서 최대80호출이다. 모델은
gpt-6-luna, 로봇10호출/push/dwell/HTTP300초를 상속한다. 입력 이력은 신규 표본 분모에
넣지 않고 비용도 분리한다. 토큰·암묵적 시뮬레이션 상한은 추가하지 않는다.
API 오류는 자동 재전송하지 않는다. 같은 실패당 대표1개를 세므로4종에는 최소4개의
서로 다른 실패 장면이 필요하며, 유효6개로4종을 보장하지 않는다.

## 실행 명령

기존 완료 세션을 새 코드로 재개하지 않고 최근6개 기록으로 새 세션을 시작한다.
아래 첫 검사는 무료이며 API·로봇·출력 디렉터리를 만들지 않는다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/run_afs_autonomous.py plan --config config/afs_expanded_ten_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00001/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00002/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00003/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00004/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00005/rollout
```

다음 명령은 키가 설정된 터미널에서 새 유료 탐색을 시작한다. 이번 구현 검증에서는 실행하지 않았다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py run --live --config config/afs_expanded_ten_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00001/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00002/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00003/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00004/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261018T081720_637822Z/attempts/attempt_00005/rollout
```

결과는 `/workspace/g1_failure/runtime/afs_autonomous/<새시각>/`에 저장한다. 예측은
`candidate.evidence.target_family`, 측정은 `episode.attribution.primary_family`,
신규 지표는 `new_only_discovery_metrics`에서 구분한다.

## 검증과 한계

관련 CPU/synthetic 테스트230개, 실제 최근6개 아카이브의 plan이 통과했다. 실제 재분석
기록의 요청에는 관측한 goal_completion_failure1종과 미발견 지원7종이 전달됐다.
수동 오프라인 후보 비교에서는 미발견 유형이 우선 선택됐다. 이는 LLM 제안·실제 로봇
결과가 아니다. 새 모드의 실제 발견율·다양성 향상은 아직 측정하지 않았다.
외부 검토 이력을 쓰는 개발 탐색이며 독립 AFS/Random 평가나 Gain 추정은 아니다.
판정 정의는 [10종 분류와 재분석 안내](EXPANDED_FAILURE_TYPES.md)를 따른다.
