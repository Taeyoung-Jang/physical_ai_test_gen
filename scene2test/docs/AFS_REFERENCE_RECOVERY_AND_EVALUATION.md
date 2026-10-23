# AFS 근거 분리와 관측 범위 및 평가 준비

## 현재 완료 범위

최신 세션 `20261019T040453_455719Z`의 중단 원인은 PASS 기준 장면의 행동 근거와 FAIL 분석 근거를 혼동한 것이다. 새 `cause-review-v3`에서는 `anchor_behavior_refs`가 출발 기준의 실제 근거를, `behavior_refs`와 `analysis_evidence_id`가 실패 분석의 근거를 가리킨다. 둘 다 `evidence_refs` 안에 있어야 하며 원래 역할·중복·범위·예산 검사는 유지한다.

새 개발 설정은 `config/afs_reference_roles_luna.json`이다. 유효 12개·최대 16시도·AFS 20요청, Luna, 300초, 작은 변경·큰 변경·조합 배정을 유지한다. 이전 모드를 새 계약으로 몰래 바꾸지 않는다. 로봇·목표·판정 규칙은 변경하지 않았다.

유형 관측 가능성 점검, 평가 설계 준비, 기존 회귀 실행기의 무료 계획도 확인했다. 독립 cold-start 평가 실행기는 연결했고 CPU 모의 검증과 실제 자료의 무료 계획을 확인했다. 실제 유료 평가나 세 지표 달성은 아직 검증하지 않았다.

## 기존 중단 응답의 제한적 복구

다음은 무료 dry-run이다. 복구 디렉터리·새 세션·API·로봇을 만들지 않는다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py recover-anchor-refs --session /workspace/g1_failure/runtime/afs_autonomous/20261019T040453_455719Z --output-dir /workspace/g1_failure/runtime/afs_autonomous/20261019T040453_455719Z_anchor_ref_recovery
```

검사 범위는 완료된 저장 응답, 원본 context/request/response 해시와 모델·사용량, 중단 상태와 ledger, 기존 유효 시도, 같은 로봇·자원·실행환경·예산이다. 원본 후보가 선택한 기준 장면의 근거가 이미 `evidence_refs`에 하나만 존재할 때, 빠진 `behavior_refs`에 그 ID를 추가하는 것만 허용한다. 값·기준 장면·분석 내용·원래 응답을 수정하지 않는다. 출처가 없는 근거를 새로 추측하거나 request를 재전송하지 않는다.

실제 저장 응답의 dry-run은 첫 후보인 human_lateral_fraction=0을 선택했다. 이전 로봇 시도 3개와 AFS 요청 4개는 소비된 채 유지된다. 남은 유효 목표는 9개이며 최대 시도 13회·AFS 16요청이 남는다. 실제 회복 시도는 아직 수행하지 않았다.

아래 `--apply`는 **별도 감사 복구본만 생성**한다. 유료 실행은 없지만 새 디렉터리를 만들므로 dry-run 검토 후 명시적으로 실행한다. 디렉터리가 이미 있다면 덮어쓰지 않는다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py recover-anchor-refs --session /workspace/g1_failure/runtime/afs_autonomous/20261019T040453_455719Z --output-dir /workspace/g1_failure/runtime/afs_autonomous/20261019T040453_455719Z_anchor_ref_recovery --apply
```

복구본은 원래 cause-review-v2의 컨텍스트·모델·예산을 유지하는 operator-assisted 개발 연속 실행이다. cause-review-v3나 독립 평가로 변환한 것이 아니다. 복구본에서 `run --live --session ... --max-new-attempts 1`은 저장 후보의 **유료 로봇 실행**이므로 별도로 결정한다. 이후 제안에도 원래 v2 계약이 적용된다. 원본 세션에 같은 재개 명령만 반복하지 않는다.

## 새 근거 분리 모드

별도 신규 개발 세션을 준비할 경우 다음 무료 plan으로 검사한다. 과거 자료는 참고 이력이며 새 성과에 합산하지 않는다.

```bash
uv run --no-sync python tools/run_afs_autonomous.py plan --config config/afs_reference_roles_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00002/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261019T040453_455719Z/attempts/attempt_00000/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261019T040453_455719Z/attempts/attempt_00001/rollout --run /workspace/g1_failure/runtime/afs_autonomous/20261019T040453_455719Z/attempts/attempt_00002/rollout
```

`plan`을 `run --live`로 바꾸면 새로운 유료 세션이다. 복구본의 남은 예산을 이어 쓰는 방식과 중복 실행하지 않는다. 이 구현 과정에서는 어느 쪽도 유료 실행하지 않았다.

## 유형 관측 범위 점검

```bash
uv run --no-sync python tools/prepare_discovery_evaluation.py audit --schema clear-path-human-v5
```

`--run <검토할 rollout>`을 반복하면 검증된 실제 기록을 10종 규칙으로 읽어 로봇 조건별로 별도 집계한다. 원본 라벨은 변경하지 않는다. 서로 다른 조건을 합산하지 않으며 rule 지원과 실제 발견, 행동 유발 가능성을 분리한다.

현재 사람 X 범위는 3.65~4.35m이고 목표 중심은 X=7m다. 목표 반경 .25m와 사람 보호+로봇 중심 노출 거리 1m를 고려해도 두 영역 사이에는 X 방향으로 최소 1.4m의 간격이 있다. **목표 영역 안의 위치와 사람 노출 영역은 동시에 성립하지 않는다.** 그러나 사람 근처에서 종료하는 목표 FAIL은 가능하므로 작업자 위험 전체가 불가능하다는 뜻은 아니다.

