"""app.py — Scene2Test Streamlit 대시보드.

4-패널 레이아웃:
  ┌─────────────────────┬─────────────────────┐
  │  Scene Graph View   │  Active Search       │
  │  3D scatter plotly  │  Discovery Curve     │
  ├─────────────────────┼─────────────────────┤
  │  PyBullet Snapshots │  Test Result Table   │
  │  FAIL/BLOCKED 슬라이더 │  + Counterexample  │
  └─────────────────────┴─────────────────────┘

실행:
  streamlit run app.py
  또는
  .venv/bin/streamlit run app.py
"""
import sys
import os

# src 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
os.environ.setdefault("PYBULLET_MODE", "DIRECT")

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from scene_graph import SceneGraph, Role
from reporter import (
    generate_test_table,
    generate_counterexample_report,
    generate_comparison_report,
    load_records_from_log,
    VERDICT_COLORS,
    VERDICT_ORDER,
)


# ---------------------------------------------------------------------------
# 페이지 설정
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Scene2Test",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Scene2Test — Physical AI 행동 회귀 테스트 대시보드")
st.markdown("3D Scene Graph 기반 Active Failure Search 결과 시각화")


# ---------------------------------------------------------------------------
# 사이드바: 데이터 소스 선택
# ---------------------------------------------------------------------------

st.sidebar.header("데이터 소스")
log_dir = st.sidebar.text_input("Search Log 디렉터리", value="data/search_logs")
scene_lib_dir = st.sidebar.text_input("Scene 라이브러리 디렉터리", value="data/scene_library")

# 사용 가능한 log 파일 목록
log_files = sorted(Path(log_dir).glob("search_*.json")) if Path(log_dir).exists() else []
log_names = [f.name for f in log_files]

st.sidebar.markdown(f"**{len(log_files)}개** search log 발견")

selected_logs = st.sidebar.multiselect(
    "분석할 log 파일 선택",
    options=log_names,
    default=log_names[:3] if log_names else [],
)


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def load_records(log_dir: str, selected_logs: list[str]) -> dict[str, list[dict]]:
    """선택된 log 파일에서 scene별 records 수집."""
    by_log: dict[str, list[dict]] = {}
    for name in selected_logs:
        path = Path(log_dir) / name
        if path.exists():
            with open(path, encoding="utf-8") as f:
                log = json.load(f)
            scene_id = log.get("scene_id", "unknown")
            mode = log.get("config", {}).get("mode", "cold")
            key = f"{scene_id} [{mode}]"
            by_log[key] = log.get("records", [])
    return by_log


@st.cache_data(ttl=60)
def load_scenes(scene_lib_dir: str) -> list[dict]:
    """Scene 라이브러리에서 SceneGraph 정보 로드."""
    scenes = []
    lib_path = Path(scene_lib_dir)
    if lib_path.exists():
        for f in sorted(lib_path.glob("*.json")):
            try:
                sg = SceneGraph.load(str(f))
                scenes.append({
                    "scene_id": sg.scene_id,
                    "n_objects": len(sg.objects),
                    "n_obstacles": len(sg.obstacles()),
                    "n_human_zones": len(sg.human_zones()),
                    "objects": [{"id": o.object_id, "role": o.role, "pos": o.position}
                                for o in sg.objects],
                    "scene_graph": sg,
                })
            except Exception:
                pass
    return scenes


if not selected_logs:
    st.info("사이드바에서 분석할 search log 파일을 선택하세요.")
    st.stop()

all_records_by_log = load_records(log_dir, selected_logs)

# 모든 records를 하나로 합침 (테이블/통계용)
all_records: list[dict] = []
for recs in all_records_by_log.values():
    all_records.extend(recs)

if not all_records:
    st.warning("선택된 log 파일에 records가 없습니다.")
    st.stop()

df = generate_test_table(all_records)


# ---------------------------------------------------------------------------
# 패널 레이아웃
# ---------------------------------------------------------------------------

col_left, col_right = st.columns(2)


