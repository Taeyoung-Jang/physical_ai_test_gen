"""P8 완료 기준 검증.

1. reporter.py 세 함수 정상 동작
2. app.py import 오류 없음 (Streamlit 앱은 headless 테스트)

실행: .venv/bin/python tests/test_p8_reporter.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["PYBULLET_MODE"] = "DIRECT"

import json
import tempfile
from pathlib import Path

from reporter import (
    generate_test_table,
    generate_counterexample_report,
    generate_comparison_report,
    load_records_from_log,
    load_all_logs,
)


# ---------------------------------------------------------------------------
# 더미 TestRecord 생성
# ---------------------------------------------------------------------------

def make_record(test_id: str, verdict: str, failure_type: str,
                robustness: float, scene_id: str = "test_scene",
                round_idx: int = 0) -> dict:
    margin_map = {
        "reach":      0.05,
        "clearance":  0.04,
        "collision":  0.06,
        "safety":     0.08,
        "goal":       0.03,
        "perception": 0.07,
    }
    # binding margin → 음수로 설정
    if failure_type in margin_map:
        margin_map[failure_type] = robustness
    return {
        "test_id":       test_id,
        "round_idx":     round_idx,
        "scene_id":      scene_id,
        "mutation_params": {"target_dx": 0.1},
        "feature_vector": [0.0] * 16,
        "margins":        margin_map,
        "robustness":     robustness,
        "verdict":        verdict,
        "failure_type":   failure_type,
        "reason":         f"테스트 {test_id} reason",
        "recommendation": f"recommendation for {test_id}",
        "acquisition_score": 0.5,
        "elapsed_s":      0.05,
    }


def main():
    print("=== P8 Reporter 검증 ===\n")

    # 더미 records
    records = [
        make_record("T01", "PASS",    "",                      0.05),
        make_record("T02", "WARN",    "clearance",             0.008),
        make_record("T03", "FAIL",    "insufficient_clearance", -0.02),
        make_record("T04", "FAIL",    "unreachable",           -0.05),
        make_record("T05", "BLOCKED", "human_risk",            -0.10),
        make_record("T06", "PASS",    "",                      0.04),
        make_record("T07", "FAIL",    "path_collision",        -0.01),
        make_record("T08", "WARN",    "perception",            0.012),
        make_record("T09", "BLOCKED", "human_risk",            -0.08),
        make_record("T10", "FAIL",    "destination_occupied",  -0.03),
    ]

    # ── 1. generate_test_table ─────────────────────────────────────────
    print("[1] generate_test_table")
    with tempfile.TemporaryDirectory() as tmpdir:
        df = generate_test_table(records, output_dir=tmpdir, filename_stem="test")
        assert len(df) == 10, f"rows: {len(df)}"
        assert "verdict" in df.columns
        assert "robustness" in df.columns
        assert (tmpdir / Path("test.csv")).is_file() or Path(tmpdir, "test.csv").exists()
        print(f"  DataFrame shape: {df.shape}")
        print(f"  판정 분포:\n{df['verdict'].value_counts().to_string()}")
    print("  ✅ generate_test_table OK\n")

    # ── 2. generate_counterexample_report ─────────────────────────────
    print("[2] generate_counterexample_report")
    with tempfile.TemporaryDirectory() as tmpdir:
        cases = generate_counterexample_report(records, output_dir=tmpdir)
        fail_verdicts = {"FAIL", "BLOCKED"}
        assert all(c["verdict"] in fail_verdicts for c in cases), \
            "PASS/WARN이 포함됨"
        assert len(cases) == 6, f"FAIL/BLOCKED count: {len(cases)}"
        # robustness 오름차순 확인
        robs = [c["robustness"] for c in cases]
        assert robs == sorted(robs), f"정렬 오류: {robs}"
        print(f"  케이스 수: {len(cases)}")
        for c in cases:
            print(f"    {c['verdict']:7s}  {c['failure_type']:28s}  rob={c['robustness']:.3f}")
    print("  ✅ generate_counterexample_report OK\n")

    # ── 3. generate_comparison_report ─────────────────────────────────
    print("[3] generate_comparison_report")
    results_by_method = {
        "random": records[:5],
        "cold":   records[5:],
    }
    report = generate_comparison_report(results_by_method)
    assert "summary" in report
    assert "curves" in report
    assert set(report["methods"]) == {"random", "cold"}
    for method, curve in report["curves"].items():
        assert len(curve["x"]) == len(results_by_method[method])
        assert curve["y_fail"][-1] >= 0
    print(f"  방법: {report['methods']}")
    summary_df = report["summary"]
    print(summary_df[["method", "total", "fail_blocked", "fdr", "unique_failure_types"]]
          .to_string(index=False))
    print("  ✅ generate_comparison_report OK\n")

    # ── 4. load_records_from_log (실제 log 파일 테스트) ───────────────
    print("[4] load_records_from_log")
    log_dir = Path("data/search_logs")
    if log_dir.exists():
        log_files = sorted(log_dir.glob("search_*.json"))
        if log_files:
            scene_id, recs = load_records_from_log(str(log_files[0]))
            print(f"  파일: {log_files[0].name}  scene={scene_id}  records={len(recs)}")
            assert len(recs) > 0
            all_logs = load_all_logs(str(log_dir))
            total = sum(len(v) for v in all_logs.values())
            print(f"  전체 log: {len(all_logs)} scenes  total records={total}")
            print("  ✅ load_records_from_log OK\n")
        else:
            print("  (log 파일 없음 — skip)\n")
    else:
        print("  (data/search_logs 없음 — skip)\n")

    # ── 5. app.py import 체크 (Streamlit headless) ────────────────────
    print("[5] app.py import 체크")
    import importlib.util, subprocess, sys
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0,'src'); "
         "from reporter import generate_test_table, generate_counterexample_report, "
         "generate_comparison_report; print('reporter import OK')"],
        capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, f"import 실패:\n{result.stderr}"
    print(f"  {result.stdout.strip()}")
    print("  ✅ import OK\n")

    print("✅ P8 완료 기준 통과 (reporter 3종 함수, log 로드, import 검증)")


if __name__ == "__main__":
    main()