이 제약은 v3 LLM 입력에도 전달된다. 사람 유형을 더 탐색하려면 중간 경로에서 끝나는 행동을 관측하거나, 목표 근처 사람 배치를 지원하는 별도 버전 도메인이 필요할 수 있다. 기존 도메인 값을 범위 밖으로 보정하거나 종료 시간 창·보호 반경을 완화하지 않는다. 새 도메인은 아직 구현하지 않았다.

## 독립 평가 설계 준비

`config/discovery_evaluation_luna.json`은 제안된 평가 설계다. seed 17·29·43 각각 유효 20개·최대 24시도, 총 유효 60개·최대 72시도다. 10호출 로봇이면 최대 720회 로봇 호출과 AFS 72요청이다. 이는 유료 실행 승인이 아니다.

```bash
uv run --no-sync python tools/prepare_discovery_evaluation.py plan --config config/discovery_evaluation_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00002/rollout
```

입력 자료는 로봇 조건·자원·목표의 출처를 고정하는 데만 쓰고 평가 warm history는 빈 목록으로 둔다. 초기 장면은 사전 seed의 전체 도메인 uniform으로 독립 실행하고 예산에 포함하도록 명시한다. seed별 결과와 전체 집계를 구분하며 좋은 seed만 선택하거나 목표를 먼저 넘었다고 중단하지 않는다. Random Gain은 이후 별도 비교다.

`freeze --output-dir <새 디렉터리>`는 현재 계획·환경 해시와 provenance를 새 manifest.json에 보존한다. 기존 파일을 덮어쓰지 않으며 로봇/API를 실행하지 않는다. 현재 `execution_readiness=INDEPENDENT_RUNNER_IMPLEMENTED_NOT_LIVE_VALIDATED`다. 이전 준비 전용 v1 manifest는 실행하지 않고 새 v2로 다시 동결한다. 동결 후 소스·자원·실행환경이 바뀌면 재개를 거절한다.

## 독립 평가 실행

아래 명령은 `scene2test`에서 실행한다. 출력 경로는 새 경로여야 하며 이미 만든 계획이나 캠페인을 덮어쓰지 않는다. 앞의 두 명령은 파일과 빈 평가 DB만 만들고 API·로봇은 실행하지 않는다.

```bash
uv run --no-sync python tools/prepare_discovery_evaluation.py freeze --config config/discovery_evaluation_luna.json --run /workspace/g1_failure/runtime/afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00002/rollout --output-dir /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_plan_v1

uv run --no-sync python tools/run_discovery_evaluation.py init --manifest /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_plan_v1/manifest.json --campaign /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v1
```

다음 명령은 **유료 실행**이다. 우선 새 장면 한 번만 실행한다. 첫 두 시도는 seed 17의 전체 도메인 uniform 초기 장면이며 AFS 제안 호출은 하지 않는다. 각 실행은 로봇 API를 최대 10회 사용한다.

```bash
uv run --no-sync python tools/run_discovery_evaluation.py run --campaign /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v1 --live --max-new-attempts 1
```

같은 명령을 다시 실행하면 다음 새 시도로 진행한다. 호출당 제한은 seed를 넘어가도 합계 한 번이다. `--max-new-attempts`를 생략하면 중단 조건 또는 동결된 목표까지 계속 실행하므로 비용 상한을 먼저 확인한다. 상태와 보고서는 무료로 확인할 수 있다.

```bash
uv run --no-sync python tools/run_discovery_evaluation.py status --campaign /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v1

uv run --no-sync python tools/run_discovery_evaluation.py report --campaign /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v1
```

각 seed는 사전 지정 순서로 실행하고 자기 seed의 새 결과만 AFS 입력으로 사용한다. 대조 자료의 장면·성공·실패와 다른 seed의 기록은 탐색 입력으로 보내지 않는다. 초기 시도의 유효 PASS/FAIL도 발견율 분모와 유형 집계에 포함한다. 유형 수는 전체 시험 집합에서 서로 다른 실패 장면의 검증된 primary를 합집합으로 계산한다. 목표를 일찍 넘더라도 나머지 사전 예산을 생략하지 않는다.

제외된 실행은 시도 예산을 소비하고 검토를 위해 멈춘다. 원인을 확인한 뒤 `--continue-after-exclusion`을 추가하면 다음 시도로 진행하며 제외 장면을 재전송하지 않는다. 정해 둔 초기 시도가 모두 제외되면 유효 탐색 근거가 없으므로 멈춘다. 초기 결과에 PASS가 없으면 기존 규칙상 FAIL 기준 완화 제안만 허용되며, 이후 기준 장면이나 후보가 없어져도 멈춘다. 외부 PASS 삽입이나 자동 Random 대체로 평가를 채우지 않는다.

작은 변경·큰 변경·조합의 순환 인덱스에는 초기 시도도 포함한다. 초기 장면은 기준 장면에서 단일 축을 바꾼 것이 아니므로 개별 축 변경 quota는 소비하지 않는다. 초기 장면은 별도 cold_start 단계로 기록하며 모든 실행 비용에는 포함한다.

캠페인 보고서는 seed별 예산·새 실행 비용·AFS 비용·보관 기록과 전체 공동 지표를 함께 보여준다. `joint_target_at_complete_budget`은 전체 유효 목표가 끝나기 전에는 null이다. 일부 규칙이 미지원이므로 전체 coverage는 여전히 null일 수 있으며, 관측된 primary 종류 수와 목표 관측 여부를 별도로 읽는다. Random Gain과 통계적 우월성은 이 실행기의 평가 대상이 아니다.

## 실패 탐색 의도와 방식의 조합 검사

독립 평가의 첫 AFS 응답은 세 후보 모두 `intent=relief`와 `mode=cross_mechanism`을 함께 사용해 로봇 실행 전에 중단됐다. 기존 요청 형식은 두 항목을 각각 제한했지만 둘의 조합은 제한하지 않았다. 수정된 요청은 아래 조합만 허용하며 실행 전 검사도 같은 공통 대응표를 사용한다.

