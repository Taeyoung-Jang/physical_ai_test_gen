# LAM-Guided 3D Failure Case Generator v2 — 실행 가이드

scene2test v2 확장의 모든 기능을 실행하는 단계별 명령어입니다. 모든 명령은 `scene2test/` 디렉터리에서 실행합니다.

⚠️ **먼저 읽기:** [LAM_GUIDED_WORKFLOW.md](LAM_GUIDED_WORKFLOW.md) — 전체 파이프라인의 4단계(관찰→취약성→생성→정제)와 각 단계가 무엇을 하는지 설명합니다. 여기는 **명령어만** 모았습니다.

---

## 0. 준비 (1회만)

```bash
cd scene2test

# 기본 의존성 설치
uv sync

# 씬 라이브러리 생성 (없으면)
uv run python src/scene_generator.py --n 20 --output-dir data/scene_library --seed 0
```

**선택 설치:**
```bash
# OpenVLA 지원 (GPU 또는 Apple Silicon MPS)
uv sync --extra vla

# 3D 객체 생성 지원 (Shap-E)
uv sync --extra gen3d
```

---

## 1. LAM-Guided Failure 루프 (핵심)

### 1.1 정상 정책 베이스라인 (Demo 1)
```bash
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model rule \
    --rounds 4 \
    --enabled
```
**출력:** 정상 경로만 실행, wrong_object_grounding 없음 → 경계값 없음

### 1.2 취약한 정책으로 Guided 탐색: 핵심 파이프라인 (Demo 2~4)

**❗ 이 명령이 LAM-Guided의 4단계 전체를 실행합니다:**

```
라운드 1~4 반복:
  1️⃣ OBSERVE: 정책 행동 + RolloutTrace 기록
  2️⃣ PROFILE: 취약성 진단 (정책이 어떤 유형의 실패를 보이는가)
  3️⃣ GENERATE: Guided 실패 케이스 60개 생성 → 검증 → top-8 선택
  4️⃣ EVALUATE: 각 케이스에서 정책 실행 → 실패 발견 시 저장
  
라운드 종료 후:
  4️⃣ REFINE: Boundary Refinement (PASS↔FAIL 임계값 binary search)
```

```bash
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model mini \
    --rounds 4 \
    --batch-size 8 \
    --enabled
```

**산출물:**
- `data/lam_guided_logs/round_*.json` — 각 라운드 상세 (선택/점수/실패)
- `data/counterexamples.jsonl` — **발견한 모든 정책 실패** (누적)
- `reports/vulnerability_summary.md` — **정책 약점 진단** ("distractor 혼동" 등)
- `reports/counterexample_table.csv` — 실패 요약 표 (family/verdict/score)
- `reports/boundary_report.md` — **정량적 경계값** ("14cm 이내면 안 됨" 등)

**해석:** 이 4개 report가 "정책이 언제 어떻게 실패하는가"를 완전히 설명합니다.

---

## 2. Counterexample 시각화 (GIF)

```bash
PYBULLET_MODE=DIRECT uv run python tools/animate_lam_failure.py --max 4
```
**출력:** `data/lam_anim/LAMFC_*.gif`
- 각 실패 케이스를 애니메이션으로 렌더링
- wrong-grounding: TARGET(녹색 원, 테이블 고정) vs PICKED(빨강 원, 그리퍼 추적)
- 명확하게 어떤 객체를 잘못 집었는지 표시

**보기:**
```bash
open data/lam_anim/LAMFC_wrong_object_grounding_*.gif
```

---

## 3. Closed-Loop VLA 통합

### 3.1 Stub 정책 (GPU 없이 작동, VLA 관찰)
```bash
PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
    --scene data/scene_library/scene_00001.json \
    --policy stub \
    --insert distractor_red_can \
    --gif
```
**출력:**
- 로봇이 distractor를 집도록 하는 시각화
- `reports/vla_observation_*.png` — 각 스텝 RGB 관찰

