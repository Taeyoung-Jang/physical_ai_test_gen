# P0 실패 발견 측정기 및 최소 행동 기록 reader 구현

날짜: 2026-09-26 UTC.
요청: 수립한 계획을 하나씩 구현. 이번 범위는 첫 측정 모듈과 최소 trace 변환이다.

## 구현 내용

- `failure_client/evaluation/research_records.py`: 엄격한 입력/비교 설계/실행/측정/유형 근거 계약.
- `failure_client/evaluation/goal_run_reader.py`: goal-agent-v5/goal_outcome_v1의 읽기 전용 importer.
  manifest 경로·해시, 필수 파일, 목표·로봇 조건·결과 플래그, provenance 형식 및 상태 로그 검사.
  정상 PASS/FAIL과 INCONCLUSIVE/INCOMPLETE/INVALID/UNSUPPORTED 분리.
- `failure_client/reporting/discovery_metrics.py`: FDR, 상대 Gain, 6종 분모의 detector-gated coverage,
  seed/조건/예산 검사, 중복 방지, 고유 장면/반복 실패, 누적 곡선·부분 비용 집계.
- `failure_client/reporting/discovery_report.py`: 신규 출력 폴더에 JSON/CSV/HTML/manifest 생성.
- `tools/measure_failure_discovery.py`: `--run` 반복 입력 또는 versioned `--input` JSON으로 오프라인 측정.
- `tests/client/test_discovery_measures.py`: 합성 기록/수학적 정답/파일 손상/CLI/보고서 검증 49개.
- [실행 및 해석 문서](../scene2test/docs/FAILURE_DISCOVERY_MEASURES.md) 추가.
  기존 전체 계획·로드맵·AGENTS의 구현 상태를 갱신하고 기존 미커밋 계획 변경은 보존했다.

## 판정 원칙

목표 달성 여부와 접촉·낙상·기술 실패 사건을 분리한다. 행동 사건이 있다는 이유로 FAIL이나
실패 유형을 자동 부여하지 않는다. 제공된 LLM 가설도 유형 정답으로 사용하지 않는다.
현재 실제 importer에 6종 detector는 없으므로 coverage는 null/not_measured이고 유형은 UNSUPPORTED다.
합성 fixture의 4/6 계산 테스트는 실제 로봇의 4종 발견 증거가 아니다.

Random 비교는 선언된 조건/seed/동일 유효 예산이 맞을 때만 계산한다.
Random 실패 0개에서는 상대 Gain을 계산하지 않는다. 공통 초기 실험·반복·경계 실행도 유효 예산에 포함.
같은 run을 복사하거나 다른 method/seed에 이중 할당하는 방식으로 결과를 늘리지 못하도록 한다.
기존 run에 execution UUID가 없어 핵심 증거가 완전히 동일하면 보수적으로 중복 처리한다.
한 장면을 여러 primary family로 다시 명명한 경우 diversity 집계에서 모호한 장면으로 분리한다.

공식 verdict는 원본 고주파 평가기를 따르며 샘플 trace로 물리를 재실행하지 않는다.
최소 행동 통계는 샘플 목표 거리/진척/XY 이동거리/dwell/높이/기울기/행동 횟수/사건 기록 수다.
미끄럼·안정성 여유·인과관계 판정이나 로봇 제어 변경은 포함하지 않는다.
이 입력은 사후 method/domain 선언이므로 prospective Random 생성 과정의 감사 증거는 아니다.

## 검증

```bash
PYTHONPATH=src .venv/bin/pytest tests/client/test_discovery_measures.py -q
```

최종 49 passed (9.10s).

```bash
PYTHONPATH=src .venv/bin/pytest tests/client tests/test_behavior_afs.py tests/test_behavior_afs_cli.py tests/test_goal_outcome.py tests/test_goal_outcome_runner.py -q
```

최종 136 passed (49.35s). 기존 client/AFS/목표 평가의 CPU 회귀 테스트 포함.
초기 45개 테스트 통과 후 예산 전 단계·live 모델 식별 누락·manifest 외부 symlink·잘못된 종료 이유
검사를 4개 추가했다. 초기 정적 검사에서 긴 줄/lambda 경고가 있어 수정/포맷한 뒤 Ruff 통과.
기능 테스트는 합성 입력과 CPU 테스트 더블이며 새 실제 GPU/VLM 성공 근거가 아니다.

## 기존 실험에 적용

문서의 명령을 그대로 사용했다. 의존성 변경·API 호출·GPU 실행은 없다.

```bash
uv run --no-sync python tools/measure_failure_discovery.py --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T151327_858717Z --run /workspace/g1_failure/runtime/robot_goal_agent/20260926T130019_070486Z
```

최종 보고서:
`/workspace/g1_failure/runtime/failure_measures/20260926T165815_679403Z/report.html`.
초기 smoke 보고서 `20260926T165224_583074Z`도 덮어쓰지 않고 보존했다.

- `151327_858717Z`: missing_manifest → INCOMPLETE.
- `130019_070486Z`: legacy_or_unsupported_profile → UNSUPPORTED.
- 결과: valid=0, excluded=2, FDR=null, Gain 계산 불가, diversity 미측정.
- 생성 성공은 계측/진단 경로 검증이지 AFS 성능 목표 달성을 뜻하지 않는다.

## 환경 및 변경 안전성

기본 exec에서 bwrap namespace 권한 오류가 재현되어, 범위가 명시된 승인 경로로 읽기/실행했다.
파일 편집은 apply_patch로 정상 수행했으며 sandbox 설정 자체는 변경하지 않았다.
원본 실험 결과, 로봇 코드/프롬프트/평가 조건, GIF 비활성화 및 시간 상한 제거 상태를 보존했다.
새 산출물만 runtime/failure_measures 아래에 생성했다. commit/push는 수행하지 않았다.

## 남은 범위

P1 시간 구간별 행동 근거·유형 규칙·failure memory 및 회귀 bundle,
P2 자동 campaign/예산 ledger와 실제 AFS/Random 비교, P3 장면/유형 확장·회귀 실행,
P4 여러 seed의 동결 평가/통계는 아직 남아 있다.
AFS 비용·미완료 API 토큰·전체 wall time은 현 importer에서 완전 계측되지 않으며 누락으로 표시한다.
