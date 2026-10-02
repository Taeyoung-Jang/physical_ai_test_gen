# 실패 유형과 장면 도메인 지원 자동 점검 구현

2026-10-02 UTC. 전체 연구 계획 리마인드 후 사용자가 다음 단계 진행을 요청했다.
P0/P1/P2 기반을 다시 만들거나 폭 실험을 반복하지 않고, P3의 장면·관측·분류 범위
공백을 자동 점검하는 오프라인 도구를 구현했다. 목적은 4/6 유형 목표에 필요한
실제 연결을 확인하는 것이다. 새로운 실패를 발견하거나 네 번째 규칙을 구현한 작업은 아니다.

## 확인한 사실과 개발 판단

현재 `goal-behavior-v1`에는 collision, obstacle_interference, goal_occupied의
세 operational 규칙이 있다. 인과 확정 규칙이 아니며, 규칙 수가 발견 유형 수는 아니다.
unreachable, human_safety_risk, perception_error는 아직 미지원이다.
따라서 4종을 측정하려면 최소 한 규칙이 더 필요하고, 그 규칙에 맞는 장면·관측·실제
양성/음성 검증도 필요하다. 규칙 추가만으로 연구 목표를 달성하지 않는다.

현재 goal-agent v1/v2/v3 생성 범위에는 초기 목표 점유를 직접 만드는 축이 없다.
목표 중심 `(7,0)`, 반지름 `0.25m`에 대해 모든 초기 비바닥 물체의 보수적 XY 경계가
분리된다. v3 두 번째 장애물의 X 최댓값은 `5.75 + hypot(0.8,0.8)/2 = 6.315685m`이며
목표 원의 왼쪽 끝 `6.75m`보다 작다. 상자와 벽도 따로 검사한다.
이는 모든 허용 초기 값에 대한 생성식의 경계 계산이며 무작위 샘플만으로 내린 결론이 아니다.

이후 로봇이 동적 상자를 목표에 옮길 가능성은 이 초기 감사로 판단하지 않는다.
`post_action_occupancy_possible=null`을 유지한다. 초기 점유 장면을 제어할 수 없다는
사실을 기존 goal_occupied 측정기가 무의미하다거나 실행 중 점유가 불가능하다는 주장으로
확대하지 않는다. 지도 no_path도 물체 이동을 포함한 로봇 목표 불가능성 증명이 아니다.

개발 판단은 다음 실제 장면 확장 후보를 목표 주변 물체 배치로 두는 것이다.
빈 목표·부분 점유·이동으로 해소 가능한 점유를 함께 검증하고 로봇 행동은 정책에 맡긴다.
이 확장 및 네 번째 유형의 구체적인 측정 계약은 아직 구현하지 않았다.

## 구현 파일과 동작

- `scene2test/src/failure_client/evaluation/domain_readiness.py`: 지원된 3/5/17축
  범위와 실제 규칙을 읽어 유형별 지원 상태를 계산한다. 초기 기하 경계, 정적 지도
  예제와 SceneGraph 해시, 관련 소스 해시를 기록한다. 관측 Coverage는 null이다.
- `scene2test/src/failure_client/reporting/domain_readiness_report.py`: 별도 HTML,
  JSON, CSV 및 파일 해시 manifest를 생성한다. 기존 출력 폴더와 내용 변조된 digest는 거부한다.
- `scene2test/tools/audit_failure_domain.py`: API/GPU 없는 CLI. 기본 v3,
  `--schema`, 새 `--output-dir`, 파일 없는 `--stdout-only`를 지원한다.
- `scene2test/tests/client/test_domain_readiness.py`: 경계·표본 포함 검사, 미측정과
  불가능성 구분, 파일 보존·HTML 이스케이프, 네트워크/무거운 추론 모듈 미사용 등을 검사한다.

프로덕션 로봇·AFS 선택·유형 판정 모듈은 변경하지 않았다. 새 도구는 해당 모듈의
계약을 읽는 별도 기능이며 캠페인 실행 경로에 끼워 넣거나 후보를 제거하지 않는다.
SceneGraph/지도 예제는 CPU 생성이며 MuJoCo 물리 rollout이 아니다.

## 검증 명령과 결과

`scene2test`에서 실행했다.

```bash
.venv/bin/python -m pytest tests/client/test_domain_readiness.py tests/client/test_discovery_measures.py tests/client/test_usage_taxonomy.py tests/client/test_behavior_memory.py tests/client/test_afs_contrast.py tests/client/test_corridor_campaign.py -q
```

결과: **166 passed in 47.47s**, 경고 없음. 이 중 새 감사 검사 17개,
기존 측정·사용량·유형·메모리·대조·캠페인 회귀 149개다.
초기 새 테스트 실행에는 pytest의 zip iterator 사용 경고가 있어 list로 수정했다.
새 파일 네 개의 `ruff check`, `ruff format --check`와 `git diff --check`도 통과했다.
이는 전체 저장소 또는 새 live G1/LLM 성능 검증이라는 뜻은 아니다.

