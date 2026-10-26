import os
import subprocess
import sys
from pathlib import Path

import pytest

from karaoke.cancel_manager import reset_cancel, run_cancellable_command
from karaoke.render_progress import RenderProgress, RenderLimitError


def test_progress_reports_real_time_speed_size_and_eta(tmp_path):
    updates = []
    tracker = RenderProgress(10, tmp_path / "render.mp4", 10_000_000,
                             lambda message, fraction: updates.append((message, fraction)))
    for line in ["frame=150", "fps=60", "out_time_us=5000000", "speed=2.0x",
                 "total_size=1000000", "progress=continue"]:
        tracker.line(line)
    message, fraction = updates[-1]
    assert fraction == 0.5
    assert "00:05 / 00:10" in message
    assert "2.00×" in message and "осталось ≈ 00:02" in message
    assert "1.0 МБ" in message and "кадр 150" in message
    for line in ["out_time_us=10000000", "speed=N/A", "progress=end"]:
        tracker.line(line)
    assert updates[-1][1] == 0.99  # Publish 100% only after validating/renaming MP4.
    assert "Завершение MP4" in updates[-1][0]


def test_disk_budget_and_excess_duration_stop_runaway_output(tmp_path):
    output = tmp_path / "partial.mp4"
    tracker = RenderProgress(2, output, 100)
    output.write_bytes(b"x" * 100)
    with pytest.raises(RenderLimitError, match="бюджет"):
        tracker.tick()
    output.unlink()
    tracker.line("out_time_us=10000000")
    with pytest.raises(RenderLimitError, match="длительность"):
        tracker.line("progress=continue")


def test_stdout_progress_is_delivered_before_process_finishes(tmp_path):
    reset_cancel()
    marker = tmp_path / "finished"
    received = []

    def line(value):
        assert not marker.exists(), "Progress was buffered until process completion"
        received.append(value)

    run_cancellable_command([
        sys.executable, "-u", "-c",
        "import sys,time,pathlib; sys.stderr.write('x'*200000); "
        "print('progress=continue',flush=True); time.sleep(0.3); "
        "pathlib.Path(sys.argv[1]).touch()", str(marker),
    ], on_stdout_line=line)
    assert received == ["progress=continue"]
    assert marker.exists()


def test_error_log_is_bounded_and_preserves_tail():
    reset_cancel()
    with pytest.raises(subprocess.CalledProcessError) as caught:
        run_cancellable_command([sys.executable, "-c",
                                 "import sys; sys.stderr.write('x'*200000+'last error'); sys.exit(7)"])
    assert caught.value.returncode == 7
    assert len(caught.value.stderr) <= 65536
    assert caught.value.stderr.endswith(b"last error")


def test_guard_failure_reaps_even_a_silent_child(tmp_path):
    reset_cancel()
    marker = tmp_path / "pid"

    def guard():
        if marker.exists() and marker.read_text():
            raise RenderLimitError("test guard")

    with pytest.raises(RenderLimitError):
        run_cancellable_command([
            sys.executable, "-c",
            "import os,time,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)",
            str(marker),
        ], on_tick=guard)
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
