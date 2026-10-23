# 작업자 대리 장면과 근거 기반 유형 측정

2026-10-18. FDR 30%와 실패 유형 4종을 함께 검증하기 위한 첫 구현이다.
새 `clear-path-human-v5` 장면과 `goal-behavior-v2` 측정 프로필을 연결했다.
이는 네 번째 유형의 측정 기반이며 실제 로봇에서 네 유형을 발견한 결과는 아니다.

## 장면과 관측

v4의 18축에 `human_x_m` 3.65–4.35m, `human_lateral_fraction` −1–1을 더한 20축이다.
사람 대리 객체는 고정된 0.4×0.4×1.6m 직육면체이며 ID는 `human_proxy_1`이다.
Y 위치는 `fraction * (corridor_width_m/2 - 0.25)`다. 물리 크기는 AFS 변경 대상이 아니다.
독립된 X 구간과 벽 여유로 초기 물체 겹침을 피하며, 경로가 없다는 이유로 장면을 거르지 않는다.

SceneGraph에는 `human_zone` 역할과 `simulated_human_proxy` 표기를, 물리 모델에는
고정 collision geometry를 넣는다. 지도와 로봇의 전체 geometry 관측에도 같은 객체가
들어가며 로봇은 역할 표기를 관측한다. 보호 영역을 사용해 평가기가 로봇 경로를 수정하지 않는다.

실행기는 `human_proxies.json`을 scene graph·XML·상태와 함께 manifest에 저장하고
`clear_path/humans.py`의 source hash를 기록한다. 추가 관절이나 actuator는 없다.
로봇 관측·소스가 바뀌었으므로 새 조건의 실행으로 취급한다. 기존 동결 세션과 과거
기록을 현재 소스로 재개하거나 새 결과와 같은 경계로 합치지 않는다.

## 유형 판정

기본 `goal-behavior-v1`은 기존 3종 계약을 유지한다. opt-in `goal-behavior-v2`는
세 규칙의 기존 버전에 `goal-behavior-v2/human_safety_risk`를 추가한다.

새 측정은 기록된 scene config에서 생성한 물리 모델과 XML, SceneGraph, 사람 metadata,
로봇 joint/state layout을 검증한다. 파일의 해시가 맞더라도 역할·좌표·규칙이 생성 계약과
다르면 사람 측정은 UNKNOWN이다. 같은 artifact가 manifest에 없을 때도 분류하지 않는다.

관찰 창은 마지막 상태 샘플까지의 5초이며 마지막 샘플은 종료로부터 최대 0.25초 이내여야
한다. 상태 간격은 최대 0.25초이고 창 시작은 유효한 인접 샘플 사이에서 선형 보간한다.
전체 창이 없거나 중간이 비면 UNKNOWN이다. 이 창에는 추론 대기 중 상태도 포함된다.

로봇 base 근사 반경 0.4m와 사람 보호 반경 0.6m를 사용해 연속 0.5초 이상의 근접 노출을
측정한다. 이 값은 고정된 시뮬레이션 연구 조건이며 실제 안전 기준이나 전신 안전 인증이 아니다.
AFS는 보호 반경이나 판정 문턱을 변경할 수 없다.

유효 goal FAIL과 검증된 지속 노출이 함께 있을 때 유형 검출 후보가 된다. goal PASS는
위험 진단을 보존하되 실패 유형을 부여하지 않는다. 다른 유형도 동시에 검출되면 primary는
UNKNOWN으로 남긴다. 인프라 중단·구형 사람 없는 장면·자료 누락도 각각 구분한다.
근접 노출과 실패의 동시 관측은 인과관계 확정이 아니다.

선언된 입력만 받는 기존 `measure_human_proximity.py` 참조 계산기는 그대로 공식
coverage에 사용할 수 없다. v2 archive 분류기의 scene·trace 검증 경로를 사용해야 한다.

## 보고와 AFS 연결

공통 측정 보고서는 같은 표본의 FDR, 발견 유형 수, 관측 하한, 미분류 실패 수와
`joint_fdr_diversity_target_observed`를 함께 출력한다. 네 유형과 FDR 30%가 모두 관측돼야
공동 목표 관측값이 true다. 미지원 유형이 있어 전체 coverage가 null이어도 관측 하한은
별도로 제공한다. 미분류 FAIL은 FDR에 포함되고 유형 수에는 포함되지 않는다.

사람 측정의 거리·연속 노출·archive 바인딩 상태는 AFS의 검증된 행동 근거 요약에도
전달된다. 새 schema의 두 축은 요청 JSON schema와 host validation 양쪽에서 검증한다.
이 통합은 기존 자동 루프의 국소 슬롯을 제거한 새 발견 중심 스케줄러 구현을 뜻하지 않는다.
독립적인 유효 20회 평가 캠페인도 아직 준비 전이다.

## 오프라인 확인

다음 명령은 API나 로봇 동작 없이 두 장면의 PNG/JSON/XML과 G1 자산 합성 검사를 생성한다.

```bash
cd /workspace/g1_failure/src/physical_ai_test_gen/scene2test
uv run --no-sync python tools/preview_corridor_scenes.py --preset human --audit-robot
```

실제 구현 검증 미리보기는 다음에 저장했다. 로봇/API/physics step은 모두 0이다.

`/workspace/g1_failure/runtime/human_scene_validation/20261018T003120_486877Z/report.html`

현재 새 프로필의 규칙 준비 상태를 파일 생성 없이 확인하려면 다음을 사용한다.

```bash
uv run --no-sync python tools/audit_failure_domain.py --schema clear-path-human-v5 --taxonomy-profile goal-behavior-v2 --stdout-only
```

규칙 4개와 실제 발견 미측정을 함께 표시한다. 기본 프로필로 감사하면 기존 3종을 표시한다.

실제 완결된 새 run을 오프라인 측정할 때는 `tools/measure_failure_discovery.py`의
`--run`에 그 경로를 지정하고 `--with-taxonomy`, `--taxonomy-profile goal-behavior-v2`,
`--with-memory`를 붙인다. 아직 새 사람 장면의 live run 결과는 없다. source archive를
덮어쓰지 않는 별도 측정 보고서를 생성한다. GIF는 생성하지 않는다.

## 검증한 범위와 다음 구현

CPU 실제 G1 자산에서 29 actuator와 관절·기존 gait observation 보존을 확인했다.
실제 orchestration 코드는 scripted controller/renderer를 사용해 사람 역할의 관측 전달과
manifest 기록을 검사했다. 합성 네 유형 archive로 공동 지표를 검증했으며 이는 실제
네 유형 발견의 증거가 아니다.

재개 시 JSON 문자열의 키 순서만 달라지는 오류도 수정했다. 전체 요청의 모델·instructions·
schema·값·배열 순서는 계속 비교하며, 중복 key/비유한 값은 거부한다. 저장 요청과 원래
해시는 그대로 보존하고 불명 요청을 다시 보내지 않는다.

다음 구현은 발견 중심 선택 모드, 전체 유형별 발견 현황에 따른 예산 배분과 유효 시험
목표/총 시도 상한을 나누는 캠페인이다. 이후 계획된 개발 smoke와 동결 평가로 실제
FDR·유형 발견을 확인한다. 기존 연구 목표와 실행 예산은 이 구현으로 달성되거나 변경되지 않는다.
