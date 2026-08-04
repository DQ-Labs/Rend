import os
import sys
import gc
import math
import time
import threading
import traceback
import tkinter as tk

import config
import registry   # stdlib-only model catalog: safe to import before the splash

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
        # Pending after() ids, so they can be cancelled before the interpreter
        # is torn down (see close()).
        self._tick_id = None
        self._poll_id = None

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

        self._tick_id = self._root.after(16, self._tick)   # ~60 fps

    # ── public API ────────────────────────────────────────────────────────────

    def wait(self, event: threading.Event):
        """Start animating; block until *event* is set, then tear down."""
        self._tick()

        def _poll():
            if event.is_set():
                self._running = False
                self._root.quit()
            else:
                self._poll_id = self._root.after(100, _poll)

        _poll()
        self._root.mainloop()
        self.close()

    def close(self):
        """Cancel pending callbacks and destroy the splash's interpreter.

        quit() only exits mainloop — it leaves already-queued after() callbacks
        in the Tcl event queue, and destroying the interpreter with a _tick
        still pending produces `invalid command name "..._tick"`. Cancel them
        first so the teardown is clean.
        """
        for attr in ("_tick_id", "_poll_id"):
            after_id = getattr(self, attr)
            if after_id is not None:
                try:
                    self._root.after_cancel(after_id)
                except tk.TclError:
                    pass          # already fired or the interpreter is gone
                setattr(self, attr, None)
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