- `relief` → `success_probe`
- `challenge` 또는 `mechanism_transfer` → `cross_mechanism`

두 항목의 조합은 [OpenAI 구조화 출력의 중첩 anyOf 계약](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)에 맞춰 후보 객체 단위로 제한한다. 완화 의도만 허용된 입력에서는 mode도 `success_probe` 하나로 제한한다. 작은 변경·큰 변경·두 축 조합에도 같은 대응 관계가 적용된다. 축·근거·기준 장면·미발견 유형 제한과 실행 전 검사는 유지한다. 응답을 받은 뒤 mode를 자동으로 바꾸거나, 모순된 후보를 몰래 버리거나, 새 요청을 자동 재전송하지 않는다.

실제 중단 응답은 이전 스키마에서는 통과하고 새 스키마에서는 거절되는 것을 읽기 전용으로 재현했다. 원본 캠페인 224개 파일은 검사 전후 해시가 같았다. 기존 두 초기 FAIL과 소비한 AFS 한 요청은 그대로 보존했다. 수정은 앞으로 생성하는 요청에 적용되며 저장된 응답을 수리하지 않는다.

관련 CPU 모의·회귀 테스트 141개가 39.07초에 통과했다. 허용 조합 전체, 완화 전용 독립 입력, 혼합 후보의 모순 거절, strict schema·기존 동적 근거 제한, 이전 탐색 모드와 재개 경로를 검증했다. 변경 Python 4개 파일의 Ruff·형식 검사와 diff 공백 검사도 통과했다. 실제 LLM의 수정 후 응답 품질은 아직 유료 실행하지 않았다.

기존 `independent_luna_v1`은 수정 전 소스와 요청이 동결된 평가다. 같은 재개 명령으로 해결되지 않으며, 수정 후에는 소스 변경 검사도 적용된다. 원래 manifest·DB·응답·예산을 편집해 재개하지 않는다. 향후 실행에는 새 버전 평가 동결 또는 별도로 검토한 명시적 복구 절차가 필요하며, 이 수정에서 어느 쪽도 실행하지 않았다. 앞의 최초 실행 명령에 있는 v1 출력 경로를 다시 사용하지 않는다.

## 회귀 자산과 다음 작업

### 행동 흐름·예측 불일치 누적 피드백 (2026-10-19)

한 번에 준비·검증·제한 실행하려면 `bash tools/run_trajectory_smoke.sh --live`를
사용한다. 먼저 `--dry-run`으로 계획만 확인할 수 있다. 현재 코드로 이전 attempt4의
환경을 10회 예산으로 새로 실행한 뒤, manifest와 VALID PASS/FAIL을 확인해야만
새 AFS 세션을 만들고 AFS 요청 최대1회·새 로봇 실행 최대1회를 진행한다.
이번 호출은 로봇 정책호출 최대20회와 AFS 요청1회이며, 전체12유효 목표를
자동 실행하는 스크립트가 아니다. 기준 기록은 상속 이력/비용으로 별도 보존한다.
기준 판정 불가 또는 단계 오류이면 중단하며 장면 전체를 자동 재시도하지 않는다.
이미 구현된 연결 전 TCP retry만 기존 정책대로 유지한다. 재실행하면 새 기준
실행부터 시작하므로 다시 유료 비용이 발생하며 기존 세션의 이어하기가 아니다.

새 출력은 `runtime/trajectory_feedback/<UTC>_<PID>`에 만들고, 전체 로그는 그 아래
`run.log`와 `scene2test/zz_log.log`에 남긴다. 후자는 최신 실행으로 덮어쓰지만
실행별 로그는 보존한다. `AFS_TRAJECTORY_SOURCE_SCENE`와 새 절대 경로인
`AFS_TRAJECTORY_OUTPUT_DIR`을 명시할 수 있고, 기존 출력은 덮어쓰기/재개하지 않는다.

새 opt-in `pattern_feedback=trajectory-v1`은 `cause-review-v3`에서만 사용한다.
기존 기본값은 `off`이며 출력 스키마·후보 순위·축 할당·거절 규칙·로봇 행동은
변경하지 않는다. `config/afs_trajectory_luna.json`은 새 개발 실험 제안용으로,
기존 breadth 개발 설정과 같은 유효12/최대16시도/20AFS/축당4/반복0을 사용한다.
이는 기존 세션의 연장이나 실행 승인이 아니다. 실제 새 세션은 이 작업에서 만들지 않았다.

요청에는 최근 제시된 실행의 행동 요약, 목표점 차단·중간 지점 도착·조작 거절·
목표 진입 및 이탈, 마지막3행동과 전체율 종료 상태를 추가한다. 목표 진입은 관측된
action 결과 지점에 한정하며, 모든 순간의 진입을 탐지했다는 뜻이 아니다.
‘차단 후 진행하다 예산 소진’의 진행은 실제 move/navigate 실행 중 목표 거리 감소
5cm 이상이라는 **탐색 요약용 기준**을 사용한다. 미세한 보행 흔들림을 진행으로
과장하지 않기 위한 값이며 기존 정체·충돌·성공 판정의 임계값은 바꾸지 않는다.
누락·불완전 기록의 부재는 UNKNOWN으로 남기고, 정체나 원인으로 해석하지 않는다.

각 예측은 해당 고정 detector의 DETECTED/NOT_DETECTED/UNKNOWN/UNSUPPORTED와
실제 primary, 종료 구간 진행·최근 차단 수·판정 대상 접촉 수를 함께 보여준다.
NOT_DETECTED는 인과적 반증이 아니며 미분류 FAIL은 여전히 유효한 FAIL이다.
LLM은 기존 change_rationale과 measurement_plan에 이전 반복 흐름과 무엇이 다르고
어떤 관측으로 구분할지 설명하도록 요청받는다. 유형 이름만 바꾸는 것으로는
다른 행동을 탐색했다고 볼 수 없지만, 작은 변화 후보를 자동 금지하지도 않는다.

