"""
Hardware detection and profiling module for AI Karaoke Studio.
Accurately detects GPU (NVIDIA CUDA, Apple Silicon MPS), VRAM, CPU cores,
system RAM, and generates optimal AI model recommendations.
"""

import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import torch


@dataclass
class HardwareProfile:
    platform: str
    os_name: str
    architecture: str
    cpu_name: str
    cpu_cores: int
    ram_gb: float
    gpu_type: str  # "cuda", "mps", "cpu"
    gpu_name: str
    vram_gb: float
    cuda_available: bool
    cuda_version: Optional[str]
    cuda_compute_capability: Optional[str]
    mps_available: bool
    tier: str  # "ultra", "high", "medium", "low"
    recommended_whisper: str
    recommended_demucs: str
    allow_fp16: bool
    status_summary: str


def _get_system_ram_gb() -> float:
    """Gets total system RAM in gigabytes across Windows, macOS, and Linux without extra dependencies."""
    try:
        if sys.platform == "win32":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024 ** 3), 1)

        elif sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return round(int(out) / (1024 ** 3), 1)

        else:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 1)
    except Exception:
        pass
    return 8.0  # Safe fallback estimate


def _get_cpu_name() -> str:
    """Gets human-readable CPU model name."""
    try:
        if sys.platform == "darwin":
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        elif sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(val).strip()
        else:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "Unknown CPU"


def get_hardware_profile() -> HardwareProfile:
    """
    Detects user hardware, evaluates capabilities, and computes recommended model configuration.
    """
    ram_gb = _get_system_ram_gb()
    cpu_cores = os.cpu_count() or 4
    cpu_name = _get_cpu_name()

    cuda_available = torch.cuda.is_available()
    mps_available = hasattr(torch.backends, "mps") and torch.backends.mps.is_available() and torch.backends.mps.is_built()

    gpu_type = "cpu"
    gpu_name = "CPU Only"
    vram_gb = 0.0
    cuda_version = None
    cuda_compute_capability = None

    if cuda_available:
        gpu_type = "cuda"
        gpu_name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_gb = round(props.total_memory / (1024 ** 3), 1)
        cuda_version = torch.version.cuda or "unknown"
        cuda_compute_capability = f"{props.major}.{props.minor}"
    elif mps_available:
        gpu_type = "mps"
        gpu_name = f"Apple Silicon ({cpu_name})"
        # On Apple Silicon, unified memory is shared between CPU and GPU
        vram_gb = ram_gb

    # Determine hardware tier and recommendations
    if gpu_type == "cuda":
        allow_fp16 = True
        if vram_gb >= 8.0:
            tier = "ultra"
            recommended_whisper = "large-v3-turbo"
            recommended_demucs = "htdemucs_ft"
            status_summary = f"NVIDIA {gpu_name} ({vram_gb} GB VRAM) — Максимальная производительность CUDA"
        elif vram_gb >= 5.5:
            tier = "high"
            recommended_whisper = "large-v3-turbo"
            recommended_demucs = "htdemucs"
            status_summary = f"NVIDIA {gpu_name} ({vram_gb} GB VRAM) — Высокая производительность CUDA"
        elif vram_gb >= 3.5:
            tier = "medium"
            recommended_whisper = "large-v3-turbo"
            recommended_demucs = "htdemucs"
            status_summary = f"NVIDIA {gpu_name} ({vram_gb} GB VRAM) — Базовый режим CUDA"
        else:
            tier = "low"
            recommended_whisper = "small"
            recommended_demucs = "htdemucs"
            status_summary = f"NVIDIA {gpu_name} ({vram_gb} GB VRAM) — Ограниченная VRAM (рекомендуется модель small)"

    elif gpu_type == "mps":
        allow_fp16 = True
        if ram_gb >= 16.0:
            tier = "ultra"
            recommended_whisper = "large-v3-turbo"
            recommended_demucs = "htdemucs_ft"
            status_summary = f"Apple Silicon ({ram_gb} GB Unified Memory) — Высокая производительность Metal"
        else:
            tier = "high"
            recommended_whisper = "large-v3-turbo"
            recommended_demucs = "htdemucs"
            status_summary = f"Apple Silicon ({ram_gb} GB Unified Memory) — Оптимальный режим Metal"

    else:
        allow_fp16 = False
        if ram_gb >= 16.0 and cpu_cores >= 8:
            tier = "medium"
            recommended_whisper = "small"
            recommended_demucs = "htdemucs"
            status_summary = f"CPU ({cpu_cores} ядер, {ram_gb} GB RAM) — Ускорение GPU не обнаружено"
        else:
            tier = "low"
            recommended_whisper = "small"
            recommended_demucs = "htdemucs"
            status_summary = f"CPU ({cpu_cores} ядер, {ram_gb} GB RAM) — Рекомендуются облегченные модели"

    return HardwareProfile(
        platform=sys.platform,
        os_name=f"{platform.system()} {platform.release()}",
        architecture=platform.machine(),
        cpu_name=cpu_name,
        cpu_cores=cpu_cores,
        ram_gb=ram_gb,
        gpu_type=gpu_type,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        cuda_available=cuda_available,
        cuda_version=cuda_version,
        cuda_compute_capability=cuda_compute_capability,
        mps_available=mps_available,
        tier=tier,
        recommended_whisper=recommended_whisper,
        recommended_demucs=recommended_demucs,
        allow_fp16=allow_fp16,
        status_summary=status_summary,
    )


def get_hardware_profile_dict() -> Dict[str, Any]:
    """Returns hardware profile as serializable dictionary."""
    return asdict(get_hardware_profile())
