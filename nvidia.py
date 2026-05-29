"""
NVIDIA GPU hardware configuration and probing.

AV1_CAPABLE is determined at import time by running a real FFmpeg dummy
transcode test. Set OVERRIDE_AV1_CAPABLE to True/False to skip probing.
"""

import probe

# ---------------------------------------------------------------------------
# AV1 capability detection
# ---------------------------------------------------------------------------

OVERRIDE_AV1_CAPABLE = None  # Set to True or False to override auto-detection

if OVERRIDE_AV1_CAPABLE is not None:
    AV1_CAPABLE = OVERRIDE_AV1_CAPABLE
else:
    AV1_CAPABLE = probe.check_vendor_av1_capable("NVIDIA")

# Cached GPU availability (probed once at import time)
GPU_AVAILABLE = probe.check_vendor_gpu_available("NVIDIA")

# ---------------------------------------------------------------------------
# Quality constants
# ---------------------------------------------------------------------------

QUALITY_PROPRIETARY_AV1 = 26
QUALITY_HEVC = 25
QUALITY_H264 = 21

NVIDIA_ACCEL_METHODS = ["NVENC"]

NVIDIA_HARDWARE_REGISTRY = {
    "NVENC": {
        "dri_device": None,
        "hwaccel": "cuda",
        "preset": "p7",
        "codecs": {
            "AV1": {"codec": "av1_nvenc", "quality": QUALITY_PROPRIETARY_AV1, "max_jobs": 1},
            "HEVC": {"codec": "hevc_nvenc", "quality": QUALITY_HEVC, "max_jobs": 3},
            "H264": {"codec": "h264_nvenc", "quality": QUALITY_H264, "max_jobs": 3},
        },
    },
}


# ---------------------------------------------------------------------------
# Probe functions
# ---------------------------------------------------------------------------


def check_gpu_availability() -> bool:
    """Check if an NVIDIA GPU with working NVENC encoder is available."""
    return probe.check_vendor_gpu_available("NVIDIA")


def resolve_nvidia_config(codec_mode: str) -> dict:
    method_info = NVIDIA_HARDWARE_REGISTRY["NVENC"]
    codec_info = method_info.get("codecs", {}).get(codec_mode, {})
    return {
        "dri_device": method_info.get("dri_device"),
        "hwaccel": method_info.get("hwaccel", "cuda"),
        "preset": method_info.get("preset", "default"),
        "quality": codec_info.get("quality", QUALITY_HEVC),
        "codec": codec_info.get("codec", "h264_nvenc"),
        "max_jobs": codec_info.get("max_jobs", 2),
    }
