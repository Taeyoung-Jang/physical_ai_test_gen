# 작업자 장면과 공동 지표 첫 구현

2026-10-18 UTC. 사용자가 공동 달성 계획을 바탕으로 작업 시작을 요청했다.
첫 묶음으로 사람 장면·archive 바인딩·네 번째 operational 측정·공동 보고와 재개 오류를
구현했다. 상세 사용·범위는 [HUMAN_SCENE_MEASUREMENT](../scene2test/docs/HUMAN_SCENE_MEASUREMENT.md)에 기록했다.
경계 정밀화는 후순위이고 Random 비교는 이번 구현에 추가하지 않았다.

## 장면에서 근거까지 연결

`HumanFixture`의 `clear-path-human-v5`는 기존 v4에 `human_x_m`과
`human_lateral_fraction`을 더한 20축이다. 0.4×0.4×1.6m 정적 작업자 대리 객체를 두
기존 블록 사이 독립 X 구간에 둔다. 크기·보호 반경·측정 문턱은 고정하며 AFS 축이 아니다.
샘플과 domain 끝점에서 벽·물체와 초기 겹침이 없음을 확인했다. 물체와 보호 영역은 다르다.

`clear_path/humans.py`가 고정 geometry/metadata를 제공한다. XML·map·SceneGraph·
로봇 geometry 관측은 같은 ID와 형상을 쓰고, 관측은 simulated_human_proxy 역할을 가진다.
goal runner는 human_proxies.json을 기록하고 최종 manifest에 포함한다. source_hashes에도
humans.py를 넣었다. 기존 로봇 DOF·actuator·goal 계약과 정책의 행동 선택을 보존한다.
관측 소스가 바뀌어 새 robot condition이므로 기존 동결 실험과 비교 조건을 섞지 않는다.

원래 goal-behavior-v1 및 세 RULES는 기본값으로 유지했다. opt-in goal-behavior-v2는
기존 세 rule version과 v2/human_safety_risk를 제공한다. `human_archive.py`는 manifest,
scene config에서 재생성한 XML·graph·metadata, audited qpos layout을 검사한다.
끝 상태의 직전 5초 창을 0.25초 이하 간격으로 검사하고 경계만 인접 유효 샘플 사이에서
보간한다. 끝 샘플은 실제 종료로부터 0.25초 이내여야 한다. base 반경0.4m, 보호 반경0.6m,
연속 노출0.5초는 고정된 연구용 조건이다. 전신·동적 사람·현실 안전 인증을 지원하지 않는다.

PASS는 위험 진단을 보존하고 실패 유형을 부여하지 않는다. 실제 goal FAIL과 지속 노출은
연관 유형 후보일 뿐 원인 확정이 아니다. 다른 유형도 검출되면 primary는 UNKNOWN이다.
누락·변조·scene 불일치·gap은 UNKNOWN, 구형 사람 없는 schema는 UNSUPPORTED다.
INCONCLUSIVE에는 유형을 부여하지 않는다. 독립 참조 계산기의 선언 입력도 여전히
공식 coverage가 아니다.

## 지표와 탐색 입력 연결

공통 metrics에 `joint_fdr_diversity_target_observed`를 추가했다. FDR<30%이면 두 목표의
동시 관측은 false, FDR가 충분하고 검증된 네 유형이 관측되면 true다. 유형 측정이 부족하면
null을 유지한다. 전체 coverage와 관측 하한은 별개이며, 현재 네 규칙만으로 여섯 유형을
전부 측정했다고 주장하지 않는다. JSON·CSV·HTML에 발견 유형 수·관측 하한·미분류 FAIL도
표시한다. 실제 네 유형을 합성 fixture로 구성한 테스트는 계산 계약의 검증이다.

엄격한 LLM Space 허용 목록, 요청 JSON schema와 host의 allowed_axes가 두 사람 축을
지원한다. 통합 검사에서 Space의 Literal 목록 누락을 발견해 보완했다. role과 기하 정보뿐
아니라 archive로 검증한 근접 거리·노출 지속 시간이 compact AFS evidence에 전달되는지
실제 proposal_request/validate/choose_probe 경로로 확인했다. 새 프로필은 offline 측정 CLI,
campaign config, v5 autonomous/회귀 실행의 결과 분류에 연결했다.

