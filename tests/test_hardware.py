from karaoke.hardware import get_hardware_profile, get_hardware_profile_dict


def test_hardware_profiling():
    prof = get_hardware_profile()
    assert prof.cpu_cores >= 1
    assert prof.ram_gb > 0
    assert prof.gpu_type in ("cuda", "mps", "cpu")
    assert prof.tier in ("ultra", "high", "medium", "low")
    assert prof.recommended_whisper in ("large-v3-turbo", "small", "base")
    assert prof.recommended_demucs in ("htdemucs", "htdemucs_ft")


def test_hardware_serializable():
    data = get_hardware_profile_dict()
    assert isinstance(data, dict)
    assert data["status_summary"] != ""
    assert "vram_gb" in data
