# AFS 근거 분리와 제한적 복구 및 평가 준비

## 작업 범위

사용자는 프로젝트 목표 재확인 후 근거 연결 오류 수정, 유형별 탐색 가능성 점검, 조건 고정 평가 준비를 진행하도록 승인했다. 이번에는 이 세 묶음의 코드·오프라인 검증과 기존 회귀 계획 확인을 진행했다. 새 유료 실행, 최종 독립 평가 실행기, 새 사람 도메인까지 완료한 것은 아니다.

최신 040453 세션은 유효 3FAIL, manipulation_failure 1종, 나머지 2개 미분류다. 제안 4개 중 마지막 두 후보가 선택한 PASS 기준의 ID를 evidence_refs에는 넣었으나 behavior_refs에는 최근 FAIL만 넣어 검사에서 중단됐다. 마지막 로봇 시도는 없다. 원본과 소비 예산을 보존했다.

## 근거 역할 분리

새 cause-review-v3와 afs_reference_roles_luna.json은 anchor_behavior_refs를 별도로 요구한다. 기존 analysis_evidence_id와 behavior_refs는 분석·가설 근거를 가리키며, 출발 기준의 PASS 근거와 다를 수 있다. 각 참조는 제시된 기록 및 evidence_refs와 일치해야 한다. 기존 v2 계약은 바꾸지 않고 v3에만 충돌하는 구버전 프롬프트 문구를 교체했다. 임의 ID·다른 역할·다른 장면의 기준 근거는 계속 거부한다.

Luna·유효12/최대16시도/AFS20요청/축당4/반복0/history4/300초와 기존 breadth 배정을 유지한다. 로봇·목표·유형·임계값·토큰·시뮬레이션 제한은 변경하지 않았다. 실제 관측과 LLM 가설의 구분도 유지한다.

## 저장 응답의 제한적 복구

recover-anchor-refs는 기본 dry-run이다. 원본의 저장된 cause-review-v2 응답이 해당 기준 근거 오류로만 중단됐는지 확인하고, 선택한 기준 장면의 근거가 이미 evidence_refs에 정확히 하나 있을 때 behavior_refs에 추가하는 정규화만 허용한다. 값·역할·장면·근거 내용·분석 문장은 바꾸지 않는다. 원본 request/context/response와 해시·모델·사용량, 기존 valid 시도와 ledger를 검증한다. 모호한 요청, 다른 자료/자원/실행환경/예산 변경, 소스 삭제는 허용하지 않는다.

명시적 --apply는 원본을 보존한 새 감사 fork만 만든다. 기존 numeric recovery의 잠금·스냅샷·provenance 검증을 재사용하고 새 스키마의 audit, 원본 상태·프로토콜·ledger 해시와 normalized_proposal 해시를 재개 시 확인한다. 보고·저장 응답 검증에서도 원본에서 같은 정규화가 나오는지 재계산한다. 이미 보낸 요청을 재전송하지 않는다.

실제 20261019T040453_455719Z dry-run이 통과했다. 원래 첫 후보 human_lateral_fraction=0을 선택하며 3로봇시도·4AFS요청 소비를 유지한다. 남은 유효 목표9개, 최대13시도·16AFS요청이다. 실제 복구 fork는 만들지 않았고 API·로봇 호출도 없다. 복구본은 원래 v2 정책의 operator-assisted 개발 연속 실행이지 v3 또는 독립 평가로의 변환이 아니다.

## 관측 범위 점검

discovery_readiness.py와 prepare_discovery_evaluation.py audit는 10종 중 8개 규칙 지원, 환경에서 바꿀 수 있는 축, 필요한 행동 관측과 주의점을 분리한다. 실제 입력 기록을 명시할 때 조건별 측정 보고를 만들고 서로 다른 로봇 조건을 합산하지 않는다. 규칙 지원 또는 축의 존재가 유형 발견·행동 유발 가능성 증거는 아니다.

현재 v5의 사람 X는3.65~4.35m이고 목표 중심X7m/반경.25m, 노출 중심 거리1m다. 두 영역은 X방향으로 최소1.4m 떨어져 있어 목표 영역 안과 사람 노출이 동시에 성립하지 않는다. 그러나 중간 사람 부근에서 종료하는 FAIL은 가능하므로 인간 위험 전체의 불가능성을 뜻하지 않는다. 이 공간 제약은 v3 LLM 입력에도 전달한다. 목표 부근 사람 배치의 별도 버전 도메인은 아직 구현하지 않았다. 현재 범위/판정 시간창을 완화하지 않았다.

실제 최신 세 실패의 점검은 같은 e8ec8119 조건에서 manipulation_failure 1종으로 유지됐다. 과거 집합 유형을 신규 결과에 합산하지 않았다.

## 독립 평가 준비와 회귀

discovery_evaluation_luna.json은 seed17/29/43 각각20valid/24attempt/24AFS의 제안이다. 총60valid/72attempt, 기준10call로봇이면 상한720robotcalls/72AFS다. 개발 이력은 로봇·목표·자원 provenance를 확인하는 데만 쓰고 평가 external_history는 빈 목록이다. 전체 도메인 uniform cold-start, seed별/전체 집계, 제외 비용, 고정 정책·예산, Random Gain 후속을 선언한다.

plan은 파일을 만들지 않고 freeze --output-dir은 새 디렉터리에 해시가 있는 manifest만 만든다. 독립 cold-start 실행기를 아직 연결하지 않았으므로 BLOCKED_INDEPENDENT_COLD_START_RUNNER_REQUIRED를 반환한다. 기존 개발 AutonomousAFS를 독립 평가라고 부르지 않는다. 실행기를 추가하면 소스 해시가 바뀌므로 실제 평가 전에 재동결해야 한다. 첫 평가·추가 seed 예산을 실행 승인으로 취급하지 않는다.

실제 PASS 대조와 최신3FAIL의 evaluation_plan이 통과했고 외부 평가 이력은 비어 있다. 실제 PASS 대조와 manipulation_failure 사례로 기존 replay_plan(repeats=2)도 통과했다. 회귀 계획은2장면/4시도/최대40robotcalls며 실행하지 않았다. 반복 확인은 별도 비용으로 계산한다.

## 검증과 후속

관련 합성 CPU 테스트152개 통과36.26초. 신규6개는 PASS 기준/FAIL 분석 분리, 원본 정규화 무변경, 복구 dry-run·fork·무재전송·스냅샷 변조 거부, 사람 공간 제약, 평가 warm history 부재·총예산·명시적 실행 차단, seed/예산 검증을 포함한다. 기존 cause review·범위 오류 복구·분기·예산·재개 회귀도 함께 통과했다. Ruff·format·diff 검사를 수행했다.

OpenAI Docs의 구조화 출력 지침을 확인해 새 역할 필드도 필수화하고 추가 속성을 금지했다. 문서 작성 지침에 따라 구현·준비·미구현 실행과 실제 성과를 구분했다. 기존 사용자 변경과 원본 아카이브·DB·라벨·비용을 보존했으며 커밋/push는 하지 않았다.

다음은 명시적 복구 적용 여부 또는 v3의 제한된 live 개발 검증을 결정하고, 독립 cold-start 실행기를 구현·검증하는 것이다. 유형 관측 제약을 해결할 별도 도메인 확장은 그 전에 설계·검증해야 한다. 최종 FDR30%와4종 공동 달성, Random Gain20%, 새 조건의 회귀 재현 성과는 여전히 미검증이다.
