from typing import List, Optional


def build_hw_init_args(accel_method: str, dri_device: Optional[str]) -> List[str]:
    if accel_method == "VAAPI":
        return ["-vaapi_device", dri_device] if dri_device else []
    if accel_method == "QSV":
        return ["-qsv_device", dri_device] if dri_device else []
    return []


def build_video_filter_args(codec_mode: str) -> List[str]:
    if codec_mode in ("AV1", "HEVC"):
        return ["-filter:v", "format=p010,hwupload"]
    return ["-filter:v", "format=nv12,hwupload"]


def build_video_codec_args(codec_mode: str) -> List[str]:
    codec_map = {
        "AV1": "av1_vaapi",
        "HEVC": "hevc_vaapi",
        "H264": "h264_vaapi",
    }
    return ["-c:v", codec_map.get(codec_mode, "h264_vaapi")]


def build_video_quality_args(codec_mode: str, resolved_quality: int, compression_preset: str) -> List[str]:
    if codec_mode == "AV1":
        return ["-q:v", str(resolved_quality), "-compression_level:v", compression_preset]
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
) -> List[str]:
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
        *build_video_filter_args(codec_mode),
        *build_video_codec_args(codec_mode),
        *build_video_quality_args(codec_mode, resolved_quality, compression_preset),
        *build_audio_args(),
        *build_subtitle_args(),
        *build_global_args(),
        output_file,
    ]