# ── 패널 1: Scene Graph View ───────────────────────────────────────────────
with col_left:
    st.subheader("Scene Graph View")

    scenes = load_scenes(scene_lib_dir)
    scene_ids_in_records = df["scene_id"].unique().tolist()

    # records에 있는 scene_id 중 첫 번째 선택
    selected_scene_id = st.selectbox(
        "Scene 선택",
        options=scene_ids_in_records,
        index=0,
    )

    # scene_library에서 해당 scene 찾기 (없으면 records에서 위치 추정)
    matched_scene = next(
        (s for s in scenes if s["scene_id"] == selected_scene_id), None
    )

    if matched_scene:
        sg: SceneGraph = matched_scene["scene_graph"]

        # 3D scatter
        role_colors = {
            Role.TARGET:      "#e74c3c",
            Role.OBSTACLE:    "#3498db",
            Role.DESTINATION: "#2ecc71",
            Role.HUMAN_ZONE:  "#f39c12",
            Role.DISTRACTOR:  "#95a5a6",
        }
        role_symbols = {
            Role.TARGET:      "circle",
            Role.OBSTACLE:    "square",
            Role.DESTINATION: "diamond",
            Role.HUMAN_ZONE:  "cross",
            Role.DISTRACTOR:  "x",
        }

        fig_scene = go.Figure()
        for obj in sg.objects:
            pos = obj.position
            sz = obj.size
            color = role_colors.get(obj.role, "#888")
            symbol = role_symbols.get(obj.role, "circle")
            fig_scene.add_trace(go.Scatter3d(
                x=[pos[0]], y=[pos[1]], z=[pos[2]],
                mode="markers+text",
                marker=dict(size=max(8, sz[0]*80), color=color, symbol=symbol, opacity=0.85),
                text=[f"{obj.object_id}<br>({obj.role})"],
                textposition="top center",
                name=f"{obj.object_id} ({obj.role})",
            ))

        # 로봇 base 위치
        fig_scene.add_trace(go.Scatter3d(
            x=[0], y=[0], z=[0],
            mode="markers+text",
            marker=dict(size=10, color="#2c3e50", symbol="diamond"),
            text=["Robot Base"],
            textposition="top center",
            name="Robot Base",
        ))

        fig_scene.update_layout(
            scene=dict(
                xaxis_title="X (m)", yaxis_title="Y (m)", zaxis_title="Z (m)",
                aspectmode="cube",
                xaxis=dict(range=[-0.1, 1.0]),
                yaxis=dict(range=[-0.5, 0.5]),
                zaxis=dict(range=[-0.05, 0.5]),
            ),
            margin=dict(l=0, r=0, t=30, b=0),
            height=380,
            showlegend=True,
            legend=dict(font=dict(size=10)),
        )
        st.plotly_chart(fig_scene, use_container_width=True)
        st.caption(f"객체 {len(sg.objects)}개 | 장애물 {len(sg.obstacles())}개 | "
                   f"human_zone {len(sg.human_zones())}개")
    else:
        st.info(f"Scene '{selected_scene_id}'이 라이브러리에 없습니다.\n"
                "data/scene_library/에 scene JSON 파일을 배치하세요.")
        st.caption(f"(Scene ID: {selected_scene_id})")


# ── 패널 2: Active Search — Failure Discovery Curve ───────────────────────
with col_right:
    st.subheader("Failure Discovery Curve")

    # method 그룹별 분리 (log key에 [mode] 포함됨)
    method_groups: dict[str, list[dict]] = {}
    for log_key, recs in all_records_by_log.items():
        method_groups[log_key] = recs

    report = generate_comparison_report(method_groups)

    fig_curve = go.Figure()
    palette = px.colors.qualitative.Plotly
    for i, (method, curve) in enumerate(report["curves"].items()):
        color = palette[i % len(palette)]
        fig_curve.add_trace(go.Scatter(
            x=curve["x"],
            y=curve["y_fail"],
            mode="lines+markers",
            name=f"{method} (FAIL)",
            line=dict(color=color, width=2),
            marker=dict(size=4),
        ))

    fig_curve.update_layout(
        xaxis_title="테스트 실행 수",
        yaxis_title="누적 FAIL/BLOCKED",
        height=380,
        margin=dict(l=0, r=0, t=30, b=40),
        legend=dict(font=dict(size=10)),
    )
    st.plotly_chart(fig_curve, use_container_width=True)

    # 요약 테이블
    summary_df = report["summary"][
        ["method", "total", "fail_blocked", "fdr", "unique_failure_types"]
    ].rename(columns={
        "method": "방법",
        "total": "총 테스트",
        "fail_blocked": "FAIL+BLOCKED",
        "fdr": "FDR",
        "unique_failure_types": "고유 실패 유형",
    })
    st.dataframe(summary_df, use_container_width=True, hide_index=True)


# ── 패널 3 + 4: 하단 ───────────────────────────────────────────────────────
col_bl, col_br = st.columns(2)


