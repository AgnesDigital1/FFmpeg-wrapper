QUALITY_VAAPI_AV1 = 90
QUALITY_PROPRIETARY_AV1 = 26
QUALITY_HEVC = 25
QUALITY_H264 = 21

AMD_ACCEL_METHODS = ["AMF", "VAAPI"]

AMD_HARDWARE_REGISTRY = {
    "VAAPI": {
        "dri_device": "/dev/dri/renderD128",
        "preset": "29",
        "codecs": {
            "AV1": {"codec": "av1_vaapi", "quality": QUALITY_VAAPI_AV1, "max_jobs": 2},
            "HEVC": {"codec": "hevc_vaapi", "quality": QUALITY_HEVC, "max_jobs": 4},
            "H264": {"codec": "h264_vaapi", "quality": QUALITY_H264, "max_jobs": 4},
        }
    },
    "AMF": {
        "dri_device": "/dev/dri/renderD128",
        "preset": "quality",
        "codecs": {
            "AV1": {"codec": "av1_amf", "quality": QUALITY_PROPRIETARY_AV1, "max_jobs": 2},
            "HEVC": {"codec": "hevc_amf", "quality": QUALITY_HEVC, "max_jobs": 4},
            "H264": {"codec": "h264_amf", "quality": QUALITY_H264, "max_jobs": 4},
        }
    }
}


def check_gpu_availability() -> bool:
    """Stubbed AMD GPU availability probe."""
    msg = "[AMD GPU Probe] Skipping actual hardware checks (Stub). Returning True."
    print(msg)
    return True


def check_amf_support() -> bool:
    """Stubbed AMD AMF driver probe."""
    msg = "[AMD AMF Probe] AMF hardware driver probe (Stub). Returning False."
    print(msg)
    return False


def resolve_amd_config(accel_method: str, codec_mode: str) -> dict:
    method_info = AMD_HARDWARE_REGISTRY.get(accel_method, {})
    codec_info = method_info.get("codecs", {}).get(codec_mode, {})
    return {
        "dri_device": method_info.get("dri_device", "/dev/dri/renderD128"),
        "preset": method_info.get("preset", "default"),
        "quality": codec_info.get("quality", QUALITY_HEVC),
        "codec": codec_info.get("codec", "h264_vaapi"),
        "max_jobs": codec_info.get("max_jobs", 2),
    }
