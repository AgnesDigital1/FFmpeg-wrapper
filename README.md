This is a 95% vibe coded FFmpeg wrapper that only uses AMD VAAPI well, others may or may not be supported ever.
Only thing it does is re encoding entire folders at effectively hard coded settings.
If you bother to use it:
- GUI mode: ```python hw.py```
- CLI mode: ```python hw.py [input folder] [destination folder] [gpu] [codec]```

This script is assumed to be run on Linux with ```zenity``` and default ```ffmpeg``` installed. I won't bother with 2 other "Operating Systems"