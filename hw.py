#!/usr/bin/env python3
import sys
import os
import argparse

from ffmpeg_cmd import build_ffmpeg_command


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

        # Build FFmpeg command
        try:
            cmd = build_ffmpeg_command(
                input_file=video_file,
                output_file=output_file,
                gpu=gpu,
                codec=codec,
                preset=6,  # Default preset
                quality_target=23,  # Default quality
                max_concurrency=4  # Default concurrency
            )

            print(f"Command: {' '.join(cmd)}")

            # Execute the command
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                print(f"✓ Successfully processed: {filename}")
            else:
                print(f"✗ Error processing {filename}: {result.stderr}")

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
        print("Fatal Error: I assume you run on Linux. Remove this check if you want to bother with likely dead code.")
        sys.exit(1)

    # Check if running in CLI mode
    if len(sys.argv) > 1:
        # CLI mode — no tkinter needed
        parser = argparse.ArgumentParser(description='Video transcoding tool - CLI mode')
        parser.add_argument('input_folder', help='Input folder containing video files')
        parser.add_argument('output_folder', help='Output folder for transcoded files')
        parser.add_argument('gpu', choices=['amd', 'nvidia', 'intel'], help='GPU type')
        parser.add_argument('codec', choices=['av1', 'hevc', 'h264'], help='Video codec')

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