누적 요약은 최근 history_limit 밖의 **이미 공급된 동일 실행 memory**까지 집계한다.
추가 아카이브 검색·다른 seed·API 호출은 하지 않는다. current/historical,
condition, 전체 task contract(호출 예산 포함), policy origin별로 분리한다.
그룹은 최대8개(current 우선), 패턴별 대표 provenance는 최대2개, 상세 예측 비교는
최근4개다. 중복 evidence는 memory의 기존 dedup을 따르며 횟수는 서로 겹치는
실패 episode 수이지 고유 실패 유형 수가 아니다. 상세 제시되지 않은 provenance는
새 anchor나 인용 ID가 될 수 없으며 기존 참조 검사를 그대로 적용한다.
요청 context와 선택 audit/HTML에 이 피드백을 보존한다.

원본 저장 자료의 읽기 전용 대조에서는 10회 조건의 유효 FAIL5개가 모두 ‘목표점
차단 후 진행하다 예산 소진’을 보였다. 15회 진단2개는 별도 조건으로 분리됐고,
attempt5의 action 결과에서 목표 안 진입·0.19초 dwell 후 최종 이탈이 요약됐다.
실제 예측 goal_occupied/collision/obstacle_interference는 각각 NOT_DETECTED로
표시됐으며 원본 FAIL이나 primary를 바꾸지 않았다. 검증한 원본587파일은 해시가
동일했다. 이는 보존 데이터 요약 검증이지 새 제안 품질·4종 발견·Gain 입증이 아니다.

관련 CPU 회귀167개가 통과했고 최종 trajectory 전용15개 테스트도 통과했다.
기본 off, 누락 데이터, 같은 condition의 다른 task budget 분리, 예측/관측 구분,
스키마의 context 해시 외 구조 유지와 동일 후보 선택, audit 보존 및 저장 응답의
추가 요청 없는 재개를 검증했다. 기존의 outcome/참조/예산/재개 guard는 유지한다.

