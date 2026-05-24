import os
import sys
import time
import signal
import asyncio
import threading
import queue
from tkinter import scrolledtext, messagebox, filedialog
import tkinter as tk
from tkinter import ttk
import shutil
import subprocess

import amd
import nvidia
import intel
from ffmpeg_cmd import build_ffmpeg_command


class BatchVideoTranscoderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Modular Batch Video Transcoder")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)

        _detected_brands = self.get_available_gpu_brands()
        _default_brand = _detected_brands[0] if _detected_brands else "AMD"

        self.GPU_BRAND_VAR = tk.StringVar(value=_default_brand)
        self.CODEC_MODE_VAR = tk.StringVar(value="HEVC")
        self.SRC_DIR_VAR = tk.StringVar()
        self.PARENT_DST_DIR_VAR = tk.StringVar()

        self.GPU_BRAND = _default_brand
        self.CODEC_MODE = "HEVC"
        self.SRC_DIR = ""
        self.PARENT_DST_DIR = ""
        self.FINAL_DST_DIR = ""
        self.MAX_JOBS = 4

        self.ACCEL_METHOD = "VAAPI"
        self.DRI_DEVICE = "/dev/dri/renderD128"
        self.COMPRESSION_PRESET = "29"
        self.RESOLVED_QUALITY = amd.QUALITY_HEVC

        self.PRESET_VAR = tk.StringVar(value=self.COMPRESSION_PRESET)
        self.QUALITY_TARGET_VAR = tk.IntVar(value=self.RESOLVED_QUALITY)
        self.MAX_CONCURRENCY_VAR = tk.IntVar(value=self.MAX_JOBS)
        self.ACCEL_METHOD_VAR = tk.StringVar(value=self.ACCEL_METHOD)

        self._default_preset = self.COMPRESSION_PRESET
        self._default_quality = self.RESOLVED_QUALITY
        self._default_max_jobs = self.MAX_JOBS

        self.EXTENSIONS = (".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov")
        self.FILE_QUEUE = []
        self.TOTAL_FILES = 0
        self.LOG_DIR = os.path.expanduser("~/.cache/batch_transcode/logs/")

        self.PASS_COUNT = 0
        self.FAIL_COUNT = 0
        self.SKIP_COUNT = 0
        self.BATCH_START_TIME = 0.0

        self.active_pids = set()
        self.pids_lock = threading.Lock()
        self.ui_msg_queue = queue.Queue()
        self.async_loop = None
        self.async_tasks = []
        self.transcoding_thread = None
        self.is_transcoding = False

        self.create_widgets()

        self.GPU_BRAND_VAR.trace_add("write", self.on_gui_settings_changed)
        self.CODEC_MODE_VAR.trace_add("write", self.on_gui_settings_changed)
        self.ACCEL_METHOD_VAR.trace_add("write", self.on_gui_settings_changed)

        self.on_gui_settings_changed()
        self.setup_signals()
        self.poll_ui_queue()

    def check_gpu_availability(self) -> bool:
        if self.GPU_BRAND == "AMD":
            return amd.check_gpu_availability()
        if self.GPU_BRAND == "NVIDIA":
            return nvidia.check_gpu_availability()
        if self.GPU_BRAND == "Intel":
            return intel.check_gpu_availability()
        return False

    def pick_directory(self, title: str) -> str:
        if shutil.which("zenity"):
            try:
                result = subprocess.run(
                    ["zenity", "--file-selection", "--directory", "--title", title],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                pass
        return filedialog.askdirectory(title=title)

    def get_quality_scale_range(self):
        if self.GPU_BRAND == "AMD" and self.ACCEL_METHOD == "VAAPI" and self.CODEC_MODE == "AV1":
            return 0, 255
        return 0, 51

    def get_available_codecs(self):
        codecs = ["HEVC", "H264"]
        if self.GPU_BRAND == "AMD" and amd.AV1_CAPABLE:
            codecs.insert(0, "AV1")
        elif self.GPU_BRAND == "NVIDIA" and nvidia.AV1_CAPABLE:
            codecs.insert(0, "AV1")
        elif self.GPU_BRAND == "Intel" and intel.AV1_CAPABLE:
            codecs.insert(0, "AV1")
        return codecs

    def get_available_gpu_brands(self):
        """Return list of GPU brands with detected hardware."""
        brands = []
        if amd.GPU_AVAILABLE:
            brands.append("AMD")
        if nvidia.GPU_AVAILABLE:
            brands.append("NVIDIA")
        if intel.GPU_AVAILABLE:
            brands.append("Intel")
        return brands

    def update_codec_options(self):
        available = self.get_available_codecs()
        if hasattr(self, "cmb_codec"):
            self.cmb_codec.config(values=available)
        current = self.CODEC_MODE_VAR.get()
        if current not in available:
            self.CODEC_MODE_VAR.set(available[0])

    def get_available_accel_methods(self):
        if self.GPU_BRAND == "AMD":
            return ["AMF", "VAAPI"]
        if self.GPU_BRAND == "Intel":
            return ["QSV", "VAAPI"]
        if self.GPU_BRAND == "NVIDIA":
            return ["NVENC"]
        return []

    def auto_select_accel_method(self):
        if self.GPU_BRAND == "AMD":
            # preserve the existing AMD fallback path
            if amd.check_amf_support():
                return "AMF"
            return "VAAPI"
        if self.GPU_BRAND == "Intel":
            return "QSV"
        if self.GPU_BRAND == "NVIDIA":
            return "NVENC"
        return "VAAPI"

    def update_accel_options(self):
        available = self.get_available_accel_methods()
        if hasattr(self, "cmb_accel"):
            self.cmb_accel.config(values=available)
            self.cmb_accel.config(state="readonly" if len(available) > 1 else "disabled")

        if self.GPU_BRAND == "NVIDIA":
            if hasattr(self, "cmb_accel"):
                self.cmb_accel.grid_remove()
            if hasattr(self, "lbl_accel_text"):
                self.lbl_accel_text.config(text="NVENC")
                self.lbl_accel_text.grid()
        else:
            if hasattr(self, "lbl_accel_text"):
                self.lbl_accel_text.grid_remove()
            if hasattr(self, "cmb_accel"):
                self.cmb_accel.grid()

        if self.ACCEL_METHOD_VAR.get() not in available:
            self.ACCEL_METHOD_VAR.set(self.auto_select_accel_method())

    def get_preset_range_text(self):
        if self.GPU_BRAND == "AMD":
            return "Preset range: 0-29\nBigger = Better"
        if self.GPU_BRAND == "NVIDIA":
            return "Preset range: 1-7\nBigger = Better"
        if self.GPU_BRAND == "Intel":
            return "Preset range: 1-7\nSmaller = Better"
        return "Preset range: default"

    def update_quality_scale(self):
        min_q, max_q = self.get_quality_scale_range()
        try:
            current = int(self.QUALITY_TARGET_VAR.get())
        except (ValueError, TypeError):
            current = self._default_quality

        if current < min_q or current > max_q:
            current = max(min_q, min(current, max_q))
            self.QUALITY_TARGET_VAR.set(current)

        if hasattr(self, "spin_quality"):
            self.spin_quality.config(from_=min_q, to=max_q)
        if hasattr(self, "lbl_quality_scale"):
            if self.GPU_BRAND == "AMD" and self.ACCEL_METHOD == "VAAPI" and self.CODEC_MODE == "AV1":
                self.lbl_quality_scale.config(text=f"Quality range: {min_q}-{max_q}\nBigger = Better")
            elif self.GPU_BRAND == "NVIDIA":
                self.lbl_quality_scale.config(text=f"Quality range: {min_q}-{max_q}\nBigger = Better")
            else:
                self.lbl_quality_scale.config(text=f"Quality range: {min_q}-{max_q}\nSmaller = Better")
        if hasattr(self, "lbl_preset_scale"):
            self.lbl_preset_scale.config(text=self.get_preset_range_text())

    def sync_user_settings(self):
        self.COMPRESSION_PRESET = self.PRESET_VAR.get().strip() or self.COMPRESSION_PRESET

        try:
            quality = int(self.QUALITY_TARGET_VAR.get())
        except (ValueError, TypeError):
            quality = self._default_quality
        min_q, max_q = self.get_quality_scale_range()
        self.RESOLVED_QUALITY = max(min_q, min(quality, max_q))
        self.QUALITY_TARGET_VAR.set(self.RESOLVED_QUALITY)

        try:
            max_jobs = int(self.MAX_CONCURRENCY_VAR.get())
        except (ValueError, TypeError):
            max_jobs = self._default_max_jobs
        self.MAX_JOBS = max(1, max_jobs)

    def resolve_hardware_config(self):
        if self.GPU_BRAND == "AMD":
            config = amd.resolve_amd_config(self.ACCEL_METHOD, self.CODEC_MODE)
        elif self.GPU_BRAND == "NVIDIA":
            config = nvidia.resolve_nvidia_config(self.CODEC_MODE)
        elif self.GPU_BRAND == "Intel":
            config = intel.resolve_intel_config(self.ACCEL_METHOD, self.CODEC_MODE)
        else:
            config = {
                "dri_device": "/dev/dri/renderD128",
                "preset": "default",
                "quality": amd.QUALITY_HEVC,
                "codec": "h264_vaapi",
                "max_jobs": 2,
            }

        previous_default_preset = self._default_preset
        previous_default_quality = self._default_quality
        previous_default_max_jobs = self._default_max_jobs

        if self.PRESET_VAR.get() == previous_default_preset:
            self.PRESET_VAR.set(config["preset"])
        if self.QUALITY_TARGET_VAR.get() == previous_default_quality:
            self.QUALITY_TARGET_VAR.set(config["quality"])
        if self.MAX_CONCURRENCY_VAR.get() == previous_default_max_jobs:
            self.MAX_CONCURRENCY_VAR.set(config["max_jobs"])

        self._default_preset = config["preset"]
        self._default_quality = config["quality"]
        self._default_max_jobs = config["max_jobs"]

        self.DRI_DEVICE = config["dri_device"]
        self.COMPRESSION_PRESET = self.PRESET_VAR.get()
        self.RESOLVED_QUALITY = self.QUALITY_TARGET_VAR.get()
        self.MAX_JOBS = self.MAX_CONCURRENCY_VAR.get()

    def on_gui_settings_changed(self, *args):
        self.GPU_BRAND = self.GPU_BRAND_VAR.get()
        self.CODEC_MODE = self.CODEC_MODE_VAR.get()

        self.update_codec_options()
        self.update_accel_options()
        self.ACCEL_METHOD = self.ACCEL_METHOD_VAR.get()

        self.resolve_hardware_config()
        self.update_quality_scale()
        self.sync_user_settings()

        self.lbl_accel.config(text=f"API Method: {self.ACCEL_METHOD}")

        if self.GPU_BRAND == "AMD" and self.ACCEL_METHOD == "AMF":
            self.lbl_warning.config(
                text="⚠️ AMD AMF is a stub. Requires AMDPRO driver or AMF headers.",
                foreground="black"
            )
        elif self.GPU_BRAND == "Intel" and self.ACCEL_METHOD == "QSV":
            self.lbl_warning.config(
                text="⚠️ Intel QSV is a stub. Requires non-free driver, onevpl-intel-gpu or drm-tip (for Arc).",
                foreground="black"
            )
        else:
            self.lbl_warning.config(text="")

    def browse_src_dir(self):
        directory = self.pick_directory("Select Source Directory")
        if directory:
            self.SRC_DIR_VAR.set(directory)
            self.scan_source_directory()

    def browse_dst_dir(self):
        directory = self.pick_directory("Select Parent Destination")
        if directory:
            self.PARENT_DST_DIR_VAR.set(directory)

    def scan_source_directory(self):
        self.SRC_DIR = self.SRC_DIR_VAR.get().strip()
        if not self.SRC_DIR or not os.path.isdir(self.SRC_DIR):
            self.log_to_ui("[Error] Invalid source directory selected.")
            return

        self.FILE_QUEUE = []
        for root_path, _, files in os.walk(self.SRC_DIR):
            for file in files:
                if file.lower().endswith(self.EXTENSIONS):
                    self.FILE_QUEUE.append(os.path.join(root_path, file))

        self.TOTAL_FILES = len(self.FILE_QUEUE)
        self.lbl_total_files.config(text=f"Discovered Files: {self.TOTAL_FILES}")
        self.log_to_ui(f"[Discovery] Scanned {self.TOTAL_FILES} video files.")

    def start_transcoding(self):
        if self.is_transcoding:
            return

        self.SRC_DIR = self.SRC_DIR_VAR.get().strip()
        self.PARENT_DST_DIR = self.PARENT_DST_DIR_VAR.get().strip()

        if not self.SRC_DIR or not os.path.isdir(self.SRC_DIR):
            messagebox.showerror("Validation Error", "Please provide a valid source directory.")
            return

        if not self.PARENT_DST_DIR or not os.path.isdir(self.PARENT_DST_DIR):
            messagebox.showerror("Validation Error", "Please provide a valid target destination.")
            return

        if self.GPU_BRAND != "AMD" or self.ACCEL_METHOD != "VAAPI":
            messagebox.showerror(
                "Unimplemented Path",
                f"Validation Failed: Configuration '{self.GPU_BRAND} {self.ACCEL_METHOD}' is a stub.\n"
                "Only the AMD VAAPI path is implemented."
            )
            return

        if not self.FILE_QUEUE:
            self.scan_source_directory()
            if not self.FILE_QUEUE:
                messagebox.showerror("Queue Empty", "No compatible video files were discovered.")
                return

        if not self.check_gpu_availability():
            messagebox.showerror("GPU Error", "Hardware check failed.")
            return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.FINAL_DST_DIR = os.path.join(self.PARENT_DST_DIR, f"batch_transcode_{self.CODEC_MODE.lower()}_{timestamp}")

        try:
            os.makedirs(self.FINAL_DST_DIR, exist_ok=True)
            os.makedirs(self.LOG_DIR, exist_ok=True)
        except Exception as err:
            messagebox.showerror("System Error", f"Unable to create directories: {err}")
            return

        self.sync_user_settings()
        self.PASS_COUNT = 0
        self.FAIL_COUNT = 0
        self.SKIP_COUNT = 0
        self.BATCH_START_TIME = time.time()

        self.toggle_inputs_state(False)
        self.is_transcoding = True

        self.log_to_ui(f"[Batch] Staging batch in: {self.FINAL_DST_DIR}")
        self.log_to_ui(f"[Batch] FFmpeg execution logs mapping to: {self.LOG_DIR}")

        self.transcoding_thread = threading.Thread(target=self.run_asyncio_loop, daemon=True)
        self.transcoding_thread.start()

    def abort_transcoding(self):
        if not self.is_transcoding:
            return

        if not messagebox.askyesno("Abort Batch", "Are you sure you want to terminate all active transcoding jobs?"):
            return

        self.log_to_ui("[Abort] Instant termination signal issued. Halting subprocesses...")
        self.kill_all_active_subprocesses()

        if self.async_loop and self.async_loop.is_running():
            self.async_loop.call_soon_threadsafe(self.cancel_active_async_tasks)

    def cancel_active_async_tasks(self):
        for task in self.async_tasks:
            task.cancel()

    def kill_all_active_subprocesses(self):
        with self.pids_lock:
            for pid in list(self.active_pids):
                try:
                    os.kill(pid, signal.SIGTERM)
                    self.log_to_ui(f"[Abort] Terminated subprocess PID: {pid}")
                except ProcessLookupError:
                    pass
                except Exception as err:
                    self.log_to_ui(f"[Abort] Error halting process {pid}: {err}")
            self.active_pids.clear()

    def setup_signals(self):
        try:
            signal.signal(signal.SIGINT, self.handle_os_shutdown)
            signal.signal(signal.SIGTERM, self.handle_os_shutdown)
        except ValueError:
            pass

    def handle_os_shutdown(self, signum, frame):
        print(f"\n[OS Signal] Intercepted signal ({signum}). Terminating children instantly...")
        with self.pids_lock:
            for pid in list(self.active_pids):
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
        sys.exit(signum)

    def run_asyncio_loop(self):
        self.async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.async_loop)

        try:
            self.async_loop.run_until_complete(
                self.async_batch_transcode(
                    self.GPU_BRAND,
                    self.CODEC_MODE,
                    self.SRC_DIR,
                    self.PARENT_DST_DIR,
                    self.FINAL_DST_DIR,
                    self.MAX_JOBS,
                    self.ACCEL_METHOD,
                    self.DRI_DEVICE,
                    self.COMPRESSION_PRESET,
                    self.RESOLVED_QUALITY,
                    self.FILE_QUEUE,
                    self.TOTAL_FILES,
                    self.LOG_DIR,
                )
            )
        except asyncio.CancelledError:
            self.log_to_ui("[Batch] Asyncio batch processing aborted cleanly.")
        finally:
            self.async_loop.close()
            self.async_loop = None
            self.ui_msg_queue.put(("batch_finished", None))

    async def async_batch_transcode(
        self,
        GPU_BRAND,
        CODEC_MODE,
        SRC_DIR,
        PARENT_DST_DIR,
        FINAL_DST_DIR,
        MAX_JOBS,
        ACCEL_METHOD,
        DRI_DEVICE,
        COMPRESSION_PRESET,
        RESOLVED_QUALITY,
        FILE_QUEUE,
        TOTAL_FILES,
        LOG_DIR,
    ):
        q = asyncio.Queue()
        for idx, filepath in enumerate(FILE_QUEUE, start=1):
            await q.put((idx, filepath))

        num_workers = min(MAX_JOBS, len(FILE_QUEUE))
        self.async_tasks = [
            asyncio.create_task(
                self.transcode_worker(
                    q,
                    CODEC_MODE,
                    FINAL_DST_DIR,
                    ACCEL_METHOD,
                    DRI_DEVICE,
                    COMPRESSION_PRESET,
                    RESOLVED_QUALITY,
                    TOTAL_FILES,
                    LOG_DIR,
                )
            )
            for _ in range(num_workers)
        ]

        await asyncio.gather(*self.async_tasks)

    async def transcode_worker(
        self,
        q: asyncio.Queue,
        CODEC_MODE,
        FINAL_DST_DIR,
        ACCEL_METHOD,
        DRI_DEVICE,
        COMPRESSION_PRESET,
        RESOLVED_QUALITY,
        TOTAL_FILES,
        LOG_DIR,
    ):
        while not q.empty():
            try:
                idx, INPUT_FILE = await q.get()
            except asyncio.CancelledError:
                break

            CURRENT_FILE_INDEX = idx
            filename = os.path.basename(INPUT_FILE)
            base_name, _ = os.path.splitext(filename)
            OUTPUT_FILE = os.path.join(FINAL_DST_DIR, f"{base_name}.mkv")

            JOB_START_TIME = time.time()

            if os.path.exists(OUTPUT_FILE):
                self.ui_msg_queue.put(("log", f"[Skip] File {CURRENT_FILE_INDEX}/{TOTAL_FILES}: '{filename}' exists. Skipping."))
                self.ui_msg_queue.put(("skip_incr", None))
                q.task_done()
                continue

            LOG_FILE = os.path.join(LOG_DIR, f"job_{CURRENT_FILE_INDEX}_{base_name}.log")
            cmd = build_ffmpeg_command(
                input_file=INPUT_FILE,
                output_file=OUTPUT_FILE,
                codec_mode=CODEC_MODE,
                accel_method=ACCEL_METHOD,
                dri_device=DRI_DEVICE,
                compression_preset=COMPRESSION_PRESET,
                resolved_quality=RESOLVED_QUALITY,
            )

            self.ui_msg_queue.put(("log", f"[Active] Running {CURRENT_FILE_INDEX}/{TOTAL_FILES}: '{filename}'"))

            proc = None
            try:
                with open(LOG_FILE, "w") as log_fp:
                    log_fp.write(f"FFmpeg Shell Construction Command:\n{' '.join(cmd)}\n\n")
                    log_fp.flush()

                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=log_fp,
                        stderr=log_fp,
                    )

                    with self.pids_lock:
                        self.active_pids.add(proc.pid)

                    return_code = await proc.wait()

                    with self.pids_lock:
                        self.active_pids.discard(proc.pid)

                job_duration = time.time() - JOB_START_TIME
                if return_code == 0:
                    self.ui_msg_queue.put(("log", f"[Success] File {CURRENT_FILE_INDEX}/{TOTAL_FILES}: '{filename}' completed in {job_duration:.2f}s"))
                    self.ui_msg_queue.put(("pass_incr", None))
                else:
                    self.ui_msg_queue.put(("log", f"[Failure] File {CURRENT_FILE_INDEX}/{TOTAL_FILES}: '{filename}' exited with error code {return_code}. Log: {LOG_FILE}"))
                    self.ui_msg_queue.put(("fail_incr", None))
                    if os.path.exists(OUTPUT_FILE):
                        try:
                            os.remove(OUTPUT_FILE)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                with self.pids_lock:
                    if proc is not None and proc.returncode is None:
                        try:
                            proc.terminate()
                            await proc.wait()
                        except Exception:
                            pass
                q.task_done()
                raise
            except Exception as err:
                self.ui_msg_queue.put(("log", f"[Error] File {CURRENT_FILE_INDEX}/{TOTAL_FILES} encountered error: {err}"))
                self.ui_msg_queue.put(("fail_incr", None))
                if os.path.exists(OUTPUT_FILE):
                    try:
                        os.remove(OUTPUT_FILE)
                    except Exception:
                        pass

            q.task_done()

    def poll_ui_queue(self):
        while True:
            try:
                msg_type, info = self.ui_msg_queue.get_nowait()
            except queue.Empty:
                break

            if msg_type == "log":
                self.log_to_ui(info)
            elif msg_type == "pass_incr":
                self.PASS_COUNT += 1
                self.lbl_success.config(text=f"Success: {self.PASS_COUNT}")
                self.refresh_progress()
            elif msg_type == "fail_incr":
                self.FAIL_COUNT += 1
                self.lbl_failed.config(text=f"Failed: {self.FAIL_COUNT}")
                self.refresh_progress()
            elif msg_type == "skip_incr":
                self.SKIP_COUNT += 1
                self.lbl_skipped.config(text=f"Skipped: {self.SKIP_COUNT}")
                self.refresh_progress()
            elif msg_type == "batch_finished":
                self.finalize_active_batch()

            self.ui_msg_queue.task_done()

        if self.is_transcoding and self.BATCH_START_TIME > 0.0:
            elapsed = time.time() - self.BATCH_START_TIME
            self.lbl_duration.config(text=f"Elapsed Time: {elapsed:.1f}s")

        self.root.after(100, self.poll_ui_queue)

    def refresh_progress(self):
        processed = self.PASS_COUNT + self.FAIL_COUNT + self.SKIP_COUNT
        if self.TOTAL_FILES > 0:
            pct = (processed / self.TOTAL_FILES) * 100
            self.progress_bar["value"] = pct
            self.lbl_pct.config(text=f"{pct:.1f}% ({processed}/{self.TOTAL_FILES})")

    def finalize_active_batch(self):
        self.is_transcoding = False
        self.toggle_inputs_state(True)
        total_time = time.time() - self.BATCH_START_TIME
        self.log_to_ui(f"[Finished] Process Complete. Success: {self.PASS_COUNT}, Failures: {self.FAIL_COUNT}, Skips: {self.SKIP_COUNT}")
        self.log_to_ui(f"[Finished] Total Duration: {total_time:.2f}s")
        messagebox.showinfo(
            "Batch Finished",
            f"Execution finished.\n\n"
            f"Success: {self.PASS_COUNT}\n"
            f"Failed: {self.FAIL_COUNT}\n"
            f"Skipped: {self.SKIP_COUNT}\n"
            f"Duration: {total_time:.1f}s"
        )

    def create_widgets(self):
        style = ttk.Style()
        style.theme_use("clam")

        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        lbl_title = ttk.Label(
            main_frame,
            text="Modular Hardware Accelerated Video Transcoder",
            font=("Helvetica", 14, "bold")
        )
        lbl_title.pack(anchor=tk.W, pady=(0, 10))

        pnl_paths = ttk.LabelFrame(main_frame, text="Directory Validation & Paths", padding="10")
        pnl_paths.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(pnl_paths, text="Source Folder:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.ent_src = ttk.Entry(pnl_paths, textvariable=self.SRC_DIR_VAR, width=65)
        self.ent_src.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=2)
        self.btn_src = ttk.Button(pnl_paths, text="Browse", command=self.browse_src_dir)
        self.btn_src.grid(row=0, column=2, sticky=tk.E, pady=2)

        ttk.Label(pnl_paths, text="Target Parent:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.ent_dst = ttk.Entry(pnl_paths, textvariable=self.PARENT_DST_DIR_VAR, width=65)
        self.ent_dst.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=2)
        self.btn_dst = ttk.Button(pnl_paths, text="Browse", command=self.browse_dst_dir)
        self.btn_dst.grid(row=1, column=2, sticky=tk.E, pady=2)

        pnl_paths.columnconfigure(1, weight=1)

        pnl_hw = ttk.LabelFrame(main_frame, text="Hardware Platform Configuration", padding="10")
        pnl_hw.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(pnl_hw, text="GPU brand:").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.cmb_gpu = ttk.Combobox(
            pnl_hw,
            textvariable=self.GPU_BRAND_VAR,
            values=self.get_available_gpu_brands(),
            state="readonly",
            width=15,
        )
        self.cmb_gpu.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(pnl_hw, text="Codec mode:").grid(row=0, column=2, sticky=tk.W, pady=2, padx=(20, 0))
        self.cmb_codec = ttk.Combobox(
            pnl_hw,
            textvariable=self.CODEC_MODE_VAR,
            values=["HEVC", "H264"],
            state="readonly",
            width=15,
        )
        self.cmb_codec.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)

        ttk.Label(pnl_hw, text="API:").grid(row=0, column=4, sticky=tk.W, pady=2, padx=(20, 0))
        self.cmb_accel = ttk.Combobox(
            pnl_hw,
            textvariable=self.ACCEL_METHOD_VAR,
            values=["VAAPI"],
            state="readonly",
            width=10,
        )
        self.cmb_accel.grid(row=0, column=5, sticky=tk.W, padx=5, pady=2)

        self.lbl_accel_text = ttk.Label(pnl_hw, text="NVENC", font=("Helvetica", 9, "bold"))
        self.lbl_accel_text.grid(row=0, column=5, sticky=tk.W, padx=5, pady=2)
        self.lbl_accel_text.grid_remove()

        ttk.Label(pnl_hw, text="Max Concurrency:").grid(row=0, column=6, sticky=tk.W, pady=2, padx=(20, 0))
        self.spin_max_jobs = tk.Spinbox(
            pnl_hw,
            from_=1,
            to=16,
            textvariable=self.MAX_CONCURRENCY_VAR,
            width=10,
        )
        self.spin_max_jobs.grid(row=0, column=7, sticky=tk.W, padx=5, pady=2)

        ttk.Label(pnl_hw, text="Preset:").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.ent_preset = ttk.Entry(pnl_hw, textvariable=self.PRESET_VAR, width=15)
        self.ent_preset.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(pnl_hw, text="Quality Target:").grid(row=1, column=2, sticky=tk.W, pady=2, padx=(20, 0))
        self.spin_quality = tk.Spinbox(
            pnl_hw,
            from_=0,
            to=255,
            textvariable=self.QUALITY_TARGET_VAR,
            width=10,
        )
        self.spin_quality.grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)

        self.lbl_preset_scale = ttk.Label(pnl_hw, text="", font=("Helvetica", 9))
        self.lbl_preset_scale.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=2)

        self.lbl_quality_scale = ttk.Label(pnl_hw, text="", font=("Helvetica", 9))
        self.lbl_quality_scale.grid(row=2, column=2, columnspan=6, sticky=tk.W, pady=2)

        info_frame = ttk.Frame(pnl_hw, padding=(0, 5))
        info_frame.grid(row=3, column=0, columnspan=6, sticky=tk.W, pady=(5, 0))

        self.lbl_accel = ttk.Label(info_frame, text="API Method: Unknown", font=("Helvetica", 9, "bold"))
        self.lbl_accel.pack(side=tk.LEFT, padx=(0, 15))

        self.lbl_warning = ttk.Label(pnl_hw, text="", font=("Helvetica", 9, "italic"))
        self.lbl_warning.grid(row=4, column=0, columnspan=4, sticky=tk.W, pady=(2, 0))

        pnl_ctrl = ttk.LabelFrame(main_frame, text="Process Execution & Statistics", padding="10")
        pnl_ctrl.pack(fill=tk.X, pady=(0, 10))

        btn_box = ttk.Frame(pnl_ctrl)
        btn_box.pack(fill=tk.X, pady=(0, 5))

        self.btn_scan = ttk.Button(btn_box, text="Scan Directory", command=self.scan_source_directory)
        self.btn_scan.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_start = ttk.Button(btn_box, text="Start Transcoding", command=self.start_transcoding, style="Accent.TButton")
        self.btn_start.pack(side=tk.LEFT, padx=5)

        self.btn_abort = ttk.Button(btn_box, text="Abort Job", command=self.abort_transcoding, state="disabled")
        self.btn_abort.pack(side=tk.LEFT, padx=5)

        stats_frame = ttk.Frame(pnl_ctrl)
        stats_frame.pack(fill=tk.X, pady=5)

        self.lbl_total_files = ttk.Label(stats_frame, text="Discovered Files: 0", font=("Helvetica", 9))
        self.lbl_total_files.pack(side=tk.LEFT, padx=(0, 20))

        self.lbl_success = ttk.Label(stats_frame, text="Success: 0", foreground="green", font=("Helvetica", 9))
        self.lbl_success.pack(side=tk.LEFT, padx=20)

        self.lbl_failed = ttk.Label(stats_frame, text="Failed: 0", foreground="red", font=("Helvetica", 9))
        self.lbl_failed.pack(side=tk.LEFT, padx=20)

        self.lbl_skipped = ttk.Label(stats_frame, text="Skipped: 0", foreground="blue", font=("Helvetica", 9))
        self.lbl_skipped.pack(side=tk.LEFT, padx=20)

        self.lbl_duration = ttk.Label(stats_frame, text="Elapsed Time: 0.0s", font=("Helvetica", 9))
        self.lbl_duration.pack(side=tk.RIGHT, padx=(20, 0))

        bar_frame = ttk.Frame(pnl_ctrl)
        bar_frame.pack(fill=tk.X, pady=(5, 0))

        self.progress_bar = ttk.Progressbar(bar_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        self.lbl_pct = ttk.Label(bar_frame, text="0.0% (0/0)", font=("Helvetica", 9, "bold"), width=15, anchor="center")
        self.lbl_pct.pack(side=tk.RIGHT)

        pnl_log = ttk.LabelFrame(main_frame, text="System Log Console", padding="10")
        pnl_log.pack(fill=tk.BOTH, expand=True)

        self.txt_log = scrolledtext.ScrolledText(pnl_log, font=("Courier", 9), state="disabled", wrap=tk.WORD)
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    def toggle_inputs_state(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_src.config(state=state)
        self.btn_dst.config(state=state)
        self.btn_scan.config(state=state)
        self.btn_start.config(state=state)
        self.cmb_gpu.config(state=state)
        self.cmb_codec.config(state=state)
        self.ent_src.config(state=state)
        self.ent_dst.config(state=state)
        self.btn_abort.config(state="normal" if not enabled else "disabled")

    def log_to_ui(self, msg: str):
        if threading.current_thread() is threading.main_thread():
            self.txt_log.config(state="normal")
            self.txt_log.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            self.txt_log.see(tk.END)
            self.txt_log.config(state="disabled")
        else:
            self.ui_msg_queue.put(("log", msg))
