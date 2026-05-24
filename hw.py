#!/usr/bin/env python3
import sys
import os
import argparse

from ffmpeg_cmd import build_ffmpeg_command, build_ffmpeg_command_with_fallback


# Map CLI vendor names to (module_name, accel_method) pairs
_GPU_VENDOR_MAP = {
    "nvidia": ("nvidia", "NVENC"),
    "amd": ("amd", "VAAPI"),
    "intel": ("intel", "QSV"),
}

# Cache imported vendor modules
_vendor_modules = {}


def _get_vendor_config(gpu: str, codec: str):
    """Resolve the correct accel method, dri_device, preset, and quality for a given GPU vendor and codec."""
    gpu_lower = gpu.lower()
    if gpu_lower not in _GPU_VENDOR_MAP:
        raise ValueError(f"Unknown GPU vendor '{gpu}'. Choose from: {', '.join(_GPU_VENDOR_MAP)}")

    module_name, accel_method = _GPU_VENDOR_MAP[gpu_lower]

    if module_name not in _vendor_modules:
        _vendor_modules[module_name] = __import__(module_name)

    mod = _vendor_modules[module_name]
    codec_upper = codec.upper()

    # Each vendor module has its own resolve_*_config with slightly different signatures
    if module_name == "nvidia":
        config = mod.resolve_nvidia_config(codec_upper)
    elif module_name == "amd":
        config = mod.resolve_amd_config(accel_method, codec_upper)
    elif module_name == "intel":
        config = mod.resolve_intel_config(accel_method, codec_upper)
    else:
        raise ValueError(f"No config resolver for vendor '{module_name}'")

    return accel_method, config


