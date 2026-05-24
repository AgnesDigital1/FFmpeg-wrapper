"""
Hardware encoder probe module.

Provides functions to detect available FFmpeg hardware encoders
and verify they actually work by running a dummy transcode test.

Usage:
    from probe import check_encoder_available, check_av1_capable
"""

import subprocess
import shutil
import os
import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# PCI vendor IDs for GPU detection
PCI_VENDOR_IDS = {
    "AMD": "1002",
    "NVIDIA": "10de",
    "Intel": "8086",
}

# Each vendor maps its accel methods to the FFmpeg encoder names to test.
# Format: {accel_method: [encoder_name, ...]}
VENDOR_ENCODERS = {
    "AMD": {
        "VAAPI": ["av1_vaapi", "hevc_vaapi", "h264_vaapi"],
        "AMF": ["av1_amf", "hevc_amf", "h264_amf"],
    },
    "NVIDIA": {
        "NVENC": ["av1_nvenc", "hevc_nvenc", "h264_nvenc"],
    },
    "Intel": {
        "QSV": ["av1_qsv", "hevc_qsv", "h264_qsv"],
        "VAAPI": ["av1_vaapi", "hevc_vaapi", "h264_vaapi"],
    },
}

# AV1 encoder names per vendor (subset of above, used for AV1 capability check)
VENDOR_AV1_ENCODERS = {
    "AMD": {
        "VAAPI": "av1_vaapi",
        "AMF": "av1_amf",
    },
    "NVIDIA": {
        "NVENC": "av1_nvenc",
    },
    "Intel": {
        "QSV": "av1_qsv",
        "VAAPI": "av1_vaapi",
    },
}

