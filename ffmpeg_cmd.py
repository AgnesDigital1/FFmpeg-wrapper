from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Accel-method helpers
# ---------------------------------------------------------------------------

# Methods that use VAAPI-style filter chains (hwupload) for sw-decode fallback
_VAAPI_METHODS = {"VAAPI", "QSV", "AMF"}

# Methods that are NVIDIA NVENC — completely different CLI syntax
_NVENC_METHODS = {"NVENC"}


def _build_hwaccel_args(hwaccel: str, dri_device: Optional[str]) -> List[str]:
    """Build hwaccel args placed BEFORE -i (for hardware decoding)."""
    if hwaccel == "vaapi":
        args = ["-hwaccel", "vaapi"]
        if dri_device:
            args += ["-vaapi_device", dri_device]
        return args
    if hwaccel == "qsv":
        args = ["-hwaccel", "qsv"]
        if dri_device:
            args += ["-qsv_device", dri_device]
        return args
    if hwaccel == "cuda":
        return ["-hwaccel", "cuda"]
    return []


def _build_init_args(accel_method: str, dri_device: Optional[str]) -> List[str]:
    """Build device init args placed AFTER -i (for encoder setup)."""
    if accel_method == "VAAPI":
        return ["-vaapi_device", dri_device] if dri_device else []
    if accel_method == "QSV":
        return ["-qsv_device", dri_device] if dri_device else []
    return []


def _build_filter_hw_decode(hwaccel: str, codec_mode: str) -> List[str]:
    """Filter chain for hw-decode → hw-encode (frames stay on GPU)."""
    if hwaccel in ("vaapi", "qsv"):
        # Frames are already VAAPI/QSV surfaces on GPU; just declare the format
        # so the encoder knows they're hardware frames. No hwupload needed.
        if codec_mode in ("AV1", "HEVC"):
            return ["-filter:v", "format=p010|vaapi"]
        return ["-filter:v", "format=nv12|vaapi"]
    if hwaccel == "cuda":
        # NVENC accepts CUDA frames directly, no filter needed
        return []
    return []


def _build_filter_sw_decode(accel_method: str, codec_mode: str) -> List[str]:
    """Filter chain for sw-decode → hwupload → hw-encode (fallback)."""
    if accel_method in _NVENC_METHODS:
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
        return ["-preset", compression_preset, "-cq", str(resolved_quality)]
    if accel_method in _VAAPI_METHODS:
        if codec_mode == "AV1":
            return ["-q:v", str(resolved_quality), "-compression_level:v", compression_preset]
        return ["-qp:v", str(resolved_quality), "-compression_level:v", compression_preset]
    return ["-qp:v", str(resolved_quality), "-compression_level:v", compression_preset]


def build_audio_args() -> List[str]:
    return ["-c:a", "libopus", "-b:a", "192k", "-vbr", "on", "-ac", "2"]


def build_subtitle_args() -> List[str]:
    return ["-c:s", "copy", "-c:t", "copy"]


def build_global_args() -> List[str]:
    return ["-nostats", "-map_chapters", "0", "-max_muxing_queue_size", "9999"]


def _resolve_video_codec(codec: Optional[str], codec_mode: str) -> str:
    if codec:
        return codec
    fallback_map = {
        "AV1": "av1_vaapi",
        "HEVC": "hevc_vaapi",
        "H264": "h264_vaapi",
    }
    return fallback_map.get(codec_mode, "h264_vaapi")


def build_ffmpeg_command(
    input_file: str,
    output_file: str,
    codec_mode: str,
    accel_method: str,
    dri_device: Optional[str],
    compression_preset: str,
    resolved_quality: int,
    codec: Optional[str] = None,
    hwaccel: Optional[str] = None,
    hw_decode: bool = False,
) -> List[str]:
    """
    Build an FFmpeg command.

    When hw_decode=True, emits hwaccel args BEFORE -i and uses a
    zero-copy filter chain (frames stay on GPU).
    When hw_decode=False, uses the sw-decode + hwupload fallback path.
    """
    video_codec = _resolve_video_codec(codec, codec_mode)

    if hw_decode and hwaccel:
        # Pipeline 1: hw decode → hw encode
        hwaccel_args = _build_hwaccel_args(hwaccel, dri_device)
        filter_args = _build_filter_hw_decode(hwaccel, codec_mode)
    else:
        # Pipeline 2: sw decode → hwupload → hw encode (fallback)
        hwaccel_args = _build_init_args(accel_method, dri_device)
        filter_args = _build_filter_sw_decode(accel_method, codec_mode)

    return [
        "ffmpeg",
        *hwaccel_args,
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
        *filter_args,
        *build_video_codec_args(video_codec),
        *build_video_quality_args(accel_method, codec_mode, resolved_quality, compression_preset),
        *build_audio_args(),
        *build_subtitle_args(),
        *build_global_args(),
        output_file,
    ]


def build_ffmpeg_command_with_fallback(
    input_file: str,
    output_file: str,
    codec_mode: str,
    accel_method: str,
    dri_device: Optional[str],
    compression_preset: str,
    resolved_quality: int,
    codec: Optional[str] = None,
    hwaccel: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """
    Build both pipeline commands: (hw_decode_cmd, sw_decode_fallback_cmd).
    The caller should try hw_decode first, then fall back to sw_decode.
    """
    hw_cmd = build_ffmpeg_command(
        input_file, output_file, codec_mode, accel_method,
        dri_device, compression_preset, resolved_quality,
        codec=codec, hwaccel=hwaccel, hw_decode=True,
    )
    sw_cmd = build_ffmpeg_command(
        input_file, output_file, codec_mode, accel_method,
        dri_device, compression_preset, resolved_quality,
        codec=codec, hwaccel=None, hw_decode=False,
    )
    return hw_cmd, sw_cmd