요청 지침은 [OpenAI 공식 문서의 관련 맥락 제공 및 평가 원칙](https://developers.openai.com/api/docs/guides/prompt-engineering)을
참고해 관측과 규칙을 분리했다. 실시간 API·GPU·로봇 실험은 하지 않았다.
이전 retry 소스 변경까지 포함해 기존 동결 평가/개발 세션은 그대로 재개할 수 없다.
다음 유료 실행은 새 조건·버전·예산을 명시해 준비해야 하며, 기존 ledger/원본 수정이나
소스 drift 우회는 허용하지 않는다.

### 타임아웃 이후 개발용 이어하기 (2026-10-19)

`independent_luna_v2` seed 17은 초기 VALID FAIL 두 개와 첫 AFS 실행의
첫 로봇 호출 타임아웃 하나를 남겼다. 제외 실행은 실패 유형이 아니다.
기존 정책은 PASS 없이 relief만 허용하고 제외된 relief에도 행동 cooldown을
적용해 다음 후보가 없어질 수 있었다. 기존 평가의 규칙과 결과는 보존한다.

새 opt-in `anchor_policy=failure-diversity-v4`는 challenge에는 PASS를 요구하지만,
mechanism_transfer는 VALID PASS 또는 FAIL에서 다른 행동 가설을 탐색할 수 있다.
타임아웃은 시도·축 quota·비용을 소비하되 관측 행동 cooldown에는 포함하지 않는다.
제외 장면과 정확히 같은 환경은 자동 재실행하지 않는다. 예측은 측정 유형이 아니다.

`run_discovery_continuation.py prepare`는 기본적으로 무상 dry-run이며, `--apply`만
새 디렉터리를 만든다. 원본 manifest·체크포인트·ledger·제안·실행 증거를 검증하고
스냅샷 및 해시를 보존한다. 로봇·자원·런타임 변경이나 미완료 요청은 거절한다.
예산을 초기화하지 않으며 정책 변경은 명시적 소스 allowlist로만 허용한다.
관측 후 정책을 바꿨으므로 이 결과는 원래 독립 평가가 아니라 개발용 증거다.

```bash
# 무료 사전 검증. 적용하려면 새 출력 경로에 --apply를 한 번만 추가한다.
uv run --no-sync python tools/run_discovery_continuation.py prepare \
  --source /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v2 \
  --campaign /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v2_development

# 준비된 개발 세션의 다음 새 후보 실행: 유료, 제외 장면 재시도 아님.
uv run --no-sync python tools/run_discovery_continuation.py run \
  --campaign /workspace/g1_failure/runtime/discovery_evaluation/independent_luna_v2_development \
  --live --continue-after-exclusion --max-new-attempts 1 --max-new-afs-requests 1
```

호출당 AFS 제한은 새 요청의 상한이다. 이미 받은 응답은 재전송하지 않고 검증한다.
후보가 모두 거절되면 해당 요청 비용만 소비하고 다음 호출 전 멈출 수 있으며,
로봇 시도나 FAIL을 만들지 않는다. 개발 보고서는 보존 기록 포함 누계와
이어하기 이후 지표를 구분한다. 전체 유효 예산 완료·4종 발견·Random Gain을
달성했다고 간주하지 않는다. 원래 v2 캠페인은 새 코드로 직접 재개하지 않는다.

최신 조작 실패 attempt_00001과 성공 대조는 기존 `run_behavior_regression.py plan --run ... --run ... --repeats 2`로 준비할 수 있다. 확인한 계획은 2장면·총 4시도·최대 40로봇호출이다. 반복은 별도 유료 비용이며 AFS 발견 분모의 무료 대체 표본이 아니다. unsupported_box_face는 물리적 밀기 능력 부족이 아니라 도구 거절임을 유지한다.

다음 작업은 새로 동결한 독립 실행기에서 초기 장면 한 번을 제한적으로 live 확인하는 것이다. 유효성·새 기록·비용을 확인한 뒤 전체 평가 진행 여부를 정한다. 필요 시 별도 도메인 확장과 회귀를 수행하고 Random 비교는 공동 목표 평가 이후로 둔다. 4종 발견이나 Gain 달성은 아직 입증하지 않았다.

## 최신 trajectory AFS / Random 연결 검증 (2026-10-20)

이 절은 위의 단계별 계획을 갱신한다. `run_paired_discovery.py`는 최신 AFS와
독립 uniform Random을 같은 로봇·장면 범위·목표·정책 호출 예산으로 실행한다.
기존 기록은 실행 설정을 검증하는 대조 자료일 뿐, 어느 arm의 탐색 이력에도
넣지 않는다. seed별 두 초기 장면은 같지만 실제 실행·비용·증거는 각각 별도다.
이후 AFS는 자신의 이력만 이용하고 Random은 full-range uniform 추출을 계속한다.
예측 결과나 발견 성과로 seed/arm을 선택하지 않는다. 사전 순서와 시도 수 균형으로
실행하며, 제외·불명확한 요청은 멈춘다. 수동 제외 확인은 같은 요청의 재전송이 아니다.

AFS 피드백은 기존 expanded-ten-v1을 유지한다. 두 방법의 결과는 동일하게 동결한
system-twelve-v1과 초기 6종 기준으로 각각 측정한다. 이는 12종을 아는 AFS 구현이나
인과적 고장 원인 판정이 아니다. 동수 유효 예산을 모두 채워야 Gain을 계산하며,
Random FDR이 0이면 상대 Gain은 null이다. 연결 검증은 성능 목표 달성 증거가 아니다.

`config/paired_trajectory_smoke_luna.json`의 제안 예산은 seed17, 방법별 유효3회/
시도최대4회(초기2회 포함), 전체 유효6회/시도최대8회/로봇호출최대80회/
AFS요청최대2회이다. AFS와 로봇 모두 gpt-6-luna/default, 로봇당10호출,
응답300초이며 암묵적 시뮬레이션·토큰 상한은 추가하지 않는다.

다음 명령은 **무료 준비**만 수행한다. 기존 출력 경로는 덮어쓰지 않는다.

```bash
uv run --no-sync python tools/run_paired_discovery.py init \
  --config config/paired_trajectory_smoke_luna.json \
  --run /workspace/g1_failure/runtime/behavior_regression/luna_standard_occupied_20261020_v1/attempts/attempt_00000/rollout \
  --output-dir /workspace/g1_failure/runtime/paired_discovery/luna_trajectory_smoke_v1

uv run --no-sync python tools/run_paired_discovery.py report \
  --campaign /workspace/g1_failure/runtime/paired_discovery/luna_trajectory_smoke_v1
```

유료 실행 승인을 받은 뒤에만 `run --campaign ... --live --max-new-attempts 1
--max-new-afs-requests 1`로 시작한다. 전체 상한 승인은 별도이며, 기존 회귀나 개발
실험의 남은 예산을 이전하지 않는다. 짧은 콘솔 요약과 별도 JSON/HTML/ledger snapshot을
저장한다. 동영상은 실행별 MP4를 연결하며 GIF를 추가 생성하지 않는다.
동결 후 소스 변경 시 기존 캠페인을 우회 재개하지 말고 새 계획을 검토한다.

### Random 전용 다중 환경 탐색 (2026-10-21)

`tools/run_random_environment.py`는 위의 내구성 있는 실행기를 Random-only로
제한한 진입점이다. `config/random_environment_luna.json`은 seed29/43/71을
사전에 고정하고, seed별 유효4회/시도최대4회, 총12회/로봇 정책호출최대120회/
AFS요청0회를 제안한다. 이 문서의 준비 작업은 유료 실행 승인이 아니다.
기본 장소 구조·물체 수·20개 변수 범위는 기존 human-v5와 동일하고 매번
전체 변수 조합을 독립 균등 추출한다. 새로운 방/지형을 생성하거나 AFS의
변경 개수를 맞춘 constrained Random은 아니다. 균등 추출은 소표본에서
균형 잡힌 분포를 보장하지 않는다. 추출 결과나 실패 결과를 보고 seed를
다시 고르거나 쉬운/어려운 장면을 거르지 않는다.

초기 bootstrap/AFS arm은 없고 모든 실행이 Random discovery다. 공용 내부
SearchBudget은 기존 직렬화 규약상 max_afs_requests>=1이므로 호환용 값1을
유지하지만, 외부 설계·manifest·arm 상한은0이며 proposer 진입은 거부한다.
Luna/default 로봇 제어 호출은 여전히 유료이며 실행당 최대10회다.
원본 대조 기록은 설정 검증 전용으로, 새 탐색 이력이나 지표 분모에 들어가지 않는다.

보고서는 `planned_random_scenes.json`에 실행 전 결정되는 전체 장면값을 저장하고,
`summary.json/environment_distribution`에 계획·실제 시도의 변수별 min/max와
허용 구간 3등분 빈도를 기록한다. 이는 제외 시도도 포함하는 환경 분포 기술이며
실패 유형 커버리지나 20차원 결합 공간 커버리지의 증명이 아니다. 공통12종과
초기6종을 별도 집계하고 AFS 비교/Gain은 `not_requested_random_only`/null이다.
각 실행의 MP4/원본 보고서 링크와 seed별 ledger를 보존한다.

무료 준비(기존 경로에 init을 반복하지 않는다):

```bash
uv run --no-sync python tools/run_random_environment.py init \
  --config config/random_environment_luna.json \
  --run /workspace/g1_failure/runtime/behavior_regression/luna_standard_occupied_20261020_v1/attempts/attempt_00000/rollout \
  --output-dir /workspace/g1_failure/runtime/random_environment/luna_full_domain_v1

uv run --no-sync python tools/run_random_environment.py report \
  --campaign /workspace/g1_failure/runtime/random_environment/luna_full_domain_v1
```

상한 검토 및 유료 실행 승인 후 다음 한 명령으로 전체 남은 시도를 실행할 수 있다.
매번 한 회씩 수동 호출할 필요는 없다. 기존 paired smoke는 완료 상태로 보존한다.

```bash
set -o pipefail
uv run --no-sync python tools/run_random_environment.py run \
  --campaign /workspace/g1_failure/runtime/random_environment/luna_full_domain_v1 \
  --live --max-new-attempts 12 \
  2>&1 | tee -a /workspace/g1_failure/runtime/random_environment/luna_full_domain_v1/run.log
```

제외·불명확한 호출은 자동 재시도/대체 없이 중단한다. 제외도 시도 예산을 소비하므로,
이번 고정 상한에서는 유효 목표를 채우지 못할 수 있다. 원인을 검토한 뒤 명시적으로
제외 후 계속하더라도 같은 장면을 재전송하거나 예산을 초기화하지 않는다.
시도 상한에 도달한 seed는 TARGET_NOT_REACHED가 될 수 있으며 전체 흐름도 멈춘다.

### 분류 설명과 저장된 AFS 피드백 점검 (2026-10-21)

`reporting/classification_explanation.py`는 표시 전용이다. 보고서와 짧은 콘솔
요약에 주 유형 있음/복합 징후로 주 유형 보류/지원 유형 미검출/측정 불충분/
미검증 귀속/기타 미지정을 나눠 표시한다. PASS·제외는 실패 설명 분모에 넣지 않고,
복사된 증거는 중복 제거한다. 집계 단위는 FAIL 에피소드이므로 반복 장면의
기존 distinct-scene 귀속 지표와 다를 수 있다. 기존 unclassified_failures,
primary 우선순위, 모호성 규칙, FDR·유형 수·Gain은 변경하지 않는다.

실제 Random12회 기록은 주 유형7/복합1/지원 유형 미검출4다. 복합 사례는
seed43/attempt_00003의 goal_occupied+human_safety_risk 동시 검출이다.
원래의 주 유형 미지정5회와 발견4종은 그대로다. 이를 임의로 단일 유형으로
승격하거나 새로운 가족으로 추가하지 않는다.

새 snapshot의 `afs_feedback_audit.json`은 저장된 context/request/response의
context digest 연결을 확인하고 전달된 행동 진단·trajectory 요약·episode review
참조를 기록한다. 저장 응답이 없거나 레이아웃이 다르면 불확실 상태로 표시하며,
정보가 없었다고 단정하지 않는다. 모델의 실제 이해·가설의 진실·인과성이나
탐색 효과를 검증하는 기능이 아니다. 요청 재전송이나 추가 모델 호출은 없다.

실제 완료된 paired smoke의 유일한 AFS 요청에는 이미 두 초기 실행의 차단 횟수,
진행 행동, 조작 요청 없음, 마지막 행동·최종 거리와 실패 원인 검토 계약이 있었다.
반환된 응답에도 실패 가설과 대안이 있다. 따라서 정보 누락을 확인하지 않은 채
피드백·정책·로봇 입력을 더 늘리지 않는다. 예측한 goal_occupied는 실행 후
terminal-stall 조건을 충족하지 않아 NOT_DETECTED였으며 원래 판정이 유지된다.

`report`는 새 timestamp snapshot만 만들며 유료 실행이 아니다. 콘솔은 방금
저장된 summary.json을 읽어 동일한 결과를 출력하므로 큰 trace를 다시 읽는
중복 계산을 피한다. 기존 보고서·ledger·실행 결과·예산을 덮어쓰지 않는다.

## 환경 단일요소 개발 실험 (2026-10-21)

Random 12/12 FAIL 이후 기준 장면 반복은 1 PASS/1 FAIL이었다. 따라서 전부
환경 탓으로 단정하거나 성공 장면 하나만 고르지 않고, 두 최신 원본을 함께
사용한다. `tools/run_factor_calibration.py`는 기존 대조 실행기에 명시적
`one-factor-at-a-time-v1` 설계를 추가한다. 기존 단일축 대조는 그대로다.

| 장면 | 기준 대비 변경 | 새 반복 |
|---|---|---:|
| 공통 기준 | 변경 없음 | 2 |
| 통로 | 폭 3.6 → 2.8m | 2 |
| 바닥 | 마찰 0.8 → 0.5 | 2 |
| 사람 | 횡방향 fraction 0.2 → −0.8 | 2 |

각 탐색 장면은 기준에서 선언된 파라미터 하나만 변경한다. 폭 변경은
장애물·사람의 파생 세계좌표에도 영향을 줄 수 있어 물리적 독립 처치는 아니다.
목표·판정·정책 모델·호출 예산·push 설정은 유지한다. 수준은 새 결과를 보기
전에 고정했으며 더 쉽거나 어렵다는 보장은 없다. 기준 2회, 통로 2회, 바닥
2회, 사람 2회의 고정 순서라 시간·provider 변동과 순서 효과도 구분할 수 없다.
작은 개발 표본이며 인과 증명, 전체 환경 커버리지, AFS/Random 비교가 아니다.

무료 준비 `init`는 8회/최대 80 로봇 정책 호출/AFS 0회의 새 예산을 동결한다.
기존 기준 2회/20호출 비용은 별도로 남는다. 아래 명령은 **유료 실행**이며
scene2test 디렉터리에서 한 번 실행하면 최대 8회를 수행한다. 제외나 오류면
중단하고 자동 재시도·대체·예산 초기화하지 않는다. MP4는 각 rollout에 남는다.

```bash
set -o pipefail
uv run --no-sync python tools/run_factor_calibration.py run --live \
  --max-new-attempts 8 2>&1 | tee -a \
  /workspace/g1_failure/runtime/factor_calibration/luna_oat_20261021_v1/run.log
```

준비 폴더가 없는 별도 환경에서는 먼저 같은 도구의 `init`를 실행한다.
이미 준비된 폴더에 init를 다시 실행하지 않는다. 이전 개발 중 준비 폴더
`luna_oat_v1`은 최종 코드 이전이므로 실행하지 않고 보존한다. 최종 이름은
`luna_oat_20261021_v1`이다. 이후 코드를 변경하면 동결 검사를 우회하지 않는다.
결과는 네 장면의 PASS/FAIL 및 행동 기록을 비교해 다음 개발 조건을 정하는 데
쓴다. 그 조건을 확정한 뒤 별도 미사용 seed로 AFS/Random 평가를 준비한다.

## 목표 접근로가 열린 기준 장면 검증 (2026-10-21)

완료된 단일요소 실험에서 목표 접근의 공통 병목을 확인한 뒤, 기존 기준 두
기록(1 FAIL/1 PASS)을 모두 보존하고 박스 횡방향 fraction만 0.5→1.0으로 바꾼
후보를 검증한다. 새 `single-probe-validation-v1`는 기존 control을 새로 반복하지
않고 후보만 2회 실행하므로 최대 20 로봇 정책 호출, AFS 0회다. 기존 대조와
factor 설계의 검증은 유지하며, 후보에 다른 파라미터/로봇 설정 변경을 금지한다.

`tools/run_goal_clearance_control.py init`는 무료다. 저장된 두 초기 관측을 해시로
확인하고, 기록된 planner 소스가 현재와 같은지 확인한 뒤 메모리상 박스 위치만
후보 위치로 옮겨 동일 목표에 `path_found`가 나오는지 검사한다. 이는 정적 경로
가능성 검사이지 물리 시뮬레이션이나 측정된 PASS가 아니다. 실제 로봇 조건과
원본 아카이브도 기존 검증을 거쳐 새 폴더에 동결한다.

최종 준비 폴더는 runtime/goal_clearance_control/luna_clear_goal_20261021_v1이다.
준비 완료 후 scene2test에서 한 번 실행하면 최대 2회를 수행한다.

```bash
set -o pipefail
uv run --no-sync python tools/run_goal_clearance_control.py run --live \
  2>&1 | tee -a \
  /workspace/g1_failure/runtime/goal_clearance_control/luna_clear_goal_20261021_v1/run.log
```

제외/오류면 중단하고 자동 재시도나 대체 실행을 하지 않는다. 결과를 보고도
PASS가 나올 때까지 예산을 초기화하지 않는다. 두 결과와 행동을 먼저 검토하고,
개발용 환경 범위를 결정한 뒤 **별도의** 공통 범위·미사용 seed·동일 예산으로
최종 AFS/Random 평가를 준비한다. 이 명령이 최종 비교까지 자동 실행하지는
않는다. 2 PASS도 성공 확률이나 AFS 우위를 통계적으로 입증하지 않는다.
목표·판정·로봇·모델·호출 예산은 그대로이며, 새 온라인 taxonomy나 robot 정책
개선은 이 단계에 포함하지 않는다. 완료된 과거 캠페인을 새 코드로 재개하지 않는다.

## 공통 항법 하위영역 AFS/Random 비교 (2026-10-21)

기준 검증은 실제 2 PASS/0 FAIL/0 제외로 완료됐다. 각각 정책 호출 6회·5회,
최종 거리 약 0.115m, 기록된 1초 체류를 충족했다. 경로계획·navigate_to만
사용했으며 직접 move 보정이나 push가 없었다. 이 개발 기록은 실행 설정을
확인하는 근거일 뿐 새 평가의 이력·성공 표본으로 복사하지 않는다.

새 `config/paired_navigation_domain_luna.json`은 아래 세 축만 원래 전체
범위보다 좁힌다. 다른 17개 축은 원래 범위를 유지한다.

| 축 | 새 공통 범위 | 목적 |
|---|---|---|
| 통로 폭 | 3.6–4.0m | 검증한 통로 부근의 항법 비교 |
| 박스 횡방향 fraction | 0.85–1.0 | 목표 중심점의 공통 박스 차단 제거 |
| 바닥 마찰 | 0.5–1.1 | 기준 0.8 주변의 명시적 개발 범위 |

이는 **항법 하위영역**이다. 원래 전체 분포나 목표 주변 박스 차단 실험을
대체하지 않으며 원래 6종 중 4종 달성으로 주장하지 않는다. 특히 초기 목표
박스 점유 유형의 기회는 의도적으로 줄어든다. 전체 프로젝트의 유형 목표는
그대로 남는다. 정적 목표 중심점 간격이 충분해도 장애물·사람 때문에 전체
경로가 막히거나 로봇이 실패할 수 있다. 성공률/Gain은 사전에 보장하지 않는다.

`clear_path/search_domain.py`가 버전·전체 축 목록·유한한 엄격 부분 범위를
검증한다. singleton/fixed 축과 물리 범위 확장은 받지 않는다. 선택한 범위는
paired manifest/domain_id 및 각 arm protocol에 동결한다. 동일 범위가 Random
추출, AFS cold start, LLM allowed_axes, 수치 검증, 거리·변경량 정규화, 저장
응답 재검증, 실행 직전 전체 후보 검증에 적용된다. 범위 밖 후보는 원본 값을
보존한 채 거절하며 clamp·범위 확장·Random 대체가 없다. 기존 breadth 수치
거절/요청 상한을 그대로 사용한다. 새 옵션이 없으면 기존 전체 범위 유지다.

Random은 모든 축의 공통 범위에서 독립 균등 추출한다. 기하 검사나 결과로
거절·재추출하지 않는다. 같은 seed/index의 초기 2개 장면을 두 방법이 각각
유료 실행하고 예산에 포함한다. 이후 AFS는 자기 arm/seed의 기록만 사용하며
Random은 계속 독립 추출한다. 새 평가 이력은 비어 있고 외부 PASS를 주입하지
않는다. 동일 장면을 복사해 두 방법이 실행한 것으로 계산하지 않는다.

사전 seed는 101/211/307, seed·방법당 유효 목표 6회·시도 상한 8회, AFS 요청은
seed당 8회다. 총 유효 목표 **36회**(방법별 18회), 상한 **48회 시도·480 로봇
정책 호출·24 AFS 요청**이다. 전원 Luna/default, 로봇 호출 예산 10회, 기존
목표·체류·판정·push 설정 그대로다. 유한 소표본의 기술적 비교이며 신뢰구간이나
통계적 우위 검정은 제공하지 않는다. 원래 6종과 시스템 12종을 별도로 기록한다.

새 준비 경로:
`/workspace/g1_failure/runtime/paired_discovery/luna_navigation_domain_20261021_v1`.
기존 캠페인에 init/run하지 않는다. 준비 자체는 아래 명령으로 무료 수행한다.

```bash
uv run --no-sync python tools/run_paired_discovery.py init \
  --config config/paired_navigation_domain_luna.json \
  --run /workspace/g1_failure/runtime/goal_clearance_control/luna_clear_goal_20261021_v1/attempts/attempt_00000/rollout \
  --run /workspace/g1_failure/runtime/goal_clearance_control/luna_clear_goal_20261021_v1/attempts/attempt_00001/rollout \
  --output-dir /workspace/g1_failure/runtime/paired_discovery/luna_navigation_domain_20261021_v1
```

이미 준비된 경로에 init를 반복하지 않는다. 준비 후 한 번에 전체 고정 예산을
진행하는 명령은 다음과 같다. 인자 없이 실행하거나 --dry-run이면 출력만 한다.

```bash
bash tools/run_navigation_comparison.sh --dry-run
bash tools/run_navigation_comparison.sh --live
```

로그는 새 캠페인의 run.log, 보고서는 reports/<timestamp>/report.html이다.
제외·오류 시 중단하며 자동 계속/에피소드 재시도/대체/예산 초기화는 없다.
고정 예산 종료 전에 목표 지표가 좋아져도 조기 종료하지 않는다. 비용은 로봇과
AFS를 별도 기록한다. 공통 범위·로봇·판정·예산·seed를 결과 확인 후 변경해서
같은 평가로 합치지 않는다. 향후 결과가 나쁘더라도 Random을 약화시키거나
지표를 다른 것으로 사후 교체하지 않는다.
# Behavior-relevant mandatory factor allocation (2026-10-21)

The completed `luna_navigation_domain_20261021_v1` comparison is preserved:
AFS 0/18 failures, Random 2/18, three infrastructure exclusions. It is not a
successful AFS superiority result. Do not resume this completed/frozen campaign
with changed sources or replace exclusions with diagnostic reruns.

Priority 1 is implemented as a new opt-in SearchBudget field:
`factor_allocation="behavior-relevance-v1"`. The default `balanced-v1` retains
the existing breadth allocation. The new option requires `breadth-v1`,
`cause-review-v3` and `trajectory-v1`. A separate development configuration is
`config/afs_behavior_relevance_luna.json`; it does not inherit a navigation
subdomain implicitly and must not be used as an unannounced replacement for the
paired design. A future paired design must explicitly retain its shared domain,
budgets, robot settings and fresh predeclared evaluation seeds, and freeze the
new search setting before any execution. This change does not launch a campaign.

Behavior evidence comes from verified supplied memory, not from LLM prose or
predicted labels. In independent/paired evaluation this is the arm's own seed
history only. Only VALID PASS/FAIL episodes participate. When every supplied
episode has complete action windows and no manipulation request, object mass
and friction are removed from **mandatory group rotation**, not from the
allowed environment axes. They remain optional second factors in a combination
with a required group. If only deferred groups are selectable, required_group
is null: no group is forced; form/quota/bounds/duplicate guards remain intact.
Incomplete, censored, missing or empty actions are UNKNOWN and do not justify
deferral. An observed manipulation request, including a local tool rejection,
restores balanced group eligibility; it does not prove physical engagement,
causal sensitivity or physical manipulation success. Exclusions still consume
the original attempt/axis quotas but supply no relevance evidence.

The request, chosen-candidate audit and allocation summary save the same
version, status, evidence IDs and deferred groups. No detector, outcome,
threshold, transport retry, robot, action budget, Random sampler or shared axis
bounds changes. This is an allocation heuristic, not a new failure detector or
a calibrated risk estimate. Large/small/combination scheduling is unchanged.

Read-only replay of the actual pre-object-probe histories (no source DB opened)
shows the following allocation changes; this is not a counterfactual rollout:

| Seed | Old mandatory group | New mandatory group | Object axes retained |
|---|---|---|---|
| 101 | object_physics | obstacle_geometry | mass, friction |
| 211 | object_physics | layout | mass, friction |
| 307 | object_physics | obstacle_geometry | mass, friction |

Priorities 2/3 (near-boundary PASS scoring and behavior-linked candidate ranking)
are deliberately not bundled into this version. Changing one search mechanism
first allows its allocation effect to be inspected without claiming that FDR
has improved. No paid/API/GPU/robot execution was performed during implementation.
