from typing import List, Optional


# ---------------------------------------------------------------------------
# Accel-method helpers
# ---------------------------------------------------------------------------

# Methods that use VAAPI-style filter chains (hwupload)
_VAAPI_METHODS = {"VAAPI", "QSV", "AMF"}

# Methods that are NVIDIA NVENC — completely different CLI syntax
_NVENC_METHODS = {"NVENC"}


def build_hw_init_args(accel_method: str, dri_device: Optional[str]) -> List[str]:
    if accel_method == "VAAPI":
        return ["-vaapi_device", dri_device] if dri_device else []
    if accel_method == "QSV":
        return ["-qsv_device", dri_device] if dri_device else []
    # NVENC and AMF don't need a DRI device init arg
    return []


def build_video_filter_args(accel_method: str, codec_mode: str) -> List[str]:
    if accel_method in _NVENC_METHODS:
        # NVENC does not use VAAPI filter chains; it takes raw frames directly
        return []
    if accel_method in _VAAPI_METHODS:
        if codec_mode in ("AV1", "HEVC"):
            return ["-filter:v", "format=p010,hwupload"]
        return ["-filter:v", "format=nv12,hwupload"]
    return []


def build_video_codec_args(codec: str) -> List[str]:
    return ["-c:v", codec]


def build_video_quality_args(accel_method: str, codec_mode: str, resolved_quality: int, compression_preset: str) -> List[str]:
    if accel_method in _NVENC_METHODS:
        # NVENC uses -preset and -cq (constant quality)
        return ["-preset", compression_preset, "-cq", str(resolved_quality)]
    if accel_method in _VAAPI_METHODS:
        if codec_mode == "AV1":
            return ["-q:v", str(resolved_quality), "-compression_level:v", compression_preset]
        return ["-qp:v", str(resolved_quality), "-compression_level:v", compression_preset]
    # Fallback to VAAPI-style
    return ["-qp:v", str(resolved_quality), "-compression_level:v", compression_preset]


def build_audio_args() -> List[str]:
    return ["-c:a", "libopus", "-b:a", "192k", "-vbr", "on", "-ac", "2"]


def build_subtitle_args() -> List[str]:
    return ["-c:s", "copy", "-c:t", "copy"]


def build_global_args() -> List[str]:
    return ["-nostats", "-map_chapters", "0", "-max_muxing_queue_size", "9999"]


def build_ffmpeg_command(
    input_file: str,
    output_file: str,
    codec_mode: str,
    accel_method: str,
    dri_device: Optional[str],
    compression_preset: str,
    resolved_quality: int,
    codec: Optional[str] = None,
) -> List[str]:
    # If a specific codec name is provided (e.g. "hevc_nvenc"), use it directly.
    # Otherwise fall back to the old VAAPI-only mapping for backwards compat.
    if codec:
        video_codec_args = build_video_codec_args(codec)
    else:
        fallback_map = {
            "AV1": "av1_vaapi",
            "HEVC": "hevc_vaapi",
            "H264": "h264_vaapi",
        }
        video_codec_args = build_video_codec_args(fallback_map.get(codec_mode, "h264_vaapi"))

    return [
        "ffmpeg",
        *build_hw_init_args(accel_method, dri_device),
        "-y",
        "-i",
        input_file,
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        "-map",
        "0:t?",
        *build_video_filter_args(accel_method, codec_mode),
        *video_codec_args,
        *build_video_quality_args(accel_method, codec_mode, resolved_quality, compression_preset),
        *build_audio_args(),
        *build_subtitle_args(),
        *build_global_args(),
        output_file,
    ]
