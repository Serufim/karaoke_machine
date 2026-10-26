from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import soundfile as sf


def compute_waveform_peaks(wav_path: Path, num_bins: int = 480) -> Tuple[List[float], float]:
    """
    Computes a downsampled peak envelope (0.0 to 1.0) and duration for Canvas timeline visualization.
    Executes in ~10-20ms using fast NumPy array slicing.
    """
    if not wav_path.exists():
        return [0.0] * num_bins, 0.0

    data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    n_samples = len(data)
    duration = float(n_samples) / float(sr)
    if n_samples == 0:
        return [0.0] * num_bins, 0.0

    # Max across channels (mono envelope)
    mono = np.max(np.abs(data), axis=1)

    bin_size = max(1, n_samples // num_bins)
    peaks = []
    for i in range(num_bins):
        s_idx = i * bin_size
        e_idx = min(n_samples, s_idx + bin_size)
        if s_idx >= n_samples:
            peaks.append(0.0)
        else:
            p = float(np.max(mono[s_idx:e_idx]))
            peaks.append(round(min(1.0, p), 3))

    max_p = max(peaks) if peaks else 1.0
    if max_p > 0.05:
        peaks = [round(p / max_p, 3) for p in peaks]

    return peaks, round(duration, 2)


def detect_chorus_fx_intervals(
    inst_path: Path,
    vocals_path: Path,
    min_duration: float = 3.5
) -> List[Dict[str, Any]]:
    """
    Auto-detects energetic chorus / climax sections by analyzing vocal & instrumental energy peaks.
    Returns a list of FX intervals: [{"start": 24.3, "end": 32.1, "effect": "sparkles_pulse", "intensity": 0.85}]
    """
    if not inst_path.exists() or not vocals_path.exists():
        return []

    v_data, sr_v = sf.read(str(vocals_path), dtype="float32", always_2d=True)
    i_data, _ = sf.read(str(inst_path), dtype="float32", always_2d=True)
    min_len = min(len(v_data), len(i_data))
    if min_len == 0:
        return []

    # 100ms frames
    frame_sz = int(sr_v * 0.10)
    n_frames = min_len // frame_sz
    if n_frames < 20:
        return []

    v_rms = np.array([np.sqrt(np.mean(v_data[i * frame_sz:(i + 1) * frame_sz] ** 2)) for i in range(n_frames)])
    i_rms = np.array([np.sqrt(np.mean(i_data[i * frame_sz:(i + 1) * frame_sz] ** 2)) for i in range(n_frames)])
    combined = v_rms * 1.5 + i_rms

    thresh = float(np.percentile(combined, 72))
    active = combined >= thresh

    intervals = []
    in_block = False
    start_f = 0
    for idx, act in enumerate(active):
        if act and not in_block:
            in_block = True
            start_f = idx
        elif not act and in_block:
            in_block = False
            dur = (idx - start_f) * 0.10
            if dur >= min_duration:
                intervals.append({
                    "start": round(start_f * 0.10, 2),
                    "end": round(idx * 0.10, 2),
                    "effect": "sparkles_pulse",
                    "intensity": 0.85,
                })

    if in_block:
        dur = (n_frames - start_f) * 0.10
        if dur >= min_duration:
            intervals.append({
                "start": round(start_f * 0.10, 2),
                "end": round(n_frames * 0.10, 2),
                "effect": "sparkles_pulse",
                "intensity": 0.85,
            })

    # Merge intervals separated by less than 2.0s
    merged: List[Dict[str, Any]] = []
    for itv in intervals:
        if merged and itv["start"] - merged[-1]["end"] < 2.0:
            merged[-1]["end"] = itv["end"]
        else:
            merged.append(itv)

    return merged


def mix_guide_vocals(
    instrumental_path: Path,
    vocals_path: Path,
    output_path: Path,
    vocal_volume: float = 0.10,
    vocal_intervals: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """
    Mixes instrumental track (100%) with guide vocals, supporting dynamic vocal volume automation
    (backing vocals / chorus boosts) with smooth 50ms Hann window crossfade transitions.
    """
    base_vol = max(0.0, min(1.0, float(vocal_volume)))
    vocal_intervals = vocal_intervals or []

    inst_data, sr_inst = sf.read(str(instrumental_path), dtype="float32", always_2d=True)
    voc_data, sr_voc = sf.read(str(vocals_path), dtype="float32", always_2d=True)

    if sr_inst != sr_voc:
        raise ValueError(f"Sample rate mismatch between instrumental ({sr_inst}) and vocals ({sr_voc})")

    min_len = min(len(inst_data), len(voc_data))
    if min_len == 0:
        return instrumental_path

    # Construct dynamic vocal gain curve
    gain = np.full(min_len, base_vol, dtype=np.float32)

    has_custom_intervals = False
    for itv in vocal_intervals:
        s_sec = float(itv.get("start", 0.0))
        e_sec = float(itv.get("end", 0.0))
        vol = max(0.0, min(1.0, float(itv.get("volume", base_vol))))
        s_idx = max(0, min(min_len, int(s_sec * sr_inst)))
        e_idx = max(0, min(min_len, int(e_sec * sr_inst)))
        if e_idx > s_idx:
            gain[s_idx:e_idx] = vol
            has_custom_intervals = True

    # Apply 50ms Hann smoothing to prevent clicks on transitions
    if has_custom_intervals:
        smooth_len = int(sr_inst * 0.05)
        if smooth_len > 1:
            hann = np.hanning(smooth_len)
            hann /= np.sum(hann)
            # Smooth gain curve
            gain = np.convolve(gain, hann, mode="same")

    print(f"[Karaoke] Mixing backing track (Base vocal: {int(round(base_vol * 100))}%, Automation zones: {len(vocal_intervals)})...")
    mixed = inst_data[:min_len] + (voc_data[:min_len] * gain[:, None])

    # Soft limiter to prevent clipping
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.98:
        mixed = mixed * (0.98 / peak)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), mixed, sr_inst)
    print(f"[Karaoke] Mixed backing track saved to: {output_path}")
    return output_path


def ensure_full_guide_mix(
    instrumental_path: Path,
    vocals_path: Path,
    output_path: Path,
) -> Path:
    """
    Creates or reuses a 100% full-vocal guide mix (Instrumental + 100% Vocals)
    used as the second switchable audio stream in Dual-Audio MP4 files for KJs/DJs.
    """
    if not vocals_path.exists():
        return instrumental_path
    if output_path.exists() and output_path.stat().st_size > 1024:
        return output_path
    return mix_guide_vocals(
        instrumental_path=instrumental_path,
        vocals_path=vocals_path,
        output_path=output_path,
        vocal_volume=1.0,
        vocal_intervals=None,
    )