### 3.2 실제 OpenVLA (uv sync --extra vla 후)
```bash
# ⚠️ OpenVLA는 Apple Silicon(MPS) 미지원 → 자동 CPU 폴백
PYBULLET_MODE=DIRECT uv run python tools/run_vla_rollout.py \
    --scene data/scene_library/scene_00001.json \
    --policy openvla
```
**주의:** 
- 최초 실행 시 모델 다운로드 ~1.3GB (한 번만)
- M4 Pro: CPU fp32 (느림, ~1-3초/스텝)
- 정책이 없으면 stub으로 자동 폴백
- **왜 CPU인가?** OpenVLA의 attention 계산이 MPS에서 오류 발생 → 안정성을 위해 CPU 강제

---

## 4. 3D 객체 생성

### 4.1 실제 생성 (uv sync --extra gen3d 후)
```bash
PYBULLET_MODE=DIRECT uv run python tools/gen3d_asset.py \
    --prompt "a red soda can" \
    --asset-id gen3d_red_can \
    --family semantic_distractor \
    --tags red,can \
    --steps 24
```
**출력:**
- `data/generated_assets/meshes/gen3d_red_can/model.obj` — 생성된 메쉬
- `data/generated_assets/index.json` — 자동 등록
- `reports/gen3d_asset.png` — 씬에 배치한 스냅샷

**성능:** M4 Pro CPU, 16~24스텝 → 20~30초

### 4.2 모델 없이 (폴백 확인)
```bash
PYBULLET_MODE=DIRECT uv run python tools/gen3d_asset.py \
    --no-model \
    --family semantic_distractor
```
**결과:** procedural default 객체 반환 (distractor_red_can)

---

## 5. 테스트 (검증)

### 5.1 개별 모듈 테스트
```bash
# LAM-Guided 루프 (P11) — 10 테스트
PYBULLET_MODE=DIRECT uv run python tests/test_p11_lam_guided.py

# Closed-loop VLA (P12) — 5 테스트
PYBULLET_MODE=DIRECT uv run python tests/test_p12_vla_closed_loop.py

# 3D 생성 + 폴백 (P13) — 5 테스트
PYBULLET_MODE=DIRECT uv run python tests/test_p13_asset_gen.py
```

### 5.2 pytest 실행
```bash
PYBULLET_MODE=DIRECT uv run pytest tests/test_p11_lam_guided.py -v
PYBULLET_MODE=DIRECT uv run pytest tests/test_p12_vla_closed_loop.py -v
PYBULLET_MODE=DIRECT uv run pytest tests/test_p13_asset_gen.py -v
```

### 5.3 전체 게이트 (회귀 + 신규)
```bash
PYBULLET_MODE=DIRECT uv run python tests/test_p11_lam_guided.py 2>&1 | grep -E "✅|❌"
PYBULLET_MODE=DIRECT uv run python tests/test_p12_vla_closed_loop.py 2>&1 | grep -E "✅|❌"
PYBULLET_MODE=DIRECT uv run python tests/test_p13_asset_gen.py 2>&1 | grep -E "✅|❌"

# 기존 P5 (oracle) 회귀 확인
PYBULLET_MODE=DIRECT uv run python tests/test_p5_physical_oracle.py 2>&1 | grep -E "✅|❌"
```

---

## 6. 대시보드 (선택)

```bash
# Streamlit 웹 인터페이스 (http://localhost:8501)
uv run streamlit run app.py
```

---

## 전체 워크플로우 예시

**완전한 사이클 (한 번에 실행하기):**