추가로 실제 오프라인 CLI를 실행했다.

```bash
.venv/bin/python tools/audit_failure_domain.py
```

출력 경로:

```text
/workspace/g1_failure/runtime/failure_domain_audit/20261002T123551_647513Z
```

`report.html`, `audit.json`, `families.csv`, `manifest.json`을 생성했다.
결과는 `INSUFFICIENT_RULE_SUPPORT`, implemented_rule_count=3,
minimum_additional_rules_needed=1, observed_failure_diversity_coverage=null이다.
v3 폭 상·하한의 기본 지도 예제는 각각 경로 있음/없음을 보이나 goal 결과는 부여하지 않았다.

저장한 JSON을 메모리의 Python dict와 직접 비교하는 검증 명령이 처음 실패했다.
원인은 축 범위의 Python tuple이 JSON array/list로 변환되는 자료형 차이였다.
JSON 정규화 비교는 일치했고 감사 digest와 산출물 세 파일 해시 모두 일치했다.
이 검사를 보고서 회귀 테스트에 추가했다. 원본 보고서를 수정하거나 다시 만들지 않았다.
HTML 내용·이스케이프·파일은 검증했으나 브라우저의 시각적 렌더링은 별도 확인하지 않았다.

## 문서와 보존 범위

[사용법과 결과 해석](../scene2test/docs/FAILURE_DOMAIN_READINESS.md), 루트 README,
로드맵, 작업 이력 색인과 AGENTS 기억을 갱신했다. write-page 스킬의 범위·근거·제안
구분 원칙에 따라 실제 구현과 향후 장면 확장을 분리했다.

API 호출 0회, 로봇 실행 0회. 유료 재시도, GPU 추론, GIF 생성, 새 goal 결과는 없다.
3.2m API timeout은 INCONCLUSIVE인 채로 보존하며 폭 suite와 옛 캠페인의
상태·예산·비용·결과는 수정하지 않는다. 로봇 정책·목표·시간/토큰 설정도 그대로다.
커밋·push는 수행하지 않았다.

## 사용자 실행 결과 검토

사용자가 같은 날 생성한 다음 결과를 읽기 전용으로 검토했다.

```text
/workspace/g1_failure/runtime/failure_domain_audit/20261002T130333_961803Z
```

JSON·CSV·HTML의 SHA256 세 개가 manifest와 일치했고, 감사 payload digest 및 관련
소스 아홉 개의 해시도 일치했다. CSV에는 지정한 여섯 유형이 있으며, JSON 내용은
앞선 `20261002T123551_647513Z` 감사와 동일하다. 정상 완료한 같은 조건의 점검이며
새로운 로봇 실험 결과는 아니다. 원본 파일은 변경하지 않았다.

`INSUFFICIENT_RULE_SUPPORT`는 실행 오류가 아니라 연구 측정 지원의 부족을 뜻한다.
목표는 6종 중 4종인데 구현된 규칙은 3개라 현재 분류기로 네 유형을 집계할 수 없다.
`minimum_additional_rules_needed=1`은 규칙 수에 대한 최소 필요 조건일 뿐이다.
새 규칙을 하나 등록하면 네 유형을 발견하거나 검증했다는 뜻이 아니다.
`observed_failure_diversity_coverage=null`은 이 감사에서 실제 발견을 측정하지 않았다는
뜻이며 0%, 로봇 실패, 기존 실험의 증거 소실로 해석하지 않는다.

v3 초기 기하 검사는 전과 동일하다. 목표 원과 두 번째 정적 블록의 가능한 초기 영역
사이에는 최소 약 0.4343m의 분리가 있다. 다른 초기 물체도 모두 분리된다.
실행 중 움직인 상자는 판단하지 않는다. 폭 하한/상한의 기본 정적 지도 예제가
경로 없음/있음인 것도 확인했으나 live 추종기 또는 목표 결과와 동일시하지 않는다.

후속 제안은 목표 주변 물체 배치의 새 버전 확장이다. 빈 목표, 부분 점유, 이동으로
해소 가능한 점유를 함께 만들고 기존 행동 근거·완화 탐색을 연결한다.
이것은 기존 goal_occupied 유형을 시험할 장면 범위를 보완하는 것이지 네 번째 유형
추가가 아니다. 4/6을 위해서는 도달 불가·작업자 위험·인식 오류 중 별도 유형의
장면/관측/근거 계약과 실제 검증이 추가로 필요하다. 유형 확장 중에도 원래 goal의
달성 여부로 PASS/FAIL을 판정하며 접촉·안전 사건만으로 결과를 바꾸지 않는다.

이번 검토는 코드 수정·새 테스트·유료 호출·로봇 실행·옛 campaign 재개를 하지 않았다.
write-page 원칙에 따라 확인된 결과와 후속 제안을 구분해 이 절만 추가했다.