def _verify_gpu_working(accel_method: str, codec: str, dri_device) -> bool:
    """Run a quick 1-frame dummy encode to verify the GPU encoder actually works."""
    import subprocess

    cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=1",
    ]

    if accel_method == "VAAPI" and dri_device:
        cmd += ["-vaapi_device", dri_device, "-filter:v", "format=nv12,hwupload"]
    elif accel_method == "QSV" and dri_device:
        cmd += ["-qsv_device", dri_device, "-filter:v", "format=nv12,hwupload"]

    cmd += ["-c:v", codec, "-f", "null", "-"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print(f"  [GPU verify] Dummy encode failed (rc={result.returncode}):")
            for line in result.stderr.splitlines():
                if "error" in line.lower() or "failed" in line.lower() or "cuda" in line.lower():
                    print(f"    {line.strip()}")
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        print(f"  [GPU verify] Dummy encode error: {e}")
        return False


def run_cli_transcoding(input_folder, output_folder, gpu, codec):
    """Run transcoding in CLI mode without GUI"""
    print(f"Starting CLI transcoding...")
    print(f"Input folder: {input_folder}")
    print(f"Output folder: {output_folder}")
    print(f"GPU: {gpu}")
    print(f"Codec: {codec}")

    # Validate input folder exists
    if not os.path.exists(input_folder):
        print(f"Error: Input folder '{input_folder}' does not exist.")
        sys.exit(1)

    # Validate output folder exists or create it
    if not os.path.exists(output_folder):
        try:
            os.makedirs(output_folder)
            print(f"Created output folder: {output_folder}")
        except OSError as e:
            print(f"Error: Cannot create output folder '{output_folder}': {e}")
            sys.exit(1)

    # Resolve GPU vendor configuration
    try:
        accel_method, vendor_config = _get_vendor_config(gpu, codec)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error resolving GPU config: {e}")
        sys.exit(1)

    dri_device = vendor_config.get("dri_device")
    hwaccel = vendor_config.get("hwaccel")
    compression_preset = vendor_config.get("preset", "6")
    resolved_quality = vendor_config.get("quality", 23)

    print(f"Accel method: {accel_method}, HW accel: {hwaccel}, DRI device: {dri_device}, Preset: {compression_preset}, Quality: {resolved_quality}")

    # Verify GPU is actually available and working (unless --force)
    if not args.force and not _verify_gpu_working(accel_method, vendor_config.get("codec"), dri_device):
        print(f"Error: GPU encoder verification failed.")
        print(f"Run 'ffmpeg -encoders | grep {accel_method.lower()}' to check encoder availability.")
        if accel_method == "NVENC":
            print("For NVIDIA GPUs on headless servers, ensure:")
            print("  - nvidia kernel module is loaded: lsmod | grep nvidia")
            print("  - device nodes exist: ls /dev/nvidia*")
            print("  - nvidia-persistenced is running (recommended for headless)")
            print("  - If in a container, GPU must be passed through (--gpus all)")
        print("")
        print("To skip this check, use --force")
        sys.exit(1)

    # Get video files from input folder
    video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm']
    video_files = []

    for file in os.listdir(input_folder):
        if any(file.lower().endswith(ext) for ext in video_extensions):
            video_files.append(os.path.join(input_folder, file))

    if not video_files:
        print(f"Error: No video files found in '{input_folder}'")
        sys.exit(1)

    print(f"Found {len(video_files)} video files to process")

    # Process each video file
    for video_file in video_files:
        filename = os.path.basename(video_file)
        output_file = os.path.join(output_folder, filename)

        print(f"\nProcessing: {filename}")

        try:
            # Build both pipeline variants
            hw_cmd, sw_cmd = build_ffmpeg_command_with_fallback(
                input_file=video_file,
                output_file=output_file,
                codec_mode=codec.upper(),
                accel_method=accel_method,
                dri_device=dri_device,
                compression_preset=str(compression_preset),
                resolved_quality=int(resolved_quality),
                codec=vendor_config.get("codec"),
                hwaccel=hwaccel,
            )

            # Try pipeline 1: hw decode → hw encode
            print(f"  Trying HW decode pipeline...")
            print(f"  Command: {' '.join(hw_cmd)}")
            import subprocess
            result = subprocess.run(hw_cmd, capture_output=True, text=True)

            if result.returncode == 0:
                print(f"✓ Successfully processed (HW decode): {filename}")
                continue

            # Pipeline 1 failed — fall back to pipeline 2
            print(f"  HW decode failed, falling back to SW decode + hwupload...")
            print(f"  Command: {' '.join(sw_cmd)}")
            result = subprocess.run(sw_cmd, capture_output=True, text=True)

            if result.returncode == 0:
                print(f"✓ Successfully processed (SW decode fallback): {filename}")
            else:
                print(f"✗ Error processing {filename}: {result.stderr}")
                stderr_lower = result.stderr.lower()
                if "cuda" in stderr_lower or "cuinit" in stderr_lower or "cuda_error" in stderr_lower:
                    print("")
                    print("  [CUDA / NVIDIA driver issue detected]")
                    print("  On headless servers without a display:")
                    print("    1. Ensure nvidia kernel module is loaded:  lsmod | grep nvidia")
                    print("    2. Check device nodes exist:              ls /dev/nvidia*")
                    print("    3. Start nvidia-persistenced:             nvidia-persistenced --verbose")
                    print("    4. If in Docker, pass GPU through:         docker run --gpus all ...")
                    print("    5. Check driver version matches:          nvidia-smi")

        except Exception as e:
            print(f"✗ Error building command for {filename}: {e}")


def run_gui():
    """Launch the GUI application. Only called when tkinter is available."""
    import tkinter as tk
    from gui import BatchVideoTranscoderApp

    root = tk.Tk()
    app = BatchVideoTranscoderApp(root)
    root.mainloop()


if __name__ == "__main__":
    if not sys.platform.startswith("linux"):
        print("Fatal Error: I assume you run on Linux. Remove this check if you want to bother yourself.")
        sys.exit(1)

    # Check if running in CLI mode
    if len(sys.argv) > 1:
        # CLI mode — no tkinter needed
        parser = argparse.ArgumentParser(description='Video transcoding tool - CLI mode')
        parser.add_argument('input_folder', help='Input folder containing video files')
        parser.add_argument('output_folder', help='Output folder for transcoded files')
        parser.add_argument('gpu', choices=['amd', 'nvidia', 'intel', "AMD", 'NVIDIA', 'INTEL', 'Intel'], help='GPU type')
        parser.add_argument('codec', choices=['av1', 'hevc', 'h264', 'AV1', 'HEVC', 'H264'], help='Video codec')
        parser.add_argument('--force', action='store_true', help='Skip GPU verification check')

        args = parser.parse_args()

        run_cli_transcoding(args.input_folder, args.output_folder, args.gpu, args.codec)
    else:
        # GUI mode — tkinter required
        try:
            import tkinter as tk
        except ImportError:
            print("Error: tkinter is not installed. Cannot start GUI.")
            print("Install it with your package manager, e.g.:")
            print("  Ubuntu/Debian: sudo apt install python3-tk")
            print("  Fedora:        sudo dnf install python3-tkinter")
            print("  Arch:          sudo pacman -S tk")
            print("")
            print("Or use CLI mode:")
            print("  python hw.py <input_folder> <output_folder> <gpu> <codec>")
            sys.exit(1)

        run_gui()