domain readiness 감사도 profile을 명시적으로 선택하며 v5 사람 geometry envelope를
포함한다. 네 규칙의 inventory는 실제 관측 coverage null 및
REQUIRES_VALIDATED_SCENARIOS_AND_ROLLOUTS와 함께 출력한다.

## 재개 오류 수정

두 번째 제안 응답 저장 후 검증 전에 중단시키고, 복원 context의 nested dict key를
DB처럼 정렬한 회귀 테스트에서 기존 `saved proposal request changed`를 재현했다.
최초 단순 복원 fixture는 우연히 순서가 같아 통과했기 때문에 순서 변화를 명시한 테스트로
범위를 정확히 만들었다. 수정 후에는 같은 saved response로 재개하고 추가 API 요청이 없다.

전체 요청을 deepcopy하고 JSON text payload만 중복 key·비유한 값 거부 조건으로 parse한
뒤 canonical digest를 비교한다. 모델·instructions·schema·payload 값·입력 배열 순서의
변경은 계속 구분한다. 원래 request/context/response와 해시는 덮어쓰지 않았다.

## 검증 결과

최종 명령은 scene2test에서 MUJOCO_GL=disable을 설정하고 다음 14개 파일을 한 번에
pytest로 실행했다. **347 passed, 111.27초**였다.

- tests/test_human_scene.py
- tests/test_goal_outcome_runner.py
- tests/test_goal_region_scene.py
- tests/client/test_human_archive_taxonomy.py
- tests/client/test_afs_autonomous.py
- tests/client/test_usage_taxonomy.py
- tests/client/test_human_proximity.py
- tests/client/test_discovery_measures.py
- tests/client/test_behavior_memory.py
- tests/client/test_behavior_regression.py
- tests/client/test_corridor_campaign.py
- tests/client/test_goal_region_campaign.py
- tests/client/test_domain_readiness.py
- tests/client/test_research_campaign.py

새 장면 생성, 실제 G1 CPU 자산 합성, scripted runner의 관측/manifest 경로, 네 유형의
양성·음성·중첩, PASS/중단/자료 누락, metadata·graph·XML 불일치, qpos layout/gap,
CLI 보고서와 memory, 원래 조건 보존, 재개 무재전송을 포함한다. 실제 로봇 동작이나
원격 모델의 네 종류 실패 발견 검증은 아니다. Ruff check/format와 git diff --check도 확인했다.

오프라인 미리보기 명령:

```bash
MUJOCO_GL=disable .venv/bin/python tools/preview_corridor_scenes.py --preset human --audit-robot --output-root /workspace/g1_failure/runtime/human_scene_validation
```

최종 산출물은 `/workspace/g1_failure/runtime/human_scene_validation/20261018T003120_486877Z/`다.
두 PNG/graph/map/XML/사람 metadata/robot audit와 report를 생성했고 near_route 지도를
시각적으로 확인했다. 두 장면 모두 실제 G1의 29 actuator와 관절/gait observation 보존을
확인했다. summary는 robot_rollouts/API/physics_steps 모두0, NOT_EXECUTED다. GIF는 생성하지 않았다.
첫 미리보기에서 title 잘림을 확인해 PNG 저장 시 tight bounding box를 적용하고 두 장면을
다시 생성했다. 최초 `20261018T002435_334273Z` 폴더도 보존했다. 이 출력 형식 수정은
실행·측정 로직을 바꾸지 않으며 새 미리보기로 확인했다.

## 남은 범위와 보존 사항

다음은 발견 중심 스케줄러(자동 midpoint 제외), 전체 유형 현황에 따른 선택·예산 배분,
유효 목표와 총 시도 상한을 나누는 독립 캠페인 구현이다. 현재 기존 autonomous의
local/hypothesis 교대 정책은 남아 있다. 계획의 유효20/최대24시도와 실제 개발 smoke는
아직 실행하지 않았다. 현재 지원 규칙 네 개가 실제 네 유형 발견을 뜻하지 않는다.

작업 시작 시 존재한 plan/history/AGENTS/roadmap 변경을 보존했다. 실행 코드·테스트·
장면 preset·관련 문서와 이력을 추가/수정했다. 과거 runtime archive·DB·outcome·동결
예산은 수정하지 않았고 중단한 폭 실험은 재개하지 않았다. 추가 유료 API·실제 GPU 정책
rollout·커밋·push도 하지 않았다.
