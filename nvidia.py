QUALITY_PROPRIETARY_AV1 = 26
QUALITY_HEVC = 25
QUALITY_H264 = 21

NVIDIA_ACCEL_METHODS = ["NVENC"]

NVIDIA_HARDWARE_REGISTRY = {
    "NVENC": {
        "dri_device": None,
        "preset": "p7",
        "codecs": {
            "AV1": {"codec": "av1_nvenc", "quality": QUALITY_PROPRIETARY_AV1, "max_jobs": 2},
            "HEVC": {"codec": "hevc_nvenc", "quality": QUALITY_HEVC, "max_jobs": 4},
            "H264": {"codec": "h264_nvenc", "quality": QUALITY_H264, "max_jobs": 4},
        }
    }
}


def check_gpu_availability() -> bool:
    """Stubbed NVIDIA GPU availability probe."""
    msg = "[NVIDIA GPU Probe] Skipping actual hardware checks (Stub). Returning True."
    print(msg)
    return True


def resolve_nvidia_config(codec_mode: str) -> dict:
    method_info = NVIDIA_HARDWARE_REGISTRY["NVENC"]
    codec_info = method_info.get("codecs", {}).get(codec_mode, {})
    return {
        "dri_device": method_info.get("dri_device"),
        "preset": method_info.get("preset", "default"),
        "quality": codec_info.get("quality", QUALITY_HEVC),
        "codec": codec_info.get("codec", "h264_nvenc"),
        "max_jobs": codec_info.get("max_jobs", 2),
    }