# DRI devices to try for VAAPI/QSV
DRI_DEVICES = ["/dev/dri/renderD128", "/dev/dri/renderD129"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_ffmpeg() -> str | None:
    """Return path to ffmpeg binary, or None if not found."""
    return shutil.which("ffmpeg")


def _find_dri_device() -> str | None:
    """Return the first available DRI render node, or None."""
    for dev in DRI_DEVICES:
        if os.path.exists(dev):
            return dev
    return None


def _get_pci_vendor_id(device_path: str) -> str | None:
    """
    Read the PCI vendor ID from a DRI device's sysfs entry.

    Accepts either /dev/dri/renderD128 or /sys/class/drm/renderD128 paths.
    Returns the vendor ID hex string (e.g. '1002' for AMD) or None.
    """
    try:
        # Extract the render node name (e.g. "renderD128")
        basename = os.path.basename(device_path)

        # Try the standard sysfs path for DRM render nodes
        sysfs_vendor = f"/sys/class/drm/{basename}/device/vendor"
        if os.path.exists(sysfs_vendor):
            with open(sysfs_vendor, "r") as f:
                vendor = f.read().strip()
                # Normalize: remove '0x' prefix if present
                return vendor.lower().replace("0x", "")

        # Fallback: try resolving via realpath for card devices
        real_path = os.path.realpath(device_path)
        if "/drm/" in real_path:
            parts = real_path.split("/")
            for i, part in enumerate(parts):
                if part == "drm" and i + 1 < len(parts):
                    sysfs_base = "/".join(parts[:i])
                    vendor_path = os.path.join(sysfs_base, "device", "vendor")
                    if os.path.exists(vendor_path):
                        with open(vendor_path, "r") as f:
                            vendor = f.read().strip()
                            return vendor.lower().replace("0x", "")
    except (OSError, IOError):
        pass
    return None


def _dri_device_belongs_to_vendor(device_path: str, vendor: str) -> bool:
    """
    Check if a DRI render node belongs to a specific PCI vendor.

    This prevents false positives where e.g. Intel VAAPI results are
    attributed to AMD when the AMD GPU is the only one present.
    """
    expected_vid = PCI_VENDOR_IDS.get(vendor)
    if not expected_vid:
        return False

    actual_vid = _get_pci_vendor_id(device_path)
    if actual_vid is None:
        # Can't determine — be permissive
        return True

    return actual_vid == expected_vid


def _any_gpu_present_for_vendor(vendor: str) -> bool:
    """
    Check if any GPU from the given vendor exists in the system
    by scanning lspci output.
    """
    expected_vid = PCI_VENDOR_IDS.get(vendor)
    if not expected_vid:
        return False
    try:
        result = subprocess.run(
            ["lspci", "-n"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        # Look for lines like: "03:00.0 0300: 1002:747e ..."
        pattern = re.compile(rf"{expected_vid}:", re.IGNORECASE)
        return bool(pattern.search(result.stdout))
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _run_ffmpeg_dummy_encode(encoder: str, dri_device: str | None = None) -> bool:
    """
    Run a 1-frame dummy transcode to verify an encoder actually works.

    Returns True if the encoder succeeds, False otherwise.
    """
    cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=1",
    ]

    # Add device init for VAAPI/QSV
    if encoder.endswith("_vaapi") and dri_device:
        cmd += ["-vaapi_device", dri_device]
        cmd += ["-filter:v", "format=nv12,hwupload"]
    elif encoder.endswith("_qsv") and dri_device:
        cmd += ["-qsv_device", dri_device]
        cmd += ["-filter:v", "format=nv12,hwupload"]

    cmd += ["-c:v", encoder, "-f", "null", "-"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _encoder_in_ffmpeg(encoder: str) -> bool:
    """Check if an encoder name appears in ffmpeg -encoders output."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        # Lines look like: " V..... av1_vaapi  ..."
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == encoder:
                return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_encoder_available(encoder: str, dri_device: str | None = None) -> bool:
    """
    Check if an encoder is both listed by ffmpeg AND actually functional.

    1. Queries ffmpeg -encoders for the encoder name.
    2. Runs a dummy 1-frame transcode to verify it works.

    Returns True only if both checks pass.
    """
    if not _encoder_in_ffmpeg(encoder):
        return False
    return _run_ffmpeg_dummy_encode(encoder, dri_device)


def check_vendor_gpu_available(vendor: str) -> bool:
    """
    Check if a GPU from the given vendor is available by testing
    at least one H.264 encoder (always assumed supported).

    For VAAPI methods, also verifies the DRI device belongs to the
    correct PCI vendor to avoid false positives.

    vendor: "AMD", "NVIDIA", or "Intel"
    """
    encoders = VENDOR_ENCODERS.get(vendor, {})
    dri_device = _find_dri_device()

    for accel_method, encoder_list in encoders.items():
        # For VAAPI, verify the DRI device belongs to this vendor
        if accel_method == "VAAPI" and dri_device:
            if not _dri_device_belongs_to_vendor(dri_device, vendor):
                continue

        # Test H.264 encoder as baseline (always expected to work)
        h264_encoder = encoder_list[-1]  # H.264 is always last in our lists
        if check_encoder_available(h264_encoder, dri_device):
            return True
    return False


def check_vendor_av1_capable(vendor: str, accel_method: str | None = None) -> bool:
    """
    Check if the given vendor (and optionally a specific accel method)
    supports AV1 encoding.

    For VAAPI methods, also verifies the DRI device belongs to the
    correct PCI vendor to avoid false positives.

    If accel_method is None, checks all methods for that vendor.

    Returns True if any AV1 encoder works.
    """
    av1_map = VENDOR_AV1_ENCODERS.get(vendor, {})
    dri_device = _find_dri_device()

    methods_to_check = [accel_method] if accel_method else list(av1_map.keys())

    for method in methods_to_check:
        if method is None:
            continue

        # For VAAPI, verify the DRI device belongs to this vendor
        if method == "VAAPI" and dri_device:
            if not _dri_device_belongs_to_vendor(dri_device, vendor):
                continue

        encoder = av1_map.get(method)
        if encoder and check_encoder_available(encoder, dri_device):
            return True
    return False


def probe_vendor(vendor: str) -> dict:
    """
    Full probe for a vendor. Returns a dict with:
        - gpu_available: bool
        - av1_capable: bool
        - working_methods: list of accel methods that have working H.264
        - av1_methods: list of accel methods that support AV1

    For VAAPI methods, the DRI device must belong to the correct PCI vendor.
    """
    result = {
        "gpu_available": False,
        "av1_capable": False,
        "working_methods": [],
        "av1_methods": [],
    }

    dri_device = _find_dri_device()
    encoders = VENDOR_ENCODERS.get(vendor, {})
    av1_map = VENDOR_AV1_ENCODERS.get(vendor, {})

    for accel_method, encoder_list in encoders.items():
        h264_encoder = encoder_list[-1]

        # For VAAPI, verify the DRI device belongs to this vendor
        if accel_method == "VAAPI" and dri_device:
            if not _dri_device_belongs_to_vendor(dri_device, vendor):
                continue

        # Check if baseline H.264 works
        if check_encoder_available(h264_encoder, dri_device):
            result["gpu_available"] = True
            result["working_methods"].append(accel_method)

        # Check AV1
        av1_encoder = av1_map.get(accel_method)
        if av1_encoder and check_encoder_available(av1_encoder, dri_device):
            result["av1_capable"] = True
            result["av1_methods"].append(accel_method)

    return result
