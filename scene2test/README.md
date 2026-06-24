# Scene2Test

Physical AI 행동 회귀 테스트 자동화 시스템.
3D Scene Graph + Active Failure Search로 로봇이 실패하는 씬 조건을 자동으로 탐색한다.

---

## 개요

```
씬 라이브러리(JSON) → [Active Failure Search] → 실패 조건 목록(FAIL/BLOCKED)
       ↑                       ↑
 절차적 생성기           PyBullet 시뮬레이터
 (scene_generator)       (Physical Oracle)
```

- **탐색 전략**: Bayesian Optimization 기반 Surrogate 모델로 실패 가능성이 높은 씬 변수를 우선 탐색
- **Cross-scene 전이**: 라이브러리 전체에서 학습한 Surrogate를 warm-start로 재사용 (cold 대비 FDR +6%p)
- **Track A/B 지원**: 절차적 씬 그래프(Track A) + RGB-D 카메라 입력(Track B)

---

## 설치

Python 3.12 이상, [uv](https://docs.astral.sh/uv/) 사용 권장.

```bash
cd scene2test
uv sync
```

의존성은 `pyproject.toml`에 선언되어 있으며, 주요 패키지는 다음과 같다.

| 패키지 | 용도 |
|---|---|
| pybullet | 물리 시뮬레이터 (Kinematic Oracle) |
| scikit-learn | Surrogate 모델 (Random Forest / GP) |
| open3d | RGB-D 포인트 클라우드 처리 |
| streamlit + plotly | 분석 대시보드 |

---

## 빠른 시작

모든 명령은 `scene2test/` 디렉터리에서 실행한다.

### 1. 씬 라이브러리 생성

```bash
uv run python src/scene_generator.py --n 20 --output-dir data/scene_library --seed 0
```

기본 20개 씬이 `data/scene_library/scene_XXXXX.json`으로 저장된다. 이미 생성된 20개가 포함되어 있다.

### 2. Active Failure Search 실행

```bash
# 단일 씬, cold 모드 (기본)
uv run python src/active_failure_search.py \
    --scene data/scene_library/scene_00100.json \
    --mode cold \
    --rounds 5

# warm-start 모드 (라이브러리 Surrogate 재사용)
uv run python src/active_failure_search.py \
    --scene data/scene_library/scene_00100.json \
    --mode warm \
    --rounds 5

# Random vs Active 비교 실험
uv run python src/active_failure_search.py \
    --scene data/scene_library/scene_00100.json \
    --mode compare \
    --rounds 5 --tests-per-round 10
```

결과는 `data/search_logs/` 에 JSON으로 저장된다.

**주요 옵션**

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--scene` | `data/scene_library/scene_00100.json` | 탐색 대상 씬 파일 |
| `--mode` | `cold` | `cold` / `warm` / `random` / `compare` |
| `--rounds` | `5` | 탐색 라운드 수 |
| `--tests-per-round` | `10` | 라운드당 실행 테스트 수 |
| `--surrogate` | `rf` | `rf` (Random Forest) / `gp` (Gaussian Process) |
| `--seed` | `42` | 재현성 시드 |

### 3. Streamlit 대시보드

```bash
uv run streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속.

사이드바에서 로그 파일(`data/search_logs/`)과 씬 라이브러리를 선택하면 4개 패널이 갱신된다.

| 패널 | 내용 |
|---|---|
| 씬 그래프 3D | 씬 내 객체 배치 산점도 |
| Failure Discovery Curve | 라운드별 누적 실패 발견 수 |
| 판정 분포 & Margin | PASS/WARN/FAIL/BLOCKED 비율 + 6종 안전 마진 박스 플롯 |
| 결과 테이블 & 반례 | 필터링된 테스트 기록 + 상위 반례 상세 |

### 4. 보고서 생성 (프로그래밍 방식)

```python
from src.reporter import load_all_logs, generate_test_table, generate_comparison_report

# 로그 로드
all_results = load_all_logs("data/search_logs")

# 테스트 결과 테이블 (CSV + Markdown)
generate_test_table(list(all_results.values())[0], output_dir="reports")

# 방법론 비교 보고서
comparison = generate_comparison_report(all_results, output_dir="reports")
```

---

## 테스트

```bash
# 전체 테스트 스위트
uv run python tests/test_p1_scene_builder.py
uv run python tests/test_p2_scene_generator.py
uv run python tests/test_p3_feature_extractor.py
uv run python tests/test_p4_mutation_space.py
uv run python tests/test_p5_physical_oracle.py
uv run python tests/test_p6_active_failure_search.py
uv run python tests/test_p7_scene_library.py
uv run python tests/test_p8_reporter.py
uv run python tests/test_p9_comparison.py
uv run python tests/test_p10_rgbd.py

# pytest로 일괄 실행 (GUI 없는 환경)
PYBULLET_MODE=DIRECT uv run pytest tests/ -v
```

---

## 프로젝트 구조

```
scene2test/
├── src/
│   ├── scene_graph.py          # SceneGraph 데이터 스키마
│   ├── scene_builder.py        # PyBullet 씬 로드·리셋
│   ├── sim_runner.py           # Kinematic 경로 실행
│   ├── scene_generator.py      # 절차적 씬 생성기 (CLI 포함)
│   ├── validity.py             # 씬 유효성 검사
│   ├── feature_extractor.py    # 씬 → 피처 벡터 (39차원)
│   ├── mutation_space.py       # 씬 변수 샘플러 (LHS / 경계 시드)
│   ├── physical_oracle.py      # 6종 안전 마진 + 판정 엔진
│   ├── surrogate_model.py      # RF / GP Surrogate
│   ├── acquisition.py          # 획득 함수 + TopK-Diverse 선택
│   ├── active_failure_search.py # AFS 탐색 루프 + CLI
│   ├── scene_library.py        # 라이브러리 Surrogate (cross-scene 전이)
│   ├── reporter.py             # CSV / Markdown / JSON 보고서 생성
│   └── vision/
│       └── rgbd_to_graph.py    # RGB-D → SceneGraph (Track B)
├── config/
│   ├── robot_config.yaml       # Franka Panda 설정
│   ├── task_config.yaml        # Pick-and-Place 태스크 설정
│   ├── thresholds.yaml         # 판정 임계값 (기본)
│   └── thresholds_p9.yaml      # 완화된 임계값 (비교 실험용)
├── data/
│   ├── scene_library/          # 생성된 씬 JSON (20개 기본 포함)
│   ├── search_logs/            # AFS 탐색 결과 JSON
│   └── test_results/           # 개별 테스트 결과
├── reports/                    # 생성된 보고서 (CSV / Markdown)
├── tests/                      # P1~P10 완료 기준 검증 스크립트
├── app.py                      # Streamlit 대시보드
└── pyproject.toml
```

---

## 판정 기준

Physical Oracle은 6종 안전 마진을 계산하여 최저값 기준으로 판정한다.

| 마진 | 설명 |
|---|---|
| `reachability` | 목표 객체가 로봇 가동 범위 안에 있는가 |
| `collision_clearance` | 경로 상 최소 충돌 여유 거리 |
| `grasp_stability` | 파지 안정성 (마찰 타원 기반) |
| `place_accuracy` | 놓기 위치 정확도 |
| `path_clearance` | 전체 경로의 장애물 여유 |
| `perception` | 인식 신뢰도 (가시성 / 피사체 비율) |

| 판정 | 조건 |
|---|---|
| `BLOCKED` | 인간 영역 침범 (안전 정지) |
| `FAIL` | 마진 < `fail_threshold` |
| `WARN` | 마진 < `warn_threshold` |
| `PASS` | 전 마진 안전 범위 |

---

## 비교 실험 결과 (P9, seed=42, 5라운드 × 10테스트)

| 방법 | FDR (%) | 고유 실패 유형 |
|---|---|---|
| Active (warm) | **80%** | 4종 |
| Random | 74% | 2종 |

warm-start Active Search가 Random 대비 실패 발견률 +6%p, 실패 다양성 2배.
