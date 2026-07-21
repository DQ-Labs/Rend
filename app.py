import os
import sys
import math
import time
import threading
import tkinter as tk

import config

# ── Animated Splash ───────────────────────────────────────────────────────────
# Displayed while heavy imports (torch, demucs) load in a background thread.
# Based on the "Rose Orbit" animation from math-curve-loaders (r = cos(kθ)).

class _AnimatedSplash:
    W, H   = 380, 320
    BG     = "#1a1a2e"
    BG_RGB = (26, 26, 46)
    FG_RGB = (0, 255, 255)   # cyan, matches app accent

    # Rose Orbit parameters (math-curve-loaders / Rose Orbit)
    _ORBIT_R    = 7.0
    _DETAIL_AMP = 2.7
    _K          = 7
    _CURVE_SCL  = 3.9
    _PX_SCL     = 2.1        # pixel scale: maps curve units → canvas px
    _N          = 72         # particle count
    _TRAIL      = 0.42       # fraction of orbit covered by the trail
    _DUR_MS     = 5200       # ms per orbit cycle
    _ROT_MS     = 28000      # ms per full slow rotation

    def __init__(self):
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.configure(bg=self.BG)
        self._root.attributes("-topmost", True)
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        self._root.geometry(
            f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 2}"
        )

        c = tk.Canvas(self._root, width=self.W, height=self.H,
                      bg=self.BG, highlightthickness=0)
        c.pack()
        self._canvas = c

        c.create_text(self.W // 2, 40,  text=config.APP_NAME,
                      fill="white",   font=("Helvetica", 28, "bold"))
        c.create_text(self.W // 2, 68,  text=config.APP_TAGLINE,
                      fill="#555555", font=("Helvetica", 11))
        self._status_id = c.create_text(
            self.W // 2, self.H - 26, text="Loading AI models...",
            fill="#444444", font=("Helvetica", 10))

        self._cx = self.W // 2
        self._cy = self.H // 2 + 12

        # Pre-allocate all particle ovals; coords updated every frame
        self._ovals = [
            c.create_oval(0, 0, 1, 1, fill=self.BG, outline="")
            for _ in range(self._N)
        ]

        self._t0      = time.time()
        self._running = True

    # ── helpers ──────────────────────────────────────────────────────────────

    def _lerp_color(self, t: float) -> str:
        """Blend BG→FG by t ∈ [0, 1] (no alpha needed on Canvas)."""
        br, bg_, bb = self.BG_RGB
        fr, fg_, fb = self.FG_RGB
        r = int(br + (fr - br) * t)
        g = int(bg_ + (fg_ - bg_) * t)
        b = int(bb + (fb - bb) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _curve_point(self, progress: float, detail: float, rot: float):
        """Return canvas (x, y) for *progress* ∈ [0, 1] along the rose orbit."""
        t = progress * math.tau
        r = self._ORBIT_R - self._DETAIL_AMP * detail * math.cos(self._K * t)
        scale = self._CURVE_SCL * self._PX_SCL
        return (
            self._cx + math.cos(t + rot) * r * scale,
            self._cy + math.sin(t + rot) * r * scale,
        )

    # ── animation loop ────────────────────────────────────────────────────────

    def _tick(self):
        if not self._running:
            return
        ms = (time.time() - self._t0) * 1000

        head      = (ms % self._DUR_MS) / self._DUR_MS
        detail    = 0.7 + 0.3 * (0.5 + 0.5 * math.cos(ms / 4600 * math.tau))
        rotation  = ms / self._ROT_MS * math.tau

        for i, oval in enumerate(self._ovals):
            frac     = i / self._N                             # 0=head … 1=tail
            progress = (head - frac * self._TRAIL) % 1.0
            x, y     = self._curve_point(progress, detail, rotation)
            opacity  = max(0.0, 1.0 - frac)
            size     = max(0.5, 3.5 * (1.0 - frac * 0.65))
            self._canvas.coords(oval, x - size, y - size, x + size, y + size)
            self._canvas.itemconfig(oval, fill=self._lerp_color(opacity))

        self._root.after(16, self._tick)   # ~60 fps

    # ── public API ────────────────────────────────────────────────────────────

    def wait(self, event: threading.Event):
        """Start animating; block until *event* is set, then destroy."""
        self._tick()

        def _poll():
            if event.is_set():
                self._running = False
                self._root.quit()
            else:
                self._root.after(100, _poll)

        _poll()
        self._root.mainloop()
        self._root.destroy()


# ── Background heavy imports ──────────────────────────────────────────────────

_imports_done = threading.Event()
_import_error: list = [None]   # holds the Exception if any import fails

def _load_heavy():
    try:
        import webbrowser           # noqa: F401
        import customtkinter        # noqa: F401
        import tkinter.filedialog   # noqa: F401
        import tkinter.messagebox   # noqa: F401
        import demucs.api           # noqa: F401
        import rend_core            # noqa: F401  (pulls in torch + soundfile)
    except Exception as exc:
        _import_error[0] = exc
    finally:
        _imports_done.set()   # always unblocks the splash, even on failure

threading.Thread(target=_load_heavy, daemon=True).start()
_AnimatedSplash().wait(_imports_done)

# If a dependency failed to import, tell the user and exit cleanly.
if _import_error[0] is not None:
    import tkinter.messagebox as _mb
    _mb.showerror(
        "Startup Error",
        f"Rend could not load a required library:\n\n{_import_error[0]}\n\n"
        "Try reinstalling the application."
    )
    sys.exit(1)

# All modules are now cached in sys.modules — these re-imports are instant.
import webbrowser
import customtkinter as ctk
from tkinter import filedialog, messagebox
from rend_core import (
    LOG_FILE,
    SeparationThread,
    check_ffmpeg,
    check_online,
    output_folder_for,
    select_device,
)

# ── Startup fixes ─────────────────────────────────────────────────────────────

# Fix Console Crash: Redirect stdout/stderr if None (happens in --noconsole mode)
class DummyStream:
    # Libraries (tqdm, logging) probe streams beyond write/flush
    encoding = "utf-8"
    def write(self, text):
        pass
    def flush(self):
        pass
    def isatty(self):
        return False
    def fileno(self):
        raise OSError("DummyStream has no file descriptor")

if sys.stdout is None:
    sys.stdout = DummyStream()
if sys.stderr is None:
    sys.stderr = DummyStream()

# Fix FFmpeg Path: Add PyInstaller's temp directory to PATH when frozen
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    os.environ["PATH"] = bundle_dir + os.pathsep + os.environ.get("PATH", "")

# Force Dark Mode and Blue Theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class App(ctk.CTk):

    # ── Palette ───────────────────────────────────────────────────────────────
    _WIN_BG     = "#0a0a14"   # near-black canvas
    _HDR_BG     = "#0f0b28"   # deep violet header
    _CARD_BG    = "#111127"   # surface cards
    _CARD_BD    = "#1e1e44"   # card border (idle)
    _CARD_BD_HI = "#5533cc"   # card border (file loaded)
    _ACCENT     = "#6C5CE7"   # primary violet
    _ACCENT_HO  = "#5849BE"   # hover violet
    _DIM        = "#2a2a52"   # muted border / disabled
    _TXT_HI     = "#d4d4f0"   # bright body text
    _TXT_MID    = "#7777aa"   # secondary text
    _TXT_DIM    = "#3a3a66"   # placeholder / label caps
    _STATUS_OK   = "#00c853"  # status light: OK / green
    _STATUS_WARN = "#ff9100"  # status light: warning / amber (e.g. offline)
    _STATUS_ERR  = "#ff3d00"  # status light: error / red
    _ZONE_ICON   = "#2e2e62"  # file zone icon (idle state)

    def __init__(self):
        super().__init__()

        self.title(config.APP_NAME)
        self.geometry("600x720")
        self.resizable(False, False)
        self.configure(fg_color=self._WIN_BG)

        try:
            self.iconbitmap(resource_path("rend.ico"))
        except Exception:
            pass

        self.file_path = None

        self.MODEL_INFO = {
            "htdemucs":    "The Default. Balanced speed and quality.",
            "htdemucs_ft": "Fine-Tuned. Slightly better vocals, but 4× slower.",
            "htdemucs_6s": "Six Stems — Drums, Bass, Vocals, Guitar, Piano, Other.",
            "mdx":         "Classic Model. Trained on MusDB HQ. Good baseline.",
            "mdx_extra":   "High Precision. Extra training data for complex mixes.",
            "mdx_q":       "Quantized. Smaller download, slightly lower quality.",
        }

        self.grid_columnconfigure(0, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=self._HDR_BG, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            hdr, text=f"♪  {config.APP_NAME}",
            font=("Roboto Medium", 36), text_color="white",
        ).grid(row=0, column=0, pady=(28, 4))

        ctk.CTkLabel(
            hdr, text=" ".join(config.APP_TAGLINE.upper()),
            font=("Roboto", 10), text_color="#443377",
        ).grid(row=1, column=0, pady=(0, 22))

        # ── File drop zone ────────────────────────────────────────────────────
        self._file_zone = ctk.CTkFrame(
            self, fg_color=self._CARD_BG, corner_radius=14,
            border_width=2, border_color=self._CARD_BD,
        )
        self._file_zone.grid(row=1, column=0, padx=28, pady=(20, 10), sticky="ew")
        self._file_zone.grid_columnconfigure(0, weight=1)

        self._zone_icon = ctk.CTkLabel(
            self._file_zone, text="♫",
            font=("Helvetica", 40), text_color=self._ZONE_ICON,
        )
        self._zone_icon.grid(row=0, column=0, pady=(22, 2))

        self._zone_text = ctk.CTkLabel(
            self._file_zone, text="Click to select an audio file",
            font=("Roboto", 13), text_color=self._TXT_MID,
        )
        self._zone_text.grid(row=1, column=0, pady=(0, 2))

        self._zone_sub = ctk.CTkLabel(
            self._file_zone, text="MP3  ·  WAV  ·  FLAC",
            font=("Roboto", 11), text_color=self._TXT_DIM,
        )
        self._zone_sub.grid(row=2, column=0, pady=(0, 14))

        self.btn_select = ctk.CTkButton(
            self._file_zone, text="Browse Files",
            command=self.select_file,
            width=130, height=32,
            font=("Roboto", 12),
            fg_color="transparent",
            border_width=1, border_color=self._DIM,
            hover_color="#1a1a38",
            text_color=self._TXT_MID,
            corner_radius=16,
        )
        self.btn_select.grid(row=3, column=0, pady=(0, 22))

        # ── Options card ──────────────────────────────────────────────────────
        card = ctk.CTkFrame(
            self, fg_color=self._CARD_BG, corner_radius=14,
            border_width=1, border_color=self._CARD_BD,
        )
        card.grid(row=2, column=0, padx=28, pady=10, sticky="ew")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text="MODEL",
            font=("Roboto", 9), text_color=self._TXT_DIM,
        ).grid(row=0, column=0, columnspan=2, padx=22, pady=(16, 8), sticky="w")

        ctk.CTkLabel(
            card, text="Engine",
            font=("Roboto", 13), text_color=self._TXT_MID,
        ).grid(row=1, column=0, padx=(22, 10), sticky="w")

        self.opt_model = ctk.CTkOptionMenu(
            card,
            values=["htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx", "mdx_extra", "mdx_q"],
            width=162,
            font=("Roboto", 13),
            fg_color="#1a1a38",
            button_color=self._DIM,
            button_hover_color="#333366",
            dropdown_fg_color="#1a1a38",
            text_color=self._TXT_HI,
            command=self.update_model_desc,
        )
        self.opt_model.grid(row=1, column=1, padx=(0, 22), pady=(0, 4), sticky="e")
        self.opt_model.set("htdemucs")

        self.lbl_model_desc = ctk.CTkLabel(
            card, text=self.MODEL_INFO["htdemucs"],
            font=("Roboto", 12), text_color=self._TXT_MID,
            wraplength=460, anchor="w", justify="left",
        )
        self.lbl_model_desc.grid(row=2, column=0, columnspan=2, padx=22, pady=(0, 14), sticky="w")

        # Divider
        ctk.CTkFrame(card, fg_color=self._CARD_BD, height=1, corner_radius=0).grid(
            row=3, column=0, columnspan=2, padx=22, sticky="ew",
        )

        ctk.CTkLabel(
            card, text="OPTIONS",
            font=("Roboto", 9), text_color=self._TXT_DIM,
        ).grid(row=4, column=0, columnspan=2, padx=22, pady=(12, 8), sticky="w")

        chk_row = ctk.CTkFrame(card, fg_color="transparent")
        chk_row.grid(row=5, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="w")

        self.chk_quality = ctk.CTkCheckBox(
            chk_row, text="High Quality  (Slow)",
            font=("Roboto", 13), text_color=self._TXT_MID,
            fg_color=self._ACCENT, hover_color=self._ACCENT_HO,
            border_color=self._DIM, checkmark_color="white",
        )
        self.chk_quality.grid(row=0, column=0, padx=(0, 28))

        self.chk_karaoke = ctk.CTkCheckBox(
            chk_row, text="Karaoke Mode  (2 Stems)",
            font=("Roboto", 13), text_color=self._TXT_MID,
            fg_color=self._ACCENT, hover_color=self._ACCENT_HO,
            border_color=self._DIM, checkmark_color="white",
        )
        self.chk_karaoke.grid(row=0, column=1)

        # Output format: WAV (float, large, lossless headroom) vs FLAC (24-bit,
        # ~half the size, lossless but clips the karaoke accompaniment sum).
        fmt_row = ctk.CTkFrame(card, fg_color="transparent")
        fmt_row.grid(row=6, column=0, columnspan=2, padx=22, pady=(0, 18), sticky="w")

        ctk.CTkLabel(
            fmt_row, text="Output",
            font=("Roboto", 13), text_color=self._TXT_MID,
        ).grid(row=0, column=0, padx=(0, 14))

        self.seg_format = ctk.CTkSegmentedButton(
            fmt_row,
            values=["WAV", "FLAC"],
            font=("Roboto", 12),
            fg_color="#1a1a38",
            selected_color=self._ACCENT,
            selected_hover_color=self._ACCENT_HO,
            unselected_color="#1a1a38",
            unselected_hover_color="#333366",
            text_color=self._TXT_HI,
            command=self._update_format_hint,
        )
        self.seg_format.grid(row=0, column=1)
        self.seg_format.set("WAV")

        self.lbl_format_hint = ctk.CTkLabel(
            fmt_row, text="Uncompressed · largest files",
            font=("Roboto", 11), text_color=self._TXT_DIM,
        )
        self.lbl_format_hint.grid(row=0, column=2, padx=(14, 0))

        # ── Run button ────────────────────────────────────────────────────────
        self.btn_run = ctk.CTkButton(
            self, text="⚡  SEPARATE STEMS",
            command=self.start_separation,
            state="disabled",
            width=420, height=52,
            font=("Roboto", 15, "bold"),
            fg_color=self._ACCENT,
            hover_color=self._ACCENT_HO,
            text_color="white",
            corner_radius=26,
        )
        self.btn_run.grid(row=3, column=0, pady=(18, 4))

        self.btn_cancel = ctk.CTkButton(
            self, text="✕  Cancel",
            command=self._cancel_separation,
            width=160, height=34,
            font=("Roboto", 13),
            fg_color="transparent",
            border_width=1, border_color="#553333",
            hover_color="#1a0a0a",
            text_color="#cc4444",
            corner_radius=17,
        )
        self.btn_cancel.grid(row=4, column=0, pady=(0, 4))
        self.btn_cancel.grid_remove()  # hidden until processing starts

        # ── Progress area ─────────────────────────────────────────────────────
        prg = ctk.CTkFrame(self, fg_color="transparent")
        prg.grid(row=5, column=0, sticky="ew", padx=36, pady=(8, 0))
        prg.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(
            prg, text="Ready",
            font=("Roboto", 11), text_color=self._TXT_DIM,
        )
        self.lbl_status.grid(row=0, column=0, pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(
            prg, width=500, height=5,
            progress_color=self._ACCENT,
            fg_color="#181830",
            corner_radius=3,
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, pady=(0, 4))

        # ── Status bar ────────────────────────────────────────────────────────
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=6, column=0, sticky="ew", padx=28, pady=(10, 16))
        bar.grid_columnconfigure(2, weight=1)

        self.lbl_ffmpeg = ctk.CTkLabel(
            bar, text="● FFmpeg",
            font=("Roboto", 11), text_color=self._TXT_DIM,
            cursor="hand2",
        )
        self.lbl_ffmpeg.grid(row=0, column=0, padx=(0, 12))
        self.lbl_ffmpeg.bind("<Button-1>", self._on_ffmpeg_click)

        self.lbl_device = ctk.CTkLabel(
            bar, text="● Device",
            font=("Roboto", 11), text_color=self._TXT_DIM,
            cursor="hand2",
        )
        self.lbl_device.grid(row=0, column=1, padx=(0, 12))
        self.lbl_device.bind("<Button-1>", self._on_device_click)

        self.lbl_online = ctk.CTkLabel(
            bar, text="● Online",
            font=("Roboto", 11), text_color=self._TXT_DIM,
        )
        self.lbl_online.grid(row=0, column=2, sticky="w")

        self.lbl_about = ctk.CTkLabel(
            bar, text="About",
            font=("Roboto", 11), text_color=self._TXT_MID,
            cursor="hand2",
        )
        self.lbl_about.grid(row=0, column=3, sticky="e", padx=(0, 16))
        self.lbl_about.bind("<Button-1>", self._show_about)

        self.lbl_attribution = ctk.CTkLabel(
            bar, text="Powered by Demucs",
            font=("Roboto", 11), text_color="#00FFFF",
            cursor="hand2",
        )
        self.lbl_attribution.grid(row=0, column=4, sticky="e")
        self.lbl_attribution.bind("<Button-1>", self.open_attribution)

        self._ffmpeg_ok = None   # None = diagnostics pending, True/False after check
        self._online_ok = None
        self._device = None      # "cuda"/"cpu", resolved by diagnostics
        self._about_win = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start Pre-Flight Check
        threading.Thread(target=self.run_diagnostics, daemon=True).start()

    def run_diagnostics(self):
        ffmpeg_ok = check_ffmpeg()
        online_ok = check_online()
        device = select_device()

        # Schedule UI Update on Main Thread
        self.after(1000, lambda: self.update_status_lights(ffmpeg_ok, online_ok, device))

    def update_status_lights(self, ffmpeg_ok, online_ok, device):
        self._ffmpeg_ok = ffmpeg_ok
        self._online_ok = online_ok
        self._device = device
        self.lbl_ffmpeg.configure(text_color=self._STATUS_OK if ffmpeg_ok else self._STATUS_ERR)
        self.lbl_online.configure(text_color=self._STATUS_OK if online_ok else self._STATUS_WARN)
        # GPU is a green "bonus"; CPU is the normal, expected state (neutral).
        if device == "cuda":
            self.lbl_device.configure(text="● GPU", text_color=self._STATUS_OK)
        else:
            self.lbl_device.configure(text="● CPU", text_color=self._TXT_MID)

    def _on_ffmpeg_click(self, event):
        if self._ffmpeg_ok is None:
            return  # diagnostics still running
        if self._ffmpeg_ok:
            messagebox.showinfo("FFmpeg", "FFmpeg is installed and working correctly.")
        elif getattr(sys, 'frozen', False):
            messagebox.showwarning(
                "FFmpeg Not Found",
                "FFmpeg could not be found inside the app bundle.\n\n"
                "This is unexpected — please report it as a bug on GitHub.",
            )
        else:
            messagebox.showwarning(
                "FFmpeg Not Found",
                "FFmpeg could not be found on your PATH or in the project root.\n\n"
                "Place ffmpeg.exe and ffprobe.exe in the same folder as app.py "
                "and restart.\n\n"
                "Windows builds: gyan.dev/ffmpeg/builds",
            )

    def _on_device_click(self, event):
        if self._device is None:
            return  # diagnostics still running
        if self._device == "cuda":
            messagebox.showinfo(
                "Device: GPU",
                "An NVIDIA (CUDA) GPU was detected and will be used for "
                "separation — several times faster than CPU.",
            )
        else:
            messagebox.showinfo(
                "Device: CPU",
                "No CUDA GPU was detected, so separation runs on the CPU.\n\n"
                "This is fully supported — GPU acceleration only requires an "
                "NVIDIA card with a CUDA-enabled build of PyTorch.",
            )

    def _update_format_hint(self, choice):
        hints = {
            "WAV":  "Uncompressed · largest files",
            "FLAC": "Lossless · ~half the size",
        }
        self.lbl_format_hint.configure(text=hints.get(choice, ""))

    def open_attribution(self, event):
        webbrowser.open("https://github.com/adefossez/demucs")

    def _show_about(self, event=None):
        if self._about_win is not None and self._about_win.winfo_exists():
            self._about_win.lift()
            self._about_win.focus_force()
            return

        win = ctk.CTkToplevel(self, fg_color=self._WIN_BG)
        self._about_win = win
        win.title(f"About {config.APP_NAME}")
        win.geometry("420x470")
        win.resizable(False, False)
        win.transient(self)

        ctk.CTkLabel(
            win, text=config.APP_NAME,
            font=("Roboto Medium", 26), text_color="white",
        ).pack(pady=(24, 0))
        ctk.CTkLabel(
            win, text=f"v{config.APP_VERSION}",
            font=("Roboto", 12), text_color=self._ACCENT,
        ).pack()
        ctk.CTkLabel(
            win, text=config.APP_TAGLINE,
            font=("Roboto", 11), text_color=self._TXT_MID,
        ).pack(pady=(0, 12))

        # Health: mirrors the main-window status lights
        if self._ffmpeg_ok is None:
            health_text, health_color = "Checking environment…", self._TXT_DIM
        elif self._ffmpeg_ok:
            health_text, health_color = "● FFmpeg OK", self._STATUS_OK
        else:
            health_text, health_color = "● FFmpeg missing", self._STATUS_ERR
        if self._online_ok is False:
            health_text += "    ● Offline (first model download needs internet)"
        ctk.CTkLabel(
            win, text=health_text,
            font=("Roboto", 11), text_color=health_color,
        ).pack(pady=(0, 10))

        credits_frame = ctk.CTkFrame(
            win, fg_color=self._CARD_BG, corner_radius=10,
            border_width=1, border_color=self._CARD_BD,
        )
        credits_frame.pack(padx=24, pady=(0, 12), fill="x")
        ctk.CTkLabel(
            credits_frame, text="BUILT WITH",
            font=("Roboto", 9), text_color=self._TXT_DIM,
        ).pack(anchor="w", padx=16, pady=(10, 2))
        for name, license_name, url in config.CREDITS:
            lbl = ctk.CTkLabel(
                credits_frame, text=f"{name}  ·  {license_name}",
                font=("Roboto", 11), text_color=self._TXT_MID,
                cursor="hand2",
            )
            lbl.pack(anchor="w", padx=16)
            lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        ctk.CTkLabel(credits_frame, text="", font=("Roboto", 2)).pack(pady=(0, 6))

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=(0, 8))
        ctk.CTkButton(
            btn_row, text="Report a Bug",
            command=lambda: webbrowser.open(config.BUG_REPORT_URL),
            width=130, height=30, font=("Roboto", 12),
            fg_color=self._ACCENT, hover_color=self._ACCENT_HO,
        ).grid(row=0, column=0, padx=6)
        ctk.CTkButton(
            btn_row, text="GitHub",
            command=lambda: webbrowser.open(config.REPO_URL),
            width=130, height=30, font=("Roboto", 12),
            fg_color="transparent", border_width=1,
            border_color=self._DIM, hover_color="#1a1a38",
            text_color=self._TXT_MID,
        ).grid(row=0, column=1, padx=6)

        ctk.CTkLabel(
            win, text=config.COPYRIGHT,
            font=("Roboto", 10), text_color=self._TXT_DIM,
        ).pack()
        ctk.CTkLabel(
            win, text=f"Error log: {LOG_FILE}",
            font=("Roboto", 9), text_color=self._TXT_DIM,
        ).pack(pady=(2, 12))

    def _on_close(self):
        if hasattr(self, 'worker') and self.worker.is_alive():
            if not messagebox.askyesno(
                "Separation in progress",
                "A separation is still running.\n\nQuit anyway? The output will be incomplete.",
                icon="warning",
            ):
                return
        self.destroy()

    def select_file(self):
        file = filedialog.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav *.flac")])
        if file:
            self.file_path = file
            fname = os.path.basename(file)
            short = fname if len(fname) <= 42 else fname[:39] + "…"
            self._zone_icon.configure(text="✓", text_color=self._ACCENT)
            self._zone_text.configure(text=short, text_color=self._TXT_HI)
            self._zone_sub.configure(
                text=os.path.splitext(fname)[1].upper().lstrip(".") + " file selected",
                text_color=self._TXT_MID,
            )
            self._file_zone.configure(border_color=self._CARD_BD_HI)
            self.btn_select.configure(text="Change File")
            self.btn_run.configure(state="normal")

    def start_separation(self):
        if not self.file_path: return

        self.btn_run.configure(state="disabled")
        self.btn_select.configure(state="disabled")
        self.chk_quality.configure(state="disabled")
        self.chk_karaoke.configure(state="disabled")
        self.opt_model.configure(state="disabled")
        self.seg_format.configure(state="disabled")
        self.progress_bar.set(0)
        self.btn_cancel.grid()  # show cancel button

        output_dir = output_folder_for(self.file_path)

        # Get Options
        model = self.opt_model.get()
        shifts = 2 if self.chk_quality.get() == 1 else 1
        two_stems = self.chk_karaoke.get() == 1
        output_format = self.seg_format.get().lower()  # "WAV"/"FLAC" -> "wav"/"flac"

        self._stop_event = threading.Event()
        self.worker = SeparationThread(
            input_file=self.file_path,
            output_folder=output_dir,
            model_name=model,
            shifts=shifts,
            two_stems=two_stems,
            callback=self.update_ui,
            stop_event=self._stop_event,
            device=self._device,  # None until diagnostics finish → auto-detect in the thread
            output_format=output_format,
        )
        self.worker.daemon = True
        self.worker.start()

    def update_ui(self, status_text, progress_val):
        # Called from a background thread — marshal all UI work to the main thread
        self.after(0, lambda s=status_text, v=progress_val: self._apply_update(s, v))

    def _apply_update(self, status_text, progress_val):
        self.lbl_status.configure(text=status_text)
        self.progress_bar.set(min(max(progress_val, 0.0), 1.0))

        if status_text == "Done!":
            output_dir = output_folder_for(self.file_path)
            self.reset_ui()
            if messagebox.askyesno("Done!", f"Separation complete!\n\nOpen output folder?"):
                os.startfile(output_dir)
        elif status_text == "Cancelled.":
            self.lbl_status.configure(text="Cancelled")
            self.after(1200, self._deferred_reset)
        elif status_text.startswith("Error"):
            messagebox.showerror("Error", f"{status_text}\n\nDetails were saved to:\n{LOG_FILE}")
            self.reset_ui()

    def reset_ui(self):
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Ready")
        self.btn_cancel.configure(state="normal")  # re-arm for next run
        self.btn_cancel.grid_remove()              # hide cancel button
        self.btn_select.configure(state="normal")
        self.chk_quality.configure(state="normal")
        self.chk_karaoke.configure(state="normal")
        self.opt_model.configure(state="normal")
        self.seg_format.configure(state="normal")
        self._reset_file_zone()

    def _reset_file_zone(self):
        self.file_path = None
        self._zone_icon.configure(text="♫", text_color=self._ZONE_ICON)
        self._zone_text.configure(text="Click to select an audio file", text_color=self._TXT_MID)
        self._zone_sub.configure(text="MP3  ·  WAV  ·  FLAC", text_color=self._TXT_DIM)
        self._file_zone.configure(border_color=self._CARD_BD)
        self.btn_select.configure(text="Browse Files")
        self.btn_run.configure(state="disabled")

    def _deferred_reset(self):
        try:
            self.reset_ui()
        except tk.TclError:
            pass  # window was closed during the post-cancel delay

    def _cancel_separation(self):
        self.btn_cancel.configure(state="disabled")
        self._stop_event.set()

    def update_model_desc(self, choice):
        description = self.MODEL_INFO.get(choice, "")
        self.lbl_model_desc.configure(text=description)
        # htdemucs_6s uses different stem names — Karaoke Mode is incompatible.
        # Disable the checkbox (and clear it) so the user can't accidentally select both.
        if choice == "htdemucs_6s":
            self.chk_karaoke.deselect()
            self.chk_karaoke.configure(state="disabled")
        else:
            self.chk_karaoke.configure(state="normal")

if __name__ == "__main__":
    app = App()
    app.mainloop()
