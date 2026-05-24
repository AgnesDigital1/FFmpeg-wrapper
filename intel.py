"""
Intel GPU hardware configuration and probing.

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
    AV1_CAPABLE = probe.check_vendor_av1_capable("Intel")

# Cached GPU availability (probed once at import time)
GPU_AVAILABLE = probe.check_vendor_gpu_available("Intel")

# ---------------------------------------------------------------------------
# Quality constants
# ---------------------------------------------------------------------------

QUALITY_VAAPI_AV1 = 90
QUALITY_PROPRIETARY_AV1 = 26
QUALITY_HEVC = 25
QUALITY_H264 = 21

INTEL_ACCEL_METHODS = ["QSV", "VAAPI"]

INTEL_HARDWARE_REGISTRY = {
    "QSV": {
        "dri_device": "/dev/dri/renderD128",
        "hwaccel": "qsv",
        "preset": "1",
        "codecs": {
            "AV1": {"codec": "av1_qsv", "quality": QUALITY_PROPRIETARY_AV1, "max_jobs": 2},
            "HEVC": {"codec": "hevc_qsv", "quality": QUALITY_HEVC, "max_jobs": 4},
            "H264": {"codec": "h264_qsv", "quality": QUALITY_H264, "max_jobs": 4},
        },
    },
    "VAAPI": {
        "dri_device": "/dev/dri/renderD128",
        "hwaccel": "vaapi",
        "preset": "1",
        "codecs": {
            "AV1": {"codec": "av1_vaapi", "quality": QUALITY_VAAPI_AV1, "max_jobs": 2},
            "HEVC": {"codec": "hevc_vaapi", "quality": QUALITY_HEVC, "max_jobs": 4},
            "H264": {"codec": "h264_vaapi", "quality": QUALITY_H264, "max_jobs": 4},
        },
    },
}


# ---------------------------------------------------------------------------
# Probe functions
# ---------------------------------------------------------------------------


def check_gpu_availability() -> bool:
    """Check if an Intel GPU with at least one working encoder is available."""
    return probe.check_vendor_gpu_available("Intel")


def resolve_intel_config(accel_method: str, codec_mode: str) -> dict:
    method_info = INTEL_HARDWARE_REGISTRY.get(accel_method, {})
    codec_info = method_info.get("codecs", {}).get(codec_mode, {})
    return {
        "dri_device": method_info.get("dri_device", "/dev/dri/renderD128"),
        "hwaccel": method_info.get("hwaccel", "qsv"),
        "preset": method_info.get("preset", "default"),
        "quality": codec_info.get("quality", QUALITY_HEVC),
        "codec": codec_info.get("codec", "h264_vaapi"),
        "max_jobs": codec_info.get("max_jobs", 2),
    }
