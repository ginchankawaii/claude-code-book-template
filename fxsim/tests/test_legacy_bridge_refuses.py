"""scripts/run_bridge.py is the pre-AI trend brain. It speaks none of the bridge
protocol (no SEQ, EXP or SL) and takes no lock, so beside a live AI brain it is a
second writer the EA executes at a different size and stop. Round-6: it must
refuse to start while the AI brain's lock is fresh — a forgotten Task Scheduler
job is the realistic trigger."""
import subprocess, sys, time
from pathlib import Path

FXSIM = Path(__file__).resolve().parents[1]


def _run(tmp_path, extra):
    env = {"MT5_COMMON_FILES": str(tmp_path), "FXSIM_DB": str(tmp_path / "t.db"),
           "PATH": "/usr/bin:/bin", "PYTHONPATH": str(FXSIM)}
    return subprocess.run([sys.executable, "-m", "scripts.run_bridge", "--once", *extra],
                          cwd=str(FXSIM), env=env, capture_output=True, text=True, timeout=120)


def test_refuses_beside_a_live_ai_brain(tmp_path):
    (tmp_path / "steady_brain.lock").write_text(f"1 {int(time.time())} 600 fx-container\n")
    r = _run(tmp_path, [])
    assert r.returncode == 2 and "REFUSING" in r.stdout
    assert not (tmp_path / "steady_signal.txt").exists()


def test_dry_run_is_still_allowed_for_inspection(tmp_path):
    (tmp_path / "steady_brain.lock").write_text(f"1 {int(time.time())} 600 fx-container\n")
    r = _run(tmp_path, ["--dry"])
    assert "REFUSING" not in r.stdout
    assert not (tmp_path / "steady_signal.txt").exists()