```bash
cd scene2test

# [준비] 씬 라이브러리 있는지 확인
ls data/scene_library/scene_*.json > /dev/null || \
  uv run python src/scene_generator.py --n 20 --output-dir data/scene_library --seed 0

# [Step 1] LAM-Guided 루프 (mini 정책, 취약점 탐색)
echo "=== LAM-Guided Failure Loop (mini) ===" && \
PYBULLET_MODE=DIRECT uv run python src/lam_guided/lam_guided_loop.py \
    --scene data/scene_library/scene_00001.json \
    --action-model mini --rounds 4 --batch-size 8 --enabled

# [Step 2] 실패 케이스 시각화
echo "=== Animating Failures ===" && \
PYBULLET_MODE=DIRECT uv run python tools/animate_lam_failure.py --max 4

# [Step 3] 테스트 (회귀 + 신규)
echo "=== Running Tests ===" && \
PYBULLET_MODE=DIRECT uv run python tests/test_p11_lam_guided.py 2>&1 | tail -3

echo "✓ 완료. 산출물:"
echo "  - logs: data/lam_guided_logs/"
echo "  - gifs: data/lam_anim/"
echo "  - reports: reports/{vulnerability_summary.md, counterexample_table.csv, boundary_report.md}"
```

---

## 주요 산출물 위치

| 항목 | 경로 | 설명 |
|---|---|---|
| **로그** | `data/lam_guided_logs/*.json` | 각 라운드 상세 로그 |
| **실패 케이스** | `data/counterexamples.jsonl` | 발견한 모든 실패 (JSONL) |
| **취약성 분석** | `reports/vulnerability_summary.md` | 정책 취약점 프로필 |
| **실패 표** | `reports/counterexample_table.csv` | 실패 요약 (verdict, family, score) |
| **경계값** | `reports/boundary_report.md` | PASS/FAIL 임계값 (family별) |
| **GIF** | `data/lam_anim/LAMFC_*.gif` | 실패 케이스 애니메이션 |
| **VLA 관찰** | `reports/vla_observation_*.png` | 폐루프 RGB 시퀀스 |
| **3D 메쉬** | `data/generated_assets/meshes/*/model.obj` | 생성된 3D 객체 |
| **Asset 인덱스** | `data/generated_assets/index.json` | 등록된 객체 카탈로그 |

---

## 성능 참고 (M4 Pro 기준)

| 작업 | 소요 시간 |
|---|---|
| LAM-Guided 루프 (4 라운드, mini) | ~2–3분 |
| GIF 렌더링 (4개) | ~1분 |
| VLA rollout (stub) | ~10초 |
| 3D 생성 (24스텝) | ~30초 (CPU, 최초 모델 다운로드 제외) |
| 전체 테스트 (P11/P12/P13) | ~30초 |

---

## 트러블슈팅

**문제: "ShapEGenerator available()=False"**
```bash
# 해결: gen3d 의존성 설치
uv sync --extra gen3d
```

**문제: "OpenVLAPolicy 구성 실패"**
```bash
# 해결: vla 의존성 확인
uv sync --extra vla
# 또는 stub 정책 사용
tools/run_vla_rollout.py --policy stub
```

**문제: GIF 프레임 없음**
```bash
# 해결: 실패 케이스가 있는지 확인
ls data/lam_anim/ | wc -l
# 0이면 루프 재실행 또는 다른 씬 사용
```

---

## 다음 단계 (선택)

- **비교 실험 (A/B/C)**: 기존 Active Failure vs 랜덤 distractor vs LAM-Guided의 성능 비교
- **더 많은 family 추가**: destination_occupied, grasp_difficult_object
- **VLA 루프 통합**: 전체 LAM-Guided 루프를 OpenVLA와 연결
- **대시보드 완성**: Streamlit app.py 확장

---

**마지막 검증: 모든 테스트 패스**
```bash
PYBULLET_MODE=DIRECT uv run python tests/test_p11_lam_guided.py && \
PYBULLET_MODE=DIRECT uv run python tests/test_p12_vla_closed_loop.py && \
PYBULLET_MODE=DIRECT uv run python tests/test_p13_asset_gen.py && \
echo "✅ 모든 테스트 통과"
```