# ── 패널 3: 판정 분포 + margin 히트맵 ────────────────────────────────────
with col_bl:
    st.subheader("판정 분포")

    verdict_counts = df["verdict"].value_counts().reindex(VERDICT_ORDER, fill_value=0)
    fig_pie = go.Figure(go.Pie(
        labels=verdict_counts.index.tolist(),
        values=verdict_counts.values.tolist(),
        marker=dict(colors=[VERDICT_COLORS.get(v, "#888") for v in verdict_counts.index]),
        hole=0.4,
        textinfo="label+percent+value",
    ))
    fig_pie.update_layout(height=280, margin=dict(l=0, r=0, t=20, b=0),
                          showlegend=False)
    st.plotly_chart(fig_pie, use_container_width=True)

    # Margin 분포 박스플롯
    margin_cols = ["m_reach", "m_clearance", "m_collision", "m_safety", "m_goal", "m_perception"]
    margin_labels = ["reach", "clearance", "collision", "safety", "goal", "perception"]
    fig_box = go.Figure()
    for col, label in zip(margin_cols, margin_labels):
        fig_box.add_trace(go.Box(
            y=df[col].values,
            name=label,
            marker_color="#3498db",
            boxmean=True,
        ))
    fig_box.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="fail boundary")
    fig_box.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=20, b=0),
        yaxis_title="Margin (m)",
        showlegend=False,
    )
    st.plotly_chart(fig_box, use_container_width=True)


# ── 패널 4: 테스트 결과 테이블 + Counterexample ────────────────────────────
with col_br:
    st.subheader("테스트 결과 테이블")

    verdict_filter = st.multiselect(
        "판정 필터",
        options=VERDICT_ORDER,
        default=VERDICT_ORDER,
    )
    df_filtered = df[df["verdict"].isin(verdict_filter)] if verdict_filter else df

    # 표시 컬럼 간소화
    display_cols = ["test_id", "round", "scene_id", "verdict",
                    "failure_type", "robustness", "reason"]
    st.dataframe(
        df_filtered[display_cols].style.map(
            lambda v: f"background-color: {VERDICT_COLORS.get(v, '')}22",
            subset=["verdict"],
        ),
        use_container_width=True,
        height=250,
        hide_index=True,
    )

    # Counterexample Report
    st.subheader("Counterexample 상세")
    cases = generate_counterexample_report(all_records)
    if not cases:
        st.success("FAIL / BLOCKED 케이스 없음")
    else:
        st.caption(f"총 {len(cases)}개 FAIL/BLOCKED 케이스 (robustness 오름차순)")
        for i, case in enumerate(cases[:5]):  # 상위 5개
            with st.expander(
                f"[{case['verdict']}] {case['test_id']} — "
                f"{case['failure_type']} (rob={case['robustness']:.4f})",
                expanded=(i == 0),
            ):
                st.markdown(f"**이유**: {case['reason']}")
                st.markdown(f"**권장 조치**: {case['recommendation']}")
                m = case["margins"]
                st.bar_chart(
                    pd.DataFrame({"margin": list(m.values())}, index=list(m.keys()))
                )


# ---------------------------------------------------------------------------
# 하단: 원클릭 시연 실행 (Run AFS)
# ---------------------------------------------------------------------------

st.divider()
st.subheader("원클릭 Active Failure Search 실행")
st.markdown("새 Scene에서 AFS를 바로 실행하고 결과를 위 대시보드에 반영합니다.")

run_col1, run_col2, run_col3 = st.columns(3)
with run_col1:
    run_seed = st.number_input("Scene Seed", value=200, step=1)
with run_col2:
    run_rounds = st.slider("라운드 수", 1, 10, 3)
with run_col3:
    run_mode = st.selectbox("탐색 모드", ["cold", "random"])

if st.button("AFS 실행", type="primary"):
    with st.spinner("AFS 실행 중..."):
        try:
            from scene_builder import connect, disconnect
            from scene_generator import generate_scene, load_scene_config, load_robot_config
            from physical_oracle import load_thresholds
            from active_failure_search import ActiveFailureSearch, SearchConfig

            connect()
            robot_cfg  = load_robot_config("config/robot_config.yaml")
            thresholds = load_thresholds("config/thresholds.yaml")
            scene_cfg  = load_scene_config("config/scene_gen_config.yaml")

            sg = generate_scene(seed=int(run_seed), scene_cfg=scene_cfg, robot_cfg=robot_cfg)
            if sg is None:
                st.error(f"Seed {run_seed}로 유효한 scene 생성 실패 — 다른 seed를 시도하세요.")
            else:
                cfg = SearchConfig(
                    num_rounds=run_rounds,
                    tests_per_round=10,
                    candidate_pool_size=400,
                    min_train_size=12,
                    mode=run_mode,
                    seed=int(run_seed),
                    log_dir=log_dir,
                )
                searcher = ActiveFailureSearch(sg, robot_cfg, thresholds, cfg)
                records = searcher.run()
                summary = searcher.summary()

                st.success(
                    f"완료! 총 {summary['total_tests']}회 실행 | "
                    f"FAIL/BLOCKED: {summary['fail'] + summary['blocked']} | "
                    f"고유 실패 유형: {summary['num_unique_failure_types']}"
                )
                st.json(summary)
                st.info("사이드바에서 새 log 파일을 선택하면 위 대시보드가 갱신됩니다.")

        except Exception as e:
            st.error(f"실행 실패: {e}")
            import traceback
            st.code(traceback.format_exc())
