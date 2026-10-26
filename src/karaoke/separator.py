import sys
import subprocess
from pathlib import Path
from typing import Tuple, Optional
import torch
from karaoke.cancel_manager import (
    check_cancelled,
    is_cancelled,
    register_process,
    unregister_process,
    GenerationCancelledError,
)

DEMUCS_MODELS = [
    "htdemucs",       # Default fast & clean Hybrid Transformer Demucs
    "htdemucs_ft",    # 4x fine-tuned ensemble (highest separation quality)
    "hdemucs_mmi",    # Hybrid Demucs MMI
    "mdx_extra",      # MDX-Net extra quality
]


def get_optimal_device() -> str:
    """Returns 'mps' if Apple Silicon GPU is available, else 'cpu'."""
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    return "cpu"


def separate_stems(
    audio_path: Path,
    output_dir: Path,
    model_name: str = "htdemucs",
    device: Optional[str] = None,
    force: bool = False,
) -> Tuple[Path, Path]:
    """
    Separates vocals from accompaniment using Demucs.
    Caches output so repeated runs on the same song are instant.
    Returns: (vocals_path, no_vocals_path)
    """
    if device is None:
        device = get_optimal_device()

    output_dir.mkdir(parents=True, exist_ok=True)
    track_name = audio_path.stem
    target_dir = output_dir / model_name / track_name

    vocals_path = target_dir / "vocals.wav"
    no_vocals_path = target_dir / "no_vocals.wav"

    if not force and vocals_path.exists() and no_vocals_path.exists():
        print(f"[Karaoke] Found cached Demucs stems ({model_name}):\n  Vocals: {vocals_path}\n  Instrumental: {no_vocals_path}")
        return vocals_path, no_vocals_path

    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", model_name,
        "--two-stems", "vocals",
        "-d", device,
        "-o", str(output_dir),
        str(audio_path)
    ]
    # For fine-tuned model ensemble on Apple Silicon, use 1 shift to keep speed high and prevent OOM
    if "ft" in model_name:
        cmd.extend(["--shifts", "1"])

    check_cancelled()
    print(f"[Karaoke] Running Demucs ({model_name}) stem separation on {device}...")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        register_process(proc)
        try:
            for line in proc.stdout:
                check_cancelled()
                line_str = line.strip()
                if line_str:
                    print(f"[Demucs] {line_str}")
            proc.wait()
        finally:
            unregister_process(proc)

        check_cancelled()
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)
    except GenerationCancelledError:
        raise
    except Exception as e:
        check_cancelled()
        if device == "mps":
            print(f"[Karaoke] Warning: MPS execution failed ({e}), falling back to CPU (4 threads)...")
            cmd_cpu = [c for c in cmd]
            cmd_cpu[cmd_cpu.index("-d") + 1] = "cpu"
            cmd_cpu.extend(["-j", "4"])
            proc = subprocess.Popen(cmd_cpu, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            register_process(proc)
            try:
                for line in proc.stdout:
                    check_cancelled()
                    line_str = line.strip()
                    if line_str:
                        print(f"[Demucs-CPU] {line_str}")
                proc.wait()
            finally:
                unregister_process(proc)

            check_cancelled()
            if proc.returncode != 0:
                raise RuntimeError(f"Demucs CPU execution also failed with returncode {proc.returncode}")
        else:
            raise e

    if not vocals_path.exists() or not no_vocals_path.exists():
        raise FileNotFoundError(
            f"Expected Demucs output files not found in {target_dir}. "
            f"Found: {list(target_dir.glob('*')) if target_dir.exists() else 'dir does not exist'}"
        )

    print(f"[Karaoke] Separation complete:\n  Vocals: {vocals_path}\n  Instrumental: {no_vocals_path}")
    return vocals_path, no_vocals_path