# The splash gets its own Tcl interpreter, and that interpreter MUST be
# finalized here, on the main thread. Left as garbage for CPython to collect
# whenever, it is freed by whichever thread happens to trigger the next
# collection — and the separation worker importing demucs allocates more than
# enough to be that thread. Tcl detects the cross-thread teardown and aborts
# the whole process with "Tcl_AsyncDelete: async handler deleted by the wrong
# thread": no Python traceback, nothing in the error log, the window simply
# vanishes the moment Separate is pressed. Holding a reference, closing it
# explicitly and collecting right here keeps the teardown on this thread.
_splash = _AnimatedSplash()
_splash.wait(_imports_done)
del _splash
gc.collect()

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
from PIL import Image
from tkinter import filedialog, messagebox, font as tkfont
from rend_core import (
    LOG_FILE,
    SeparationThread,
    available_models,
    check_ffmpeg,
    check_online,
    log_error,
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

# Make the adjacent ffmpeg discoverable through PATH.
#
# Rend's own ffmpeg_exe() searches PATH -> frozen bundle -> project root, but
# demucs resolves ffmpeg through PATH *only*, and when it finds none it falls
# back to torchaudio.load — which on torch 2.9 raises "TorchCodec is required".
# So a source install with ffmpeg.exe in the project root, exactly as the README
# instructs, failed on every Demucs separation. Prepending the app directory
# covers the frozen bundle (_MEIPASS) and the source checkout alike.
_app_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = _app_dir + os.pathsep + os.environ.get("PATH", "")

# Force Dark Mode and Blue Theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def ui_font():
    """The first available UI face, best first.

    Every earlier release asked for "Roboto"/"Helvetica", neither of which ships
    with Windows, so Tk silently substituted Arial and the app never rendered in
    its intended typeface. Segoe UI Variable Display ships with Windows 11 and
    plain Segoe UI with Windows 10, so this resolves without bundling a font.
    """
    families = set(tkfont.families())
    for family in ("Segoe UI Variable Display", "Segoe UI", "Arial"):
        if family in families:
            return family
    return "Arial"


def load_icon(name, size, variant="accent"):
    """Load assets/<variant>/<name> as a CTkImage at *size*.

    Sources are exported at 2x the display size, so CTkImage downsamples and
    stays crisp on HiDPI displays. Callers must keep a reference — an image
    that gets garbage collected renders as a blank widget.
    """
    path = resource_path(os.path.join("assets", variant, name))
    image = Image.open(path)
    return ctk.CTkImage(light_image=image, dark_image=image, size=size)

class App(ctk.CTk):

    # ── Palette ───────────────────────────────────────────────────────────────
    _WIN_BG     = "#0B0B12"   # near-black canvas
    _HDR_BG     = "#0E0E1A"   # header band, a shade above the canvas
    _CARD_BG    = "#14141F"   # surface cards
    _CARD_WELL  = "#1A1A28"   # inset wells inside a card
    _CARD_BD    = "#23233A"   # card border (idle)
    _CARD_BD_HI = "#3A2F7A"   # card border (file loaded)
    _ACCENT     = "#6C5CE7"   # primary violet
    _ACCENT_HO  = "#5849BE"   # hover violet
    _DIM        = "#33334F"   # muted border / disabled
    _TXT_HI     = "#E4E4F2"   # bright body text
    _TXT_MID    = "#8A8AB0"   # secondary text
    _TXT_DIM    = "#4A4A6A"   # placeholder / label caps
    _STATUS_OK   = "#00c853"  # status light: OK / green
    _STATUS_WARN = "#ff9100"  # status light: warning / amber (e.g. offline)
    _STATUS_ERR  = "#ff3d00"  # status light: error / red

    _PAD = 24                 # outer gutter; inner steps are 8 / 16

    # Class-level so report_callback_exception is safe even if a callback fires
    # before __init__ has finished.
    _reported_ui_error = False

    # Credit follows the engine actually selected — Demucs and the vendored
    # Mel-Band RoFormer are separate projects under separate copyrights.
    _ENGINE_CREDIT = {
        "demucs":   ("Powered by Demucs", "https://github.com/adefossez/demucs"),
        "roformer": ("Powered by Mel-Band RoFormer", "https://github.com/lucidrains/BS-RoFormer"),
    }

    # Each engine owns an accent, so which one is selected is readable at a
    # glance without reading the model name.
    _ENGINE_ACCENT = {"demucs": "#6C5CE7", "roformer": "#22D3A6"}

    def __init__(self):
        super().__init__()

        self.title(config.APP_NAME)
        self.resizable(False, False)
        self.configure(fg_color=self._WIN_BG)
        self.F = ui_font()

        try:
            self.iconbitmap(resource_path("rend.ico"))
        except Exception:
            pass

        self.file_path = None

        # The picker is driven entirely by the registry (via rend_core, which
        # filters out models whose engine this build can't run). Labels carry a
        # download badge for weights that aren't on disk yet, so they change as
        # models arrive — _model_by_label is rebuilt by _refresh_model_menu().
        self._models = available_models()
        self._model_by_label = {}
        self._selected_id = self._models[0].id

        # Icons are kept on self deliberately: a CTkImage that gets garbage
        # collected renders as a blank widget.
        self._ico_wordmark = load_icon("rend_wordmark.png", (150, 38))
        self._ico_drop     = load_icon("dropzone_glyph.png", (84, 84))
        self._ico_engine   = {
            "demucs":   load_icon("engine_demucs.png", (22, 22)),
            "roformer": load_icon("engine_roformer.png", (22, 22)),
        }
        self._ico_mic      = load_icon("option_mic.png", (18, 18), "white")
        self._ico_sparkle  = load_icon("option_sparkle.png", (18, 18), "white")
        self._ico_file     = load_icon("option_file.png", (18, 18), "white")
        self._ico_bolt     = load_icon("action_bolt.png", (18, 18), "white")
        self._ico_download = load_icon("download_arrow.png", (13, 13), "white")

        self._ffmpeg_ok = None   # None = diagnostics pending, True/False after check
        self._online_ok = None
        self._device = None      # "cuda"/"cpu", resolved by diagnostics
        self._about_win = None
        self._attribution_url = self._ENGINE_CREDIT["demucs"][1]

        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_body()
        self._build_options()
        self._build_action()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Populate the picker and everything that follows from it (description,
        # meta line, Karaoke availability, engine accent and credit).
        self._refresh_model_menu()

        # Size to what the layout actually needs rather than a hardcoded height.
        # Font metrics differ between machines, and a fixed number is what left
        # the status row clipped off the bottom in every release up to 1.3.0.
        #
        # winfo_reqheight() reports real pixels, which already include CTk's
        # widget scaling, while CTk.geometry() applies window scaling to
        # whatever it is given. Feeding one into the other double-scales the
        # window — 900x600 becomes 1125x940 on a 125% display. Convert back to
        # logical units so CTk's own scaling is applied exactly once.
        self.update_idletasks()
        scaling = ctk.ScalingTracker.get_widget_scaling(self) or 1.0
        self.geometry(f"900x{math.ceil(self.winfo_reqheight() / scaling)}")

        # Start Pre-Flight Check
        threading.Thread(target=self.run_diagnostics, daemon=True).start()

    # ── Header: identity left, environment right ──────────────────────────────
    # The status lights live up here rather than in a strip along the bottom.
    # Previously an oversized header wasted the top of the window while a
    # cramped status row cluttered the bottom; merging them fixed both.

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=self._HDR_BG, corner_radius=0, height=64)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.grid(row=0, column=0, padx=(self._PAD, 0), pady=13, sticky="w")
        ctk.CTkLabel(left, image=self._ico_wordmark, text="").grid(row=0, column=0)
        ctk.CTkLabel(
            left, text=config.APP_TAGLINE.upper(),
            font=(self.F, 9), text_color=self._TXT_DIM,
        ).grid(row=0, column=1, padx=(12, 0), pady=(4, 0))

        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.grid(row=0, column=2, padx=(0, self._PAD), pady=13, sticky="e")

        self.lbl_ffmpeg = ctk.CTkLabel(
            right, text="● FFmpeg", font=(self.F, 11),
            text_color=self._TXT_DIM, cursor="hand2")
        self.lbl_ffmpeg.grid(row=0, column=0, padx=(0, 14))
        self.lbl_ffmpeg.bind("<Button-1>", self._on_ffmpeg_click)

        self.lbl_device = ctk.CTkLabel(
            right, text="● Device", font=(self.F, 11),
            text_color=self._TXT_DIM, cursor="hand2")
        self.lbl_device.grid(row=0, column=1, padx=(0, 14))
        self.lbl_device.bind("<Button-1>", self._on_device_click)

        self.lbl_online = ctk.CTkLabel(
            right, text="● Online", font=(self.F, 11), text_color=self._TXT_DIM)
        self.lbl_online.grid(row=0, column=2, padx=(0, 16))

        self.lbl_about = ctk.CTkLabel(
            right, text="About", font=(self.F, 11),
            text_color=self._TXT_MID, cursor="hand2")
        self.lbl_about.grid(row=0, column=3)
        self.lbl_about.bind("<Button-1>", self._show_about)

    # ── Body: file on the left, model on the right ────────────────────────────
    # Two columns rather than one stacked run: the model description and meta
    # line no longer sit under a full-width dropdown, which is most of what
    # made the old window so tall.

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew", padx=self._PAD, pady=(self._PAD, 0))
        body.grid_columnconfigure(0, weight=42, uniform="body")
        body.grid_columnconfigure(1, weight=58, uniform="body")

        # File drop zone
        self._file_zone = ctk.CTkFrame(
            body, fg_color=self._CARD_BG, corner_radius=14,
            border_width=1, border_color=self._CARD_BD, height=286)
        self._file_zone.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._file_zone.grid_propagate(False)
        self._file_zone.grid_columnconfigure(0, weight=1)
        self._file_zone.grid_rowconfigure(0, weight=1)
        self._file_zone.grid_rowconfigure(4, weight=1)

        self._zone_icon = ctk.CTkLabel(self._file_zone, image=self._ico_drop, text="")
        self._zone_icon.grid(row=1, column=0)
        self._zone_text = ctk.CTkLabel(
            self._file_zone, text="Drop an audio file",
            font=(self.F, 15), text_color=self._TXT_HI, wraplength=300)
        self._zone_text.grid(row=2, column=0, pady=(14, 2))
        self._zone_sub = ctk.CTkLabel(
            self._file_zone, text="MP3   ·   WAV   ·   FLAC",
            font=(self.F, 11), text_color=self._TXT_DIM)
        self._zone_sub.grid(row=3, column=0)
        self.btn_select = ctk.CTkButton(
            self._file_zone, text="Browse Files", command=self.select_file,
            width=140, height=34, font=(self.F, 12), fg_color="transparent",
            border_width=1, border_color=self._DIM, hover_color=self._CARD_WELL,
            text_color=self._TXT_MID, corner_radius=17)
        self.btn_select.grid(row=4, column=0, pady=(18, 0), sticky="n")

        # Model card
        card = ctk.CTkFrame(
            body, fg_color=self._CARD_BG, corner_radius=14,
            border_width=1, border_color=self._CARD_BD, height=286)
        card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))
        head.grid_columnconfigure(1, weight=1)
        self._eng_icon = ctk.CTkLabel(head, image=self._ico_engine["demucs"], text="")
        self._eng_icon.grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(
            head, text="MODEL", font=(self.F, 10, "bold"),
            text_color=self._TXT_DIM).grid(row=0, column=1, sticky="w")

        self.opt_model = ctk.CTkOptionMenu(
            card, values=[registry.menu_label(m) for m in self._models],
            height=38, font=(self.F, 13), fg_color=self._CARD_WELL,
            button_color="#2A2A42", button_hover_color="#38385A",
            dropdown_fg_color=self._CARD_WELL, dropdown_font=(self.F, 12),
            text_color=self._TXT_HI, corner_radius=8,
            command=self.update_model_desc)
        self.opt_model.grid(row=1, column=0, sticky="ew", padx=20, pady=(10, 14))

        # Fixed height: descriptions run to one or two wrapped lines depending on
        # the model, and the window is a fixed size — letting the card grow would
        # change the layout every time the selection changed.
        self.lbl_model_desc = ctk.CTkLabel(
            card, text="", font=(self.F, 12), text_color=self._TXT_MID,
            wraplength=400, height=52, anchor="nw", justify="left")
        self.lbl_model_desc.grid(row=2, column=0, sticky="ew", padx=20)

        # Download state, license and rough CPU cost for the selected model.
        well = ctk.CTkFrame(card, fg_color=self._CARD_WELL, corner_radius=8)
        well.grid(row=3, column=0, sticky="ew", padx=20, pady=(4, 16))
        well.grid_columnconfigure(1, weight=1)
        self._meta_icon = ctk.CTkLabel(well, image=self._ico_download, text="")
        self._meta_icon.grid(row=0, column=0, padx=(12, 0))
        self.lbl_model_meta = ctk.CTkLabel(
            well, text="", font=(self.F, 11), text_color=self._TXT_DIM,
            wraplength=400, justify="left", anchor="w")
        self.lbl_model_meta.grid(row=0, column=1, sticky="ew", padx=10, pady=9)

    # ── Options: one horizontal band ──────────────────────────────────────────

    def _build_options(self):
        band = ctk.CTkFrame(
            self, fg_color=self._CARD_BG, corner_radius=14,
            border_width=1, border_color=self._CARD_BD)
        band.grid(row=2, column=0, sticky="ew", padx=self._PAD, pady=(16, 0))
        band.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(band, image=self._ico_mic, text="").grid(
            row=0, column=0, padx=(20, 8), pady=18)
        self.chk_karaoke = ctk.CTkCheckBox(
            band, text="Karaoke Mode", font=(self.F, 13), text_color=self._TXT_MID,
            fg_color=self._ACCENT, hover_color=self._ACCENT_HO,
            border_color=self._DIM, checkmark_color="white",
            checkbox_width=20, checkbox_height=20)
        self.chk_karaoke.grid(row=0, column=1, padx=(0, 26))

        ctk.CTkLabel(band, image=self._ico_sparkle, text="").grid(
            row=0, column=2, padx=(0, 8))
        self.chk_quality = ctk.CTkCheckBox(
            band, text="High Quality", font=(self.F, 13), text_color=self._TXT_MID,
            fg_color=self._ACCENT, hover_color=self._ACCENT_HO,
            border_color=self._DIM, checkmark_color="white",
            checkbox_width=20, checkbox_height=20)
        self.chk_quality.grid(row=0, column=3, padx=(0, 8))
        ctk.CTkLabel(
            band, text="2× slower", font=(self.F, 10),
            text_color=self._TXT_DIM).grid(row=0, column=4, sticky="w")

        ctk.CTkLabel(band, image=self._ico_file, text="").grid(
            row=0, column=6, padx=(0, 8))
        ctk.CTkLabel(
            band, text="OUTPUT", font=(self.F, 10, "bold"),
            text_color=self._TXT_DIM).grid(row=0, column=7, padx=(0, 10))
        self.seg_format = ctk.CTkSegmentedButton(
            band, values=["WAV", "FLAC"], width=150, height=32,
            font=(self.F, 12), fg_color=self._CARD_WELL,
            selected_color=self._ACCENT, selected_hover_color=self._ACCENT_HO,
            unselected_color=self._CARD_WELL, unselected_hover_color=self._DIM,
            text_color=self._TXT_HI, corner_radius=8,
            command=self._update_format_hint)
        self.seg_format.grid(row=0, column=8)
        self.seg_format.set("WAV")
        self.lbl_format_hint = ctk.CTkLabel(
            band, text="Uncompressed", font=(self.F, 10),
            text_color=self._TXT_DIM, width=104, anchor="w")
        self.lbl_format_hint.grid(row=0, column=9, padx=(12, 20))

    # ── Action: run / cancel, then progress ───────────────────────────────────

    def _build_action(self):
        act = ctk.CTkFrame(self, fg_color="transparent")
        act.grid(row=3, column=0, sticky="ew", padx=self._PAD, pady=(16, self._PAD))
        act.grid_columnconfigure(0, weight=1)

        # Run and Cancel share one cell: only one is ever meaningful, and
        # swapping them keeps the layout height fixed.
        self.btn_run = ctk.CTkButton(
            act, text="  SEPARATE STEMS", image=self._ico_bolt, compound="left",
            command=self.start_separation, state="disabled", height=52,
            font=(self.F, 15, "bold"), fg_color=self._ACCENT,
            hover_color=self._ACCENT_HO, text_color="white", corner_radius=12)
        self.btn_run.grid(row=0, column=0, sticky="ew")

        self.btn_cancel = ctk.CTkButton(
            act, text="✕   CANCEL", command=self._cancel_separation,
            height=52, font=(self.F, 14), fg_color="transparent",
            border_width=1, border_color="#553344", hover_color="#1A0A12",
            text_color="#CC4466", corner_radius=12)
        self.btn_cancel.grid(row=0, column=0, sticky="ew")
        self.btn_cancel.grid_remove()

        prog = ctk.CTkFrame(act, fg_color="transparent")
        prog.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        prog.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(
            prog, height=4, progress_color=self._ACCENT,
            fg_color="#1C1C2E", corner_radius=2)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=0, sticky="ew")

        foot = ctk.CTkFrame(prog, fg_color="transparent")
        foot.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        foot.grid_columnconfigure(0, weight=1)
        self.lbl_status = ctk.CTkLabel(
            foot, text="Ready", font=(self.F, 11),
            text_color=self._TXT_DIM, anchor="w")
        self.lbl_status.grid(row=0, column=0, sticky="w")
        self.lbl_attribution = ctk.CTkLabel(
            foot, text="Powered by Demucs", font=(self.F, 11),
            text_color=self._ACCENT, cursor="hand2", anchor="e")
        self.lbl_attribution.grid(row=0, column=1, sticky="e")
        self.lbl_attribution.bind("<Button-1>", self.open_attribution)

    def report_callback_exception(self, exc, val, tb):
        """Send exceptions raised inside widget callbacks to the error log.

        Tk's default handler prints them to stderr — which is a DummyStream
        under --noconsole — so a failure in any button or menu callback would
        otherwise vanish without a trace. Only the first one raises a dialog:
        a callback that fails once usually fails every time it is invoked, and
        a loop of modal errors would be worse than the original fault.
        """
        log_error("".join(traceback.format_exception(exc, val, tb)))
        if not self._reported_ui_error:
            self._reported_ui_error = True
            messagebox.showerror(
                "Unexpected Error",
                f"Something went wrong inside the interface:\n\n{val}\n\n"
                f"Details were saved to:\n{LOG_FILE}",
            )

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
        webbrowser.open(self._attribution_url)

    def _show_about(self, event=None):
        if self._about_win is not None and self._about_win.winfo_exists():
            self._about_win.lift()
            self._about_win.focus_force()
            return

        win = ctk.CTkToplevel(self, fg_color=self._WIN_BG)
        self._about_win = win
        win.title(f"About {config.APP_NAME}")
        win.geometry("420x560")
        win.resizable(False, False)
        win.transient(self)

        # The 256px app icon, shown here rather than shipped unused — the window
        # and taskbar icons come from rend.ico, not this PNG.
        self._ico_app = ctk.CTkImage(
            light_image=Image.open(resource_path(os.path.join("assets", "app_icon.png"))),
            dark_image=Image.open(resource_path(os.path.join("assets", "app_icon.png"))),
            size=(72, 72))
        ctk.CTkLabel(win, image=self._ico_app, text="").pack(pady=(22, 8))

        ctk.CTkLabel(
            win, text=config.APP_NAME,
            font=(self.F, 24, "bold"), text_color="white",
        ).pack(pady=(24, 0))
        ctk.CTkLabel(
            win, text=f"v{config.APP_VERSION}",
            font=(self.F, 12), text_color=self._ACCENT,
        ).pack()
        ctk.CTkLabel(
            win, text=config.APP_TAGLINE,
            font=(self.F, 11), text_color=self._TXT_MID,
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
            font=(self.F, 11), text_color=health_color,
        ).pack(pady=(0, 10))

        credits_frame = ctk.CTkFrame(
            win, fg_color=self._CARD_BG, corner_radius=10,
            border_width=1, border_color=self._CARD_BD,
        )
        credits_frame.pack(padx=24, pady=(0, 12), fill="x")
        ctk.CTkLabel(
            credits_frame, text="BUILT WITH",
            font=(self.F, 9), text_color=self._TXT_DIM,
        ).pack(anchor="w", padx=16, pady=(10, 2))
        for name, license_name, url in config.CREDITS:
            lbl = ctk.CTkLabel(
                credits_frame, text=f"{name}  ·  {license_name}",
                font=(self.F, 11), text_color=self._TXT_MID,
                cursor="hand2",
            )
            lbl.pack(anchor="w", padx=16)
            lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        ctk.CTkLabel(credits_frame, text="", font=(self.F, 2)).pack(pady=(0, 6))

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=(0, 8))
        ctk.CTkButton(
            btn_row, text="Report a Bug",
            command=lambda: webbrowser.open(config.BUG_REPORT_URL),
            width=130, height=30, font=(self.F, 12),
            fg_color=self._ACCENT, hover_color=self._ACCENT_HO,
        ).grid(row=0, column=0, padx=6)
        ctk.CTkButton(
            btn_row, text="GitHub",
            command=lambda: webbrowser.open(config.REPO_URL),
            width=130, height=30, font=(self.F, 12),
            fg_color="transparent", border_width=1,
            border_color=self._DIM, hover_color="#1a1a38",
            text_color=self._TXT_MID,
        ).grid(row=0, column=1, padx=6)

        ctk.CTkLabel(
            win, text=config.COPYRIGHT,
            font=(self.F, 10), text_color=self._TXT_DIM,
        ).pack()
        ctk.CTkLabel(
            win, text=f"Error log: {LOG_FILE}",
            font=(self.F, 9), text_color=self._TXT_DIM,
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
            short = fname if len(fname) <= 34 else fname[:31] + "…"
            self._zone_text.configure(text=short, text_color=self._TXT_HI)
            self._zone_sub.configure(
                text=os.path.splitext(fname)[1].upper().lstrip(".") + " file selected",
                text_color=self._TXT_MID,
            )
            self._file_zone.configure(border_color=self._CARD_BD_HI)
            self.btn_select.configure(text="Change File")
            self.btn_run.configure(state="normal")

    def _confirm_model_download(self, model):
        """License gate shown before the first download of a model's weights.

        Rend never bundles or rehosts these checkpoints — several are published
        with no license grant at all (see registry.py), so the first use of one
        is the moment to say where the file comes from and under what terms.
        Returns True to proceed. Once the weights are on disk is_installed() is
        True and the gate is not shown again for that model.
        """
        win = ctk.CTkToplevel(self, fg_color=self._WIN_BG)
        win.title("Download model")
        win.geometry("470x400")
        win.resizable(False, False)
        win.transient(self)

        result = {"ok": False}

        ctk.CTkLabel(
            win, text=model.display_name,
            font=(self.F, 15, "bold"), text_color="white",
            wraplength=410, justify="left",
        ).pack(padx=28, pady=(24, 4), anchor="w")
        ctk.CTkLabel(
            win, text="These weights are not included in Rend and will be downloaded now.",
            font=(self.F, 12), text_color=self._TXT_MID,
            wraplength=410, justify="left",
        ).pack(padx=28, pady=(0, 14), anchor="w")

        facts = ctk.CTkFrame(
            win, fg_color=self._CARD_BG, corner_radius=10,
            border_width=1, border_color=self._CARD_BD,
        )
        facts.pack(padx=28, pady=(0, 14), fill="x")
        source = model.files[0].url.split("/")[2] if model.files else "the model author"
        for field, value in (
            ("Size",    registry.format_size(registry.download_size(model))),
            ("From",    source),
            ("License", model.license or "None declared"),
        ):
            row = ctk.CTkFrame(facts, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(
                row, text=field, font=(self.F, 11), text_color=self._TXT_DIM, width=60, anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=value, font=(self.F, 12), text_color=self._TXT_HI,
                wraplength=320, justify="left", anchor="w",
            ).pack(side="left")

        if not model.redistributable:
            ctk.CTkLabel(
                win,
                text="The author publishes this model without a license grant, so Rend "
                     "downloads it from their page rather than bundling it. Review the "
                     "model page before using its output in a released project.",
                font=(self.F, 11), text_color=self._STATUS_WARN,
                wraplength=410, justify="left",
            ).pack(padx=28, pady=(0, 8), anchor="w")

        if model.license_url:
            link = ctk.CTkLabel(
                win, text="Open the model page",
                font=(self.F, 11), text_color="#00FFFF", cursor="hand2",
            )
            link.pack(padx=28, anchor="w")
            link.bind("<Button-1>", lambda e: webbrowser.open(model.license_url))

        if self._online_ok is False:
            ctk.CTkLabel(
                win, text="● You appear to be offline — the download will fail.",
                font=(self.F, 11), text_color=self._STATUS_ERR,
                wraplength=410, justify="left",
            ).pack(padx=28, pady=(8, 0), anchor="w")

        def choose(ok):
            result["ok"] = ok
            win.destroy()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=(16, 0))
        ctk.CTkButton(
            btn_row, text="Cancel", command=lambda: choose(False),
            width=120, height=32, font=(self.F, 12),
            fg_color="transparent", border_width=1, border_color=self._DIM,
            hover_color="#1a1a38", text_color=self._TXT_MID,
        ).grid(row=0, column=0, padx=6)
        ctk.CTkButton(
            btn_row, text="Download & Separate", command=lambda: choose(True),
            width=170, height=32, font=(self.F, 12),
            fg_color=self._ACCENT, hover_color=self._ACCENT_HO,
        ).grid(row=0, column=1, padx=6)

        win.protocol("WM_DELETE_WINDOW", lambda: choose(False))
        # CTkToplevel is not viewable the instant it is created, and grab_set on
        # a window that isn't mapped yet raises TclError — so defer the grab.
        win.after(200, win.grab_set)
        self.wait_window(win)
        return result["ok"]

    def start_separation(self):
        if not self.file_path: return

        model = self._model_by_label.get(self.opt_model.get())
        if model is None:
            return

        # First use of a downloadable model: take consent before any network
        # traffic. The engine downloads the weights as its first step, so the
        # gate has to happen here, before the worker thread starts.
        if model.downloadable and not registry.is_installed(model):
            if not self._confirm_model_download(model):
                return

        self.btn_run.grid_remove()   # Separate and Cancel share the same cell
        self.btn_cancel.grid()
        self.btn_select.configure(state="disabled")
        self.chk_quality.configure(state="disabled")
        self.chk_karaoke.configure(state="disabled")
        self.opt_model.configure(state="disabled")
        self.seg_format.configure(state="disabled")
        self.progress_bar.set(0)

        output_dir = output_folder_for(self.file_path)

        # Get Options
        shifts = 2 if self.chk_quality.get() == 1 else 1
        two_stems = self.chk_karaoke.get() == 1
        output_format = self.seg_format.get().lower()  # "WAV"/"FLAC" -> "wav"/"flac"

        self._stop_event = threading.Event()
        self.worker = SeparationThread(
            input_file=self.file_path,
            output_folder=output_dir,
            model_name=model.id,
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
        self.btn_cancel.configure(state="normal", text="✕   CANCEL")  # re-arm
        self.btn_cancel.grid_remove()              # swap Cancel back to Separate
        self.btn_run.grid()
        self.btn_select.configure(state="normal")
        self.chk_quality.configure(state="normal")
        self.chk_karaoke.configure(state="normal")
        self.opt_model.configure(state="normal")
        self.seg_format.configure(state="normal")
        # A model may have been downloaded during the run just finished — drop
        # its download badge (and re-apply the Karaoke rule for the selection).
        self._refresh_model_menu()
        self._reset_file_zone()

    def _reset_file_zone(self):
        self.file_path = None
        self._zone_text.configure(text="Drop an audio file", text_color=self._TXT_HI)
        self._zone_sub.configure(text="MP3   ·   WAV   ·   FLAC", text_color=self._TXT_DIM)
        self._file_zone.configure(border_color=self._CARD_BD)
        self.btn_select.configure(text="Browse Files")
        self.btn_run.configure(state="disabled")

    def _deferred_reset(self):
        try:
            self.reset_ui()
        except tk.TclError:
            pass  # window was closed during the post-cancel delay

    def _cancel_separation(self):
        # Cancelling is not instant — the engine only stops when it reaches a
        # checkpoint between chunks — so say so. Without this the button simply
        # greys out, the progress bar freezes, and it reads as a hang.
        self.btn_cancel.configure(state="disabled", text="CANCELLING…")
        self.lbl_status.configure(text="Cancelling — finishing the current chunk…")
        self._stop_event.set()

    def _refresh_model_menu(self):
        """Rebuild the picker's labels and reapply the current selection.

        Labels carry a "↓ 913 MB" badge for weights that aren't on disk, so they
        go stale the moment a download finishes. Called at startup and after
        every run, which is when that can have changed.
        """
        labels = [registry.menu_label(m) for m in self._models]
        self._model_by_label = dict(zip(labels, self._models))
        self.opt_model.configure(values=labels)
        # Selection is tracked by model id, not label: the label may have just
        # lost its download badge.
        current = next(
            (lbl for lbl, m in self._model_by_label.items() if m.id == self._selected_id),
            labels[0],
        )
        self.opt_model.set(current)
        self.update_model_desc(current)   # set() does not fire the command

    def _model_meta_text(self, model):
        """The small line under the description: download state, license, cost.

        Returns (text, pending_download) — the caller shows the download arrow
        icon only when there is actually something to fetch.
        """
        parts = []
        pending = model.downloadable and not registry.is_installed(model)
        if model.downloadable:
            parts.append(f"{registry.format_size(registry.download_size(model))} on first use"
                         if pending else "Downloaded")
            parts.append(f"License: {model.license}")
        if model.cpu_x_realtime:
            parts.append(f"~{model.cpu_x_realtime:g}× song length on CPU")
        return "   ·   ".join(parts) or "Weights managed automatically", pending

    def update_model_desc(self, choice):
        model = self._model_by_label.get(choice)
        if model is None:
            return
        self._selected_id = model.id
        accent = self._ENGINE_ACCENT.get(model.engine, self._ACCENT)
        self.lbl_model_desc.configure(text=model.description)

        meta, pending = self._model_meta_text(model)
        self.lbl_model_meta.configure(text=meta)
        # The arrow only appears when weights are actually still to be fetched.
        if pending:
            self._meta_icon.grid()
        else:
            self._meta_icon.grid_remove()

        icon = self._ico_engine.get(model.engine)
        if icon is not None:
            self._eng_icon.configure(image=icon)

        # Karaoke Mode needs a clean vocals split. Models without one (the
        # 6-stem Demucs, whose stem naming differs, and the guitar RoFormer)
        # clear and disable the checkbox so the two can't both be selected.
        if model.karaoke:
            self.chk_karaoke.configure(state="normal", text_color=self._TXT_MID)
        else:
            self.chk_karaoke.deselect()
            self.chk_karaoke.configure(state="disabled", text_color=self._TXT_DIM)

        credit, url = self._ENGINE_CREDIT.get(model.engine, self._ENGINE_CREDIT["demucs"])
        self.lbl_attribution.configure(text=credit, text_color=accent)
        self._attribution_url = url

if __name__ == "__main__":
    app = App()
    app.mainloop()
