# Hardware Acceleration Requirements

## QSV (Intel Quick Sync Video)

### Hardware
- Intel CPU with integrated graphics (HD/Iris/UHD)
- Intel Arc GPU: drm-tip kernel driver
- Intel integrated GPU: onevpl-intel-gpu package

### Software
- FFmpeg with QSV support
- Intel Media Driver (onevpl-intel-gpu)
- Non-free Intel drivers

### FFmpeg Commands
- Device: `-qsv_device /dev/dri/renderD128`
- AV1/HEVC filter: `-filter:v format=p010,hwupload`
- H.264 filter: `-filter:v format=nv12,hwupload`
- Codecs: `av1_qsv`, `hevc_qsv`, `h264_qsv`

### Quality Settings
- AV1: 26 (lower = better)
- HEVC: 25 (lower = better)
- H.264: 21 (lower = better)

### System Packages
```bash
# Ubuntu/Debian
sudo apt install intel-media-driver onevpl-intel-gpu

# Fedora
sudo dnf install intel-media-driver

# Arch Linux
sudo pacman -S intel-media-driver
```

### DRI Device
- `/dev/dri/renderD128`

## NVENC (NVIDIA Video Encoder)

### Hardware
- NVIDIA GPU (GTX 900 series or newer)
- NVIDIA drivers installed

### Software
- FFmpeg with NVENC support
- NVIDIA drivers with NVENC support

### FFmpeg Commands
- No device initialization needed
- AV1/HEVC filter: `-filter:v format=p010,hwupload`
- H.264 filter: `-filter:v format=nv12,hwupload`
- Codecs: `av1_nvenc`, `hevc_nvenc`, `h264_nvenc`

### Quality Settings
- AV1: 26 (lower = better)
- HEVC: 25 (lower = better)
- H.264: 21 (lower = better)

### Preset Settings
- Default: `p7` (highest quality)
- Range: `p1` (fastest) to `p7` (highest quality)

### System Packages
```bash
# Ubuntu/Debian
sudo apt install nvidia-driver-xxx nvidia-utils-xxx

# Fedora
sudo dnf install nvidia-driver

# Arch Linux
sudo pacman -S nvidia
```

## Common Requirements

### FFmpeg Support
- FFmpeg with hardware acceleration
- Codecs: AV1, HEVC, H.264

### System
- Linux OS
- DRI support
- GPU drivers configured

### Verification
```bash
# Check encoders
ffmpeg -encoders | grep -E 'qsv|nvenc|vaapi'

# Check devices
ls /dev/dri/render*
```

### Performance Limits
- QSV: 2 jobs AV1, 4 jobs HEVC/H.264
- NVENC: 2 jobs AV1, 4 jobs HEVC/H.264
- VAAPI: Similar limits

### Quality Scales
- AV1 + VAAPI: 0-90 (higher = better)
- All others: 0-51 (lower = better)
- NVENC/QSV: Proprietary scale (lower = better)